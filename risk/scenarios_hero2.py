"""Hero #2 scenarios: every loss surface measured on the fork, every probability a computed base rate.

  trusd_frozen   trUSD loses value; strUSD, PT-strUSD and etrUSD oracles stay at par (RedStone *_FUNDAMENTAL feeds:
                 trUSD_FUNDAMENTAL reads exactly 1.00000000), so nobody is liquidated: silent bad debt.
  reusd_market   PT-reUSD market price falls; its oracle (Ojo PT feed over a Pendle TWAP) follows after the TWAP;
                 liquidators sell through the Pendle router within the executed capacity.
  iusd_nav       siUSD exchange rate marked down by the issuer; oracle follows; capacity from executed Kyber routes.
  prime_nav      PRIME / wYLDS exchange rate marked down; oracle follows; capacity from executed routes.
  pendle_exploit both PT markets' collateral loses value with no exit (capacity 0).
  morpho_exploit Morpho Blue exploit: parametric, loss = loss-given-exploit share (not a fork run, confidence medium).
Comparison only (not in the Monte Carlo): trusd_tracking, the same trUSD move if the oracles tracked it.

    python -m risk.scenarios_hero2 [--offline]   -> data/shocks/hero2.json
"""
from __future__ import annotations

import json
import math
import statistics
import sys
import time

from core import addresses as A
from core.fork import ROOT, Fork
from discovery import hero2
from risk import base_rates as BR
from risk.engine import Driver, Scenario, Surface
from risk.fork_shocks import MarketLeg, market_shock

OUT = ROOT / "data" / "shocks" / "hero2.json"
GRID = [-0.02, -0.05, -0.10, -0.25, -0.50, -0.75, -0.95]
N_BORROWERS_SHOCK = 200
TRUSD_LEGS = ("strUSD", "PT-strUSD-26NOV2026", "etrUSD")


# ------------------------------------------------------------------------------------------------ drivers
def _class(br: dict, cls: str) -> dict:
    return br["values"]["depeg"]["value"]["classes"][cls]


def nav_drawdowns(ids: list[str], offline: bool, thr: float = 0.01) -> dict:
    """NAV-accruing RWA tokens: episodes where price falls > thr below its running max (DefiLlama daily prices)."""
    years, troughs = 0.0, []
    coins = {}
    for cid in ids:
        px = BR.price_history(cid, offline)
        if len(px) < 30:
            continue
        yrs = (px[-1][0] - px[0][0]) / BR.YEAR
        years += yrs
        peak, cur = 0.0, None
        n = 0
        for _, p in px:
            peak = max(peak, p)
            dd = 1 - p / peak if peak else 0
            if dd > thr:
                cur = max(cur or 0, dd)
            elif cur is not None:
                troughs.append(cur)
                n += 1
                cur = None
        if cur is not None:
            troughs.append(cur)
            n += 1
        coins[cid] = {"years": round(yrs, 2), "episodes": n}
    return {"coin_years": years, "episodes": len(troughs), "severities": troughs, "coins": coins,
            "annual_rate": (len(troughs) + 0.5) / years if years else None}


PRIME_NAV_AGG = "0x48f9a46ba852b5c22d4153d0534397b59abfdef5"   # PRIME / WYLDS Exchange Rate (OCR2 aggregator)


def nav_feed_history(agg: str = PRIME_NAV_AGG, thr: float = 0.01) -> dict:
    """Issuer NAV markdowns read from the on-chain feed itself (AnswerUpdated history via Etherscan)."""
    from core.etherscan import get_logs
    from discovery.oracle_quality import ANSWER_UPDATED
    ans = sorted((int(x["timeStamp"], 16), int(x["topics"][1], 16)) for x in get_logs(agg, ANSWER_UPDATED, 0, A.FORK_BLOCK))
    years = (ans[-1][0] - ans[0][0]) / BR.YEAR if len(ans) > 1 else 0.0
    peak, dec = 0, []
    for _, a in ans:
        if a < peak:
            dec.append(1 - a / peak)
        peak = max(peak, a)
    big = [d for d in dec if d > thr]
    return {"n_updates": len(ans), "years": years, "n_decreases": len(dec), "severities": dec,
            "annual_rate": (len(big) + 0.5) / years if years else 0.0, "n_over_threshold": len(big)}


def drivers(offline: bool) -> tuple[dict[str, Driver], dict]:
    br = json.loads(BR.OUT.read_text())
    ys = _class(br, "yield_synthetic")
    rate = ys["thresholds"]["0.99"]["p_annual"]
    sev = [1 - t for t in ys["episode_troughs"]]
    n_coins = sum(1 for v in ys["coins"].values() if "years" in v)
    src = (f"base_rates yield_synthetic class (rule-based: every non-fiat USD stablecoin launched since 2024 with peak "
           f"supply >= $25M, failures included): {n_coins} coins, {ys['coin_years']} coin-years, "
           f"{ys['thresholds']['0.99']['episodes']} episodes < $0.99; severity = 1 - episode trough")
    D = {k: Driver(k, lab, rate, sev, "market_disruption", "counterparty_defaults", src)
         for k, lab in (("trusd", "trUSD depeg"), ("reusd", "reUSD depeg"), ("iusd", "iUSD depeg"))}
    nav = nav_feed_history()
    D["prime"] = Driver("prime", "PRIME NAV markdown", nav["annual_rate"], nav["severities"] or [0.0],
                        "market_disruption", "counterparty_defaults",
                        f"on-chain PRIME / wYLDS NAV feed: {nav['n_updates']} updates over {nav['years'] * 365:.0f} days, "
                        f"{nav['n_decreases']} decreases (max {max(nav['severities'] or [0]):.2%}), none > 1%: rate = "
                        "Jeffreys bound (0+0.5)/years, severities = observed decreases",
                        badge="short_history")
    ex = br["detail"]["exploit"]
    protos = {p.get("slug"): p for p in BR.protocols(offline)}
    for k, slug, lab in (("morpho_exploit", "morpho-blue", "Morpho Blue exploit"), ("pendle_exploit", "pendle", "Pendle exploit")):
        p = protos.get(slug) or {}
        pa, bucket = BR.exploit_p(ex, p.get("category"), p.get("listedAt"), p.get("tvl"))
        lgd, lb = BR.lgd_for(ex, p.get("tvl"))
        D[k] = Driver(k, lab, pa, [lgd], "security_incident", "security_incidents",
                      f"DefiLlama hacks: bucket {bucket} -> {pa:.3%}/yr; loss-given-exploit {lgd:.1%} ({lb})")
    return D, {"prime_nav_feed": nav}


# ------------------------------------------------------------------------------------------------ fork runs
def _legs(fork: Fork, meta: dict, offline: bool) -> dict[str, dict]:
    out = {}
    q2 = {r["market"]: r for r in meta["q2"]}
    for m in meta["q1"]["markets"]:
        mid = bytes.fromhex(m["market_id"][2:])
        params = list(fork.call(A.MORPHO_BLUE, "idToMarketParams(bytes32)", ["bytes32"], [mid], ["address"] * 4 + ["uint256"]))
        mm = dict(m, params=params)
        bs = hero2.borrowers(fork, mm, offline, n=N_BORROWERS_SHOCK)
        ce = q2.get(m["collateral_symbol"], {}).get("collateral_exit", {})
        out[m["collateral_symbol"]] = {"m": mm, "bs": bs, "capacity": ce.get("liquidation_capacity_usd") or 0.0,
                                       "exit_confidence": ce.get("confidence", "medium"),
                                       "debt_read": sum(b["debt_usd"] for b in bs), "market_debt": m["market_borrow_usd"]}
    return out


def leg(L: dict, sym: str, move: float, oracle: str, capacity: float | None = None) -> MarketLeg:
    x = L[sym]
    om = 0.0 if oracle == "frozen" else move
    cap = x["capacity"] * (1 + move) if capacity is None else capacity
    return MarketLeg(sym, x["m"]["market_id"], x["m"]["params"], x["bs"], x["m"]["vault_share_of_market"],
                     move, om, cap)


SETS = {
    "trusd_frozen": lambda L, s: [leg(L, k, s, "frozen") for k in TRUSD_LEGS if k in L],
    "trusd_tracking": lambda L, s: [leg(L, k, s, "tracks") for k in TRUSD_LEGS if k in L],
    "reusd_market": lambda L, s: [leg(L, "PT-reUSD-10DEC2026", s, "tracks")],
    "iusd_nav": lambda L, s: [leg(L, "siUSD", s, "tracks")],
    "prime_nav": lambda L, s: [leg(L, "PRIME", s, "tracks")],
    "pendle_exploit": lambda L, s: [leg(L, k, s, "tracks", capacity=0.0) for k in ("PT-reUSD-10DEC2026", "PT-strUSD-26NOV2026") if k in L],
}


def twap_seconds(fork: Fork, g: dict) -> int | None:
    for n in g["nodes"].values():
        if (n["props"].get("contract_name") or "") == "PendleChainlinkOracle":
            v = fork.call1(n["id"], "twapDuration()", "uint32")
            if v:
                return int(v)
    return None


def run(offline: bool = False) -> dict:
    fork = Fork(offline=offline)
    if fork.offline:
        fork.fork_block = A.FORK_BLOCK
    g = json.loads((ROOT / "data" / "graphs" / "hero2.json").read_text())
    meta = g["meta"]
    L = _legs(fork, meta, offline)
    measured = {}
    for sid, mk in SETS.items():
        rows = []
        for s in GRID:
            r = market_shock(fork, hero2.V, mk(L, s))
            rows.append({"severity": -s, **{k: v for k, v in r.items() if k != "legs"}, "legs": r["legs"]})
            print(f"  {sid:15s} {s:+.0%}  loss/share {r['loss_per_share']:.4%}  recognized "
                  f"{(r['recognized_loss_per_share'] or 0):.4%}  liquidated {sum(x['n_liquidated'] for x in r['legs'])}")
        measured[sid] = rows
    D, extra = drivers(offline)
    twap = twap_seconds(fork, g)
    coverage = {k: v["debt_read"] / v["market_debt"] if v["market_debt"] else None for k, v in L.items()}
    out = {"fork_block": fork.fork_block, "vault": hero2.V, "grid": GRID, "measured": measured,
           "coverage_debt_read": coverage, "capacities_usd": {k: v["capacity"] for k, v in L.items()},
           "exit_confidence": {k: v["exit_confidence"] for k, v in L.items()},
           "pendle_twap_s": twap, "drivers": {k: vars(d) for k, d in D.items()}, "extra": extra,
           "generated_at": int(time.time())}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=1, default=str))
    return out


# ------------------------------------------------------------------------------------------------ to engine
SCENARIO_META = {
    # id: (label, driver, family, kpi, group, confidence)
    "trusd_frozen": ("trUSD depeg, oracles frozen at par (strUSD, PT-strUSD, etrUSD)", "trusd", "market_disruption",
                     "counterparty_defaults", "trUSD stack", "high"),
    "reusd_market": ("PT-reUSD market price shock (Pendle TWAP oracle)", "reusd", "market_disruption",
                     "liquidations", "PT-reUSD", "medium"),
    "iusd_nav": ("siUSD exchange-rate markdown", "iusd", "market_disruption", "counterparty_defaults", "siUSD", "high"),
    "prime_nav": ("PRIME NAV markdown", "prime", "market_disruption", "counterparty_defaults", "PRIME",
                  "low (165 days of NAV history, no markdown > 1%)"),
    "pendle_exploit": ("Pendle exploit: PT collateral, no exit", "pendle_exploit", "security_incident",
                       "security_incidents", "Pendle", "high"),
}


def load(path=OUT) -> dict:
    return json.loads(path.read_text())


def build(data: dict | None = None) -> tuple[dict[str, Driver], list[Scenario]]:
    data = data or load()
    D = {k: Driver(**v) for k, v in data["drivers"].items()}
    sc = []
    for sid, (lab, drv, fam, kpi, grp, conf) in SCENARIO_META.items():
        pts = [(r["severity"], r["loss_per_share"]) for r in data["measured"][sid]]
        tti = (data.get("pendle_twap_s") or 0) if sid == "reusd_market" else 0
        if sid == "trusd_frozen" and data["exit_confidence"].get("etrUSD") == "low":
            conf = "high (etrUSD leg: medium, linked to trUSD via shared owner)"
        sc.append(Scenario(sid, lab, drv, Surface(pts), tti, conf, grp))
        D[drv].family, D[drv].kpi = fam, kpi
    lgd = D["morpho_exploit"].severities[0]
    sc.append(Scenario("morpho_exploit", "Morpho Blue exploit (parametric)", "morpho_exploit",
                       Surface([(lgd, lgd)], measured_on="base rate"), 0, "medium", "Morpho Blue"))
    return D, sc


def refresh_drivers(offline: bool = True) -> dict:
    out = load()
    D, extra = drivers(offline)
    out.update(drivers={k: vars(d) for k, d in D.items()}, extra=extra)
    OUT.write_text(json.dumps(out, indent=1, default=str))
    return out


if __name__ == "__main__":
    out = refresh_drivers() if "--drivers-only" in sys.argv else run(offline="--offline" in sys.argv)
    for k, d in out["drivers"].items():
        print(f"  driver {k:15s} {d['annual_rate']:.3f}/yr  severities n={len(d['severities'])}  {d['source'][:90]}")
    print("coverage of market debt by borrowers read:", {k: round(v or 0, 3) for k, v in out["coverage_debt_read"].items()})
