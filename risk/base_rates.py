"""Base rates COMPUTED from data (ASSUMED_ANSWERS.md §7). Never typed in.

- exploit probability per protocol-year: DefiLlama hacks / protocol-years of exposure, bucketed by category group,
  age (<2y / >=2y) and TVL (<$100M / $100M-1B / >=$1B); Jeffreys estimate (k + 0.5) / T; coarser bucket when T is thin.
- loss given exploit: (amount - returned) / protocol TVL the day before the hack, for the largest hacks in the window.
- depeg frequency & depth: daily prices (DefiLlama coins), episodes below 0.99 / 0.97 / 0.90 and their duration,
  per coin-year, by stablecoin class.
- oracle failure: staleness events (gap > 1.5x observed heartbeat) per feed-year from the full AnswerUpdated history.

If a fetch fails, the matching value falls back to ASSUMED_ANSWERS.md fallback_priors, tagged placeholder_prior.

    python -m risk.base_rates [--offline]     -> data/base_rates.json
"""
from __future__ import annotations

import json
import statistics
import sys
import time
from collections import defaultdict

import requests

from core.config import PLACEHOLDER, SOURCE, cfg
from core.fork import ROOT, DiskCache

API = DiskCache("api")
OUT = ROOT / "data" / "base_rates.json"
YEAR = 365.25 * 86400
WINDOW_YEARS = 3.0                  # exploit window: the current DeFi security regime (assumption, see table)
MIN_EXPOSURE_YEARS = 50.0           # below this, back off to the coarser bucket
MATERIAL_LOSS_SHARE = 0.01          # an "exploit" event = net loss >= 1% of protocol TVL (keeps frequency & LGD consistent)
NON_DEFI = {"CEX", "Chain", "Wallet"}
METHOD_PARAMS = {"window_years": WINDOW_YEARS, "min_exposure_protocol_years": MIN_EXPOSURE_YEARS,
                 "material_loss_share": MATERIAL_LOSS_SHARE, "jeffreys_prior": 0.5}

CATEGORY_GROUP = {
    "Lending": "lending", "CDP": "lending", "NFT Lending": "lending", "Uncollateralized Lending": "lending",
    "RWA Lending": "lending", "Dexs": "dex_derivatives", "DEX Aggregator": "dex_derivatives",
    "Derivatives": "dex_derivatives", "Options": "dex_derivatives", "Yield": "yield_vault",
    "Yield Aggregator": "yield_vault", "Leveraged Farming": "yield_vault", "Basis Trading": "yield_vault",
    "Liquid Staking": "staking", "Liquid Restaking": "staking", "Restaking": "staking",
    "Algo-Stables": "stable_synthetic", "Synthetics": "stable_synthetic", "Bridge": "bridge",
    "Cross Chain": "bridge", "RWA": "rwa",
}
STABLES = {
    "fiat_backed": ["usd-coin", "tether", "true-usd", "first-digital-usd", "binance-usd", "paypal-usd"],
    "crypto_backed": ["dai", "liquity-usd", "crvusd", "gho"],
    "synthetic": ["ethena-usde", "terrausd", "frax", "usdd", "nusd"],
    # post-2024 yield-bearing synthetic / delta-neutral / RWA-backed dollars: comparables for the hero #2 collateral
    # roots (trUSD, iUSD are in the set themselves). Which coins count as comparable is a Fault Line choice (assumption
    # shown in the UI): every coin of this kind with DefiLlama history, failures (USR, USDX) included.
    "yield_synthetic": ["tori-trusd", "infinifi-usd", "resolv-usr", "usdx-money-usdx", "usual-usd", "falcon-finance",
                        "f-x-protocol-fxusd"],
}
THRESHOLDS = (0.99, 0.97, 0.90, 0.75, 0.50)


def _get(key: str, url: str, offline: bool, trim=None, method="GET", body=None):
    hit = API.get(key)
    if hit is not None or offline:
        return hit
    r = requests.request(method, url, json=body, timeout=120)
    r.raise_for_status()
    data = r.json()
    return API.put(key, {"fetched_at": int(time.time()), "data": trim(data) if trim else data})


def _rate(k: int, T: float) -> float:
    return (k + 0.5) / T if T > 0 else float("nan")


def tvl_bucket(tvl: float | None) -> str:
    tvl = tvl or 0.0
    return ">=1B" if tvl >= 1e9 else ("100M-1B" if tvl >= 1e8 else "<100M")


# --------------------------------------------------------------------------- exploits
def protocols(offline: bool) -> list[dict]:
    d = _get("llama_protocols_meta", "https://api.llama.fi/protocols", offline, trim=lambda d: [
        {"id": str(p.get("id")), "slug": p.get("slug"), "name": p.get("name"), "category": p.get("category"),
         "listedAt": p.get("listedAt"), "tvl": p.get("tvl"), "parentProtocol": p.get("parentProtocol"),
         "audits": p.get("audits")} for p in d])
    return d["data"]


def hacks(offline: bool) -> dict:
    return _get("llama_hacks", "https://api.llama.fi/hacks", offline)


def _loss_share(h: dict, p: dict, tvl_before: dict) -> tuple[float, float]:
    """(net loss / TVL at hack, TVL used). TVL before the hack where fetched, else max(current TVL, amount)."""
    net = max(0.0, (h.get("amount") or 0.0) - (h.get("returnedFunds") or 0.0))
    tvl = tvl_before.get((h["name"], h["date"])) or max(p.get("tvl") or 0.0, h.get("amount") or 0.0)
    return (min(1.0, net / tvl) if tvl else 1.0), tvl


def exploit_rates(offline: bool = False, tvl_before: dict | None = None) -> dict:
    now = time.time()
    tvl_before = tvl_before or {}
    w0 = now - WINDOW_YEARS * YEAR
    protos = protocols(offline)
    hk = hacks(offline)
    # protocols without listedAt were listed before DefiLlama tracked the field: give them the earliest listedAt
    first_listed = min(p["listedAt"] for p in protos if p.get("listedAt"))
    protos = [p | {"listedAt": p.get("listedAt") or first_listed, "listed_imputed": not p.get("listedAt")} for p in protos]
    by_id = {p["id"]: p for p in protos}
    expo: dict[tuple, float] = defaultdict(float)
    for p in protos:
        if p.get("category") in NON_DEFI:
            continue
        g, tb, lst = CATEGORY_GROUP.get(p.get("category"), "other"), tvl_bucket(p.get("tvl")), p["listedAt"]
        young = max(0.0, min(now, lst + 2 * YEAR) - max(w0, lst))
        old = max(0.0, now - max(w0, lst + 2 * YEAR))
        expo[(g, "<2y", tb)] += young / YEAR
        expo[(g, ">=2y", tb)] += old / YEAR
    cnt: dict[tuple, int] = defaultdict(int)
    n_matched, material = 0, []
    for h in hk["data"]:
        p = by_id.get(str(h.get("defillamaId")))
        if not p or not h.get("date") or h["date"] < w0 or p.get("category") in NON_DEFI \
                or h.get("targetType") not in ("DeFi Protocol", "Liquidity Pool", None):
            continue
        n_matched += 1
        share, tvl = _loss_share(h, p, tvl_before)
        if share < MATERIAL_LOSS_SHARE:
            continue
        age = "<2y" if h["date"] - p["listedAt"] < 2 * YEAR else ">=2y"
        tb = tvl_bucket(tvl)          # TVL at hack (a hack shrinks TVL afterwards)
        cnt[(CATEGORY_GROUP.get(p.get("category"), "other"), age, tb)] += 1
        material.append({"name": h["name"], "date": h["date"], "loss_share": share, "tvl": tvl, "bucket": f"{age}|{tb}"})
    buckets = {}
    for key, T in expo.items():
        if T <= 0:
            continue
        buckets["|".join(key)] = {"hacks": cnt.get(key, 0), "protocol_years": round(T, 1),
                                  "p_annual": _rate(cnt.get(key, 0), T)}
    shares = [m["loss_share"] for m in material]
    lgd_by_tvl = {}
    for tb in ("<100M", "100M-1B", ">=1B"):
        xs = [m["loss_share"] for m in material if m["bucket"].endswith(tb)]
        lgd_by_tvl[tb] = {"n": len(xs), "median": statistics.median(xs) if xs else None}
    return {"buckets": buckets, "window_years": WINDOW_YEARS, "n_hacks_matched": n_matched,
            "n_material": len(material), "material": material,
            "lgd_material_median": statistics.median(shares) if shares else None,
            "lgd_by_tvl_bucket": lgd_by_tvl,
            "lgd_material_p75": statistics.quantiles(shares, n=4)[2] if len(shares) >= 4 else None,
            "fetched_at": hk["fetched_at"],
            "n_listed_imputed": sum(p["listed_imputed"] for p in protos),
            "method": f"material exploits (net loss >= {MATERIAL_LOSS_SHARE:.0%} of TVL) per protocol-year, Jeffreys "
                      "(k+0.5)/T; DeFi only (CEX/chain/wallet excluded); TVL at hack = TVL history where fetched, else "
                      "max(current TVL, amount); exposure bucketed by current TVL; missing listedAt = earliest listedAt"}


def exploit_p(rates: dict, category: str | None, listed_at: float | None, tvl: float | None) -> tuple[float, str]:
    """Annual exploit probability for a protocol; backs off to coarser buckets when exposure is thin."""
    g = CATEGORY_GROUP.get(category, "other")
    age = "<2y" if listed_at and time.time() - listed_at < 2 * YEAR else ">=2y"
    tb = tvl_bucket(tvl)
    B = rates["buckets"]
    k = f"{g}|{age}|{tb}"
    if k in B and B[k]["protocol_years"] >= MIN_EXPOSURE_YEARS:
        return B[k]["p_annual"], k
    # back off keeping TVL size (what separates a blue chip from the long tail) as long as possible
    def m(pat):
        pg, pa, pt = pat.split("|")
        return lambda x: all(q in ("*", y) for q, y in zip((pg, pa, pt), x.split("|")))
    for label in (f"{g}|*|{tb}", f"*|{age}|{tb}", f"*|*|{tb}", f"{g}|{age}|*", f"{g}|*|*"):
        sel = [v for kk, v in B.items() if m(label)(kk)]
        T = sum(v["protocol_years"] for v in sel)
        if T >= MIN_EXPOSURE_YEARS:
            return _rate(sum(v["hacks"] for v in sel), T), label
    T = sum(v["protocol_years"] for v in B.values())
    return _rate(sum(v["hacks"] for v in B.values()), T), "*|*|*"


def tvl_series(slug: str, offline: bool) -> list[list[float]]:
    """Daily [date, tvl] for a protocol (trimmed from DefiLlama /protocol/{slug}, ~15MB raw)."""
    d = _get(f"llama_tvl_series_{slug}", f"https://api.llama.fi/protocol/{slug}", offline,
             trim=lambda d: [[x["date"], x["totalLiquidityUSD"]] for x in (d.get("tvl") or [])])
    return (d or {}).get("data") or []


def lgd_for(rates: dict, tvl: float | None, min_n: int = 5) -> tuple[float, str]:
    """Loss-given-exploit for a protocol's size; backs off to >=100M pooled, then all material exploits."""
    B, tb = rates["lgd_by_tvl_bucket"], tvl_bucket(tvl)
    if B[tb]["n"] >= min_n:
        return B[tb]["median"], tb
    big = [m["loss_share"] for m in rates["material"] if not m["bucket"].endswith("<100M")]
    if tb != "<100M" and len(big) >= min_n:
        return statistics.median(big), ">=100M"
    return rates["lgd_material_median"], "all"


def loss_given_exploit(offline: bool = False, workers: int = 8) -> dict:
    """Net loss / TVL the day before, for EVERY in-window DeFi hack whose protocol has a TVL history."""
    from concurrent.futures import ThreadPoolExecutor
    now = time.time()
    protos = {p["id"]: p for p in protocols(offline)}
    hk = [h for h in hacks(offline)["data"] if h.get("date", 0) >= now - WINDOW_YEARS * YEAR and h.get("amount")
          and str(h.get("defillamaId")) in protos and protos[str(h["defillamaId"])].get("category") not in NON_DEFI]
    slugs = sorted({protos[str(h["defillamaId"])]["slug"] for h in hk})

    def fetch(sl):
        try:
            return sl, tvl_series(sl, offline)
        except Exception:
            return sl, []
    with ThreadPoolExecutor(workers) as ex:
        series = dict(ex.map(fetch, slugs))
    out = []
    for h in hk:
        ser = [x for x in series.get(protos[str(h["defillamaId"])]["slug"], []) if h["date"] - 7 * 86400 <= x[0] <= h["date"]]
        if not ser or not ser[-1][1]:
            continue
        net = max(0.0, h["amount"] - (h.get("returnedFunds") or 0))
        out.append({"name": h["name"], "date": h["date"], "loss": net, "tvl_before": ser[-1][1],
                    "lgd": min(1.0, net / ser[-1][1])})
    lg = [x["lgd"] for x in out]
    return {"n": len(lg), "n_hacks": len(hk), "n_protocols_fetched": sum(bool(v) for v in series.values()),
            "median": statistics.median(lg) if lg else None, "sample": out,
            "method": "net loss / protocol TVL within 7 days before the hack (DefiLlama TVL history)"}


# --------------------------------------------------------------------------- depegs
def price_history(cg_id: str, offline: bool, start: int = 1577836800) -> list[tuple[int, float]]:
    pts, t = [], start
    now = int(time.time())
    while t < now:
        d = _get(f"llama_px_{cg_id}_{t}", f"https://coins.llama.fi/chart/coingecko:{cg_id}?start={t}&span=500&period=1d",
                 offline, trim=lambda d: d.get("coins", {}).get(f"coingecko:{cg_id}", {}).get("prices", []))
        chunk = (d or {}).get("data") or []
        pts += [(p["timestamp"], p["price"]) for p in chunk]
        t += 500 * 86400
    return sorted(set(pts))


def episodes(px: list[tuple[int, float]], thr: float) -> list[dict]:
    out, cur = [], None
    for ts, p in px:
        if p < thr:
            if cur is None:
                cur = {"start": ts, "end": ts, "min": p, "days": 1}
            else:
                cur.update(end=ts, min=min(cur["min"], p), days=cur["days"] + 1)
        elif cur is not None:
            out.append(cur)
            cur = None
    if cur:
        out.append(cur)
    return out


def depeg_rates(offline: bool = False) -> dict:
    res = {}
    for cls, ids in STABLES.items():
        coin_years, per_thr = 0.0, {t: {"episodes": 0, "episodes_over_24h": 0, "durations_days": [], "min": []} for t in THRESHOLDS}
        coins = {}
        for cid in ids:
            px = price_history(cid, offline)
            if len(px) < 30:
                continue
            yrs = (px[-1][0] - px[0][0]) / YEAR
            coin_years += yrs
            coins[cid] = {"years": round(yrs, 2), "min_price": min(p for _, p in px)}
            for t in THRESHOLDS:
                eps = episodes(px, t)
                coins[cid][f"p_annual_over_24h<{t}"] = _rate(sum(e["days"] >= 2 for e in eps), yrs)
                per_thr[t]["episodes"] += len(eps)
                per_thr[t]["episodes_over_24h"] += sum(e["days"] >= 2 for e in eps)
                per_thr[t]["durations_days"] += [e["days"] for e in eps]
                per_thr[t]["min"] += [e["min"] for e in eps]
                coins[cid][f"episodes<{t}"] = len(eps)
        res[cls] = {"coin_years": round(coin_years, 1), "coins": coins, "thresholds": {
            str(t): {"episodes": v["episodes"], "episodes_over_24h": v["episodes_over_24h"],
                     "p_annual": _rate(v["episodes"], coin_years) if coin_years else None,
                     "p_annual_over_24h": _rate(v["episodes_over_24h"], coin_years) if coin_years else None,
                     "median_duration_days": statistics.median(v["durations_days"]) if v["durations_days"] else None,
                     "median_trough": statistics.median(v["min"]) if v["min"] else None}
            for t, v in per_thr.items()},
            # every episode below the first threshold, for severity sampling: trough price and length in days
            "episode_troughs": sorted(per_thr[THRESHOLDS[0]]["min"]),
            "episode_days": per_thr[THRESHOLDS[0]]["durations_days"]}
    return {"classes": res, "method": "daily prices (DefiLlama coins, CoinGecko ids), runs below threshold; "
                                      ">24h = >=2 consecutive daily points; daily data misses intraday CEX wicks"}


# --------------------------------------------------------------------------- oracles
def oracle_failure_rates(feeds: dict[str, str], offline: bool = False) -> dict:
    """feeds: {label: aggregator address}. Full AnswerUpdated history from Etherscan."""
    from core.etherscan import get_logs
    from discovery.oracle_quality import ANSWER_UPDATED
    out = {}
    for label, agg in feeds.items():
        logs = get_logs(agg, ANSWER_UPDATED, 0, 99_999_999)   # cached; current aggregator phase only
        ts = sorted(int(x["timeStamp"], 16) for x in logs)
        if len(ts) < 10:
            out[label] = {"n_updates": len(ts)}
            continue
        gaps = sorted(b - a for a, b in zip(ts, ts[1:]))
        hb = gaps[int(0.95 * (len(gaps) - 1))]
        stale = sum(g > 1.5 * hb for g in gaps)
        yrs = (ts[-1] - ts[0]) / YEAR
        out[label] = {"aggregator": agg, "n_updates": len(ts), "years": round(yrs, 2), "heartbeat_p95_s": hb,
                      "stale_events": stale, "p_stale_annual": _rate(stale, yrs), "max_gap_s": gaps[-1]}
    return out


# --------------------------------------------------------------------------- assemble
def compute(offline: bool = False, feeds: dict[str, str] | None = None) -> dict:
    fb = cfg()["fallback_priors"]
    out: dict = {"source": "computed from data", "generated_at": int(time.time()), "values": {}, "detail": {},
                 "method_params": {k: {"value": v, "source": "method choice (Fault Line), shown in Assumptions"}
                                   for k, v in METHOD_PARAMS.items()}}

    def put(name, fn, extract, fallback_key, why):
        try:
            d = fn()
            v = extract(d)
            if v is None:
                raise ValueError("no data")
            out["detail"][name] = d
            out["values"][name] = {"value": v, "status": "computed", "source": why}
        except Exception as e:  # fetch failed -> fallback prior, flagged
            out["values"][name] = {"value": fb[fallback_key], "status": PLACEHOLDER,
                                   "source": f"{SOURCE} fallback_priors.{fallback_key}", "error": repr(e)[:200]}

    lg = {}
    try:
        lg = loss_given_exploit(offline)
    except Exception:
        pass
    tvl_before = {(x["name"], x["date"]): x["tvl_before"] for x in lg.get("sample", [])}
    put("exploit", lambda: exploit_rates(offline, tvl_before), lambda d: d if d["buckets"] else None,
        "exploit_annual_bluechip", "DefiLlama hacks + protocols")
    put("loss_given_exploit", lambda: out["detail"]["exploit"] | {"top_hacks_tvl_sample": lg},
        lambda d: d["lgd_material_median"], "loss_given_exploit",
        "median net loss / TVL over the same material exploits as the frequency")
    dr = {}
    put("depeg", lambda: dr.setdefault("d", depeg_rates(offline)), lambda d: d if d["classes"] else None,
        "depeg_3pct_24h_annual_synthetic", "DefiLlama coins daily prices")
    if out["values"]["depeg"]["status"] == "computed":
        usde = dr["d"]["classes"]["synthetic"]["coins"].get("ethena-usde", {})
        if "p_annual_over_24h<0.97" in usde:
            out["values"]["depeg_3pct_24h_annual_usde"] = {
                "value": usde["p_annual_over_24h<0.97"], "status": "computed",
                "source": f"USDe own daily history ({usde['years']}y, daily trough {usde['min_price']:.3f}); "
                          "class rate (incl. UST, sUSD) available as stress"}
        for cls, fbk in (("fiat_backed", "depeg_3pct_24h_annual_fiat_backed"), ("synthetic", "depeg_3pct_24h_annual_synthetic"),
                         ("crypto_backed", None)):
            v = dr["d"]["classes"].get(cls, {}).get("thresholds", {}).get("0.97", {}).get("p_annual_over_24h")
            if v is not None:
                out["values"][f"depeg_3pct_24h_annual_{cls}"] = {"value": v, "status": "computed",
                                                                  "source": "DefiLlama coins daily prices"}
            elif fbk:
                out["values"][f"depeg_3pct_24h_annual_{cls}"] = {"value": fb[fbk], "status": PLACEHOLDER,
                                                                  "source": f"{SOURCE} fallback_priors.{fbk}"}
    else:
        for cls, fbk in (("fiat_backed", "depeg_3pct_24h_annual_fiat_backed"), ("synthetic", "depeg_3pct_24h_annual_synthetic")):
            out["values"][f"depeg_3pct_24h_annual_{cls}"] = {"value": fb[fbk], "status": PLACEHOLDER,
                                                              "source": f"{SOURCE} fallback_priors.{fbk}"}
    if feeds:
        put("oracle_stale", lambda: oracle_failure_rates(feeds, offline),   # pooled over feed-years
            lambda d: _rate(sum(x.get("stale_events", 0) for x in d.values()),
                            sum(x.get("years", 0) for x in d.values())) if d else None,
            "exploit_annual_bluechip", "Etherscan AnswerUpdated history")
        if out["values"]["oracle_stale"]["status"] == PLACEHOLDER:
            out["values"]["oracle_stale"]["source"] += " (no oracle prior in ASSUMED_ANSWERS: reused exploit prior)"
    return out


def load(offline: bool = True) -> dict:
    """UI / Monte Carlo entry point: cached file, else compute (falls back per value)."""
    if OUT.exists():
        return json.loads(OUT.read_text())
    return compute(offline=offline)


if __name__ == "__main__":
    from core import addresses as A
    from core.fork import Fork
    off = "--offline" in sys.argv
    fk = Fork(offline=off)
    if fk.offline:
        fk.fork_block = A.FORK_BLOCK
    # AnswerUpdated is emitted by the aggregator behind each EAC proxy: resolve it on-chain
    feeds = {lbl: fk.call1(px, "aggregator()", "address") for lbl, px in
             (("USDe/USD", A.HERO1["usde_usd_feed"]), ("USDC/USD", A.CHAINLINK_USDC_USD))}
    res = compute(off, feeds={k: v for k, v in feeds.items() if v})
    OUT.write_text(json.dumps(res, indent=1, default=str))
    for k, v in res["values"].items():
        val = v["value"] if not isinstance(v["value"], dict) else f"{len(v['value'].get('buckets') or v['value'].get('classes'))} groups (see detail)"
        print(f"  {k:36s} {v['status']:18s} {val}")
    print(f"→ {OUT}")
