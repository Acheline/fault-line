"""How fast does a Morpho market get liquidity back after it hits 100% utilization? Measured from history.

For each market: hourly utilization, supply and borrow (Morpho GraphQL historicalState, 180 days). An episode starts
the first hour utilization >= 0.99. We record the hours until it falls back below 0.97 / 0.95 / 0.90 (the adaptive
IRM's target) and the free liquidity (supply - borrow) regained per hour over the following 24 h, as a fraction of
the market's supply at the start. This is what the IRM rate spike, borrower repayments and new lenders produced in
practice, so the exit race uses it instead of an assumed repayment speed.

    python -m risk.liquidity_recovery [--offline]   -> data/liquidity_recovery.json
"""
from __future__ import annotations

import json
import statistics
import sys
import time

import requests

from core.fork import ROOT, DiskCache

API = DiskCache("api")
OUT = ROOT / "data" / "liquidity_recovery.json"
DAYS = 180
LEVELS = (0.97, 0.95, 0.90)
Q = '''{ marketById(marketId:"%s", chainId:1){ historicalState{
  utilization(options:{startTimestamp:%d, endTimestamp:%d, interval:HOUR}){ x y }
  supplyAssetsUsd(options:{startTimestamp:%d, endTimestamp:%d, interval:HOUR}){ x y }
  borrowAssetsUsd(options:{startTimestamp:%d, endTimestamp:%d, interval:HOUR}){ x y } } } }'''


def history(market_id: str, offline: bool, end: int | None = None) -> dict | None:
    key = f"morpho_hist_{market_id[:18]}_{DAYS}d"
    hit = API.get(key)
    if hit is not None or offline:
        return (hit or {}).get("data")
    end = end or int(time.time())
    st = end - DAYS * 86400
    r = requests.post("https://api.morpho.org/graphql", json={"query": Q % (market_id, st, end, st, end, st, end)},
                      timeout=120).json()
    h = r["data"]["marketById"]["historicalState"]
    return API.put(key, {"fetched_at": end, "data": h})["data"]


def episodes(h: dict) -> list[dict]:
    sup = {p["x"]: p["y"] for p in h["supplyAssetsUsd"] if p["y"] is not None}
    bor = {p["x"]: p["y"] for p in h["borrowAssetsUsd"] if p["y"] is not None}
    u = sorted((p["x"], p["y"]) for p in h["utilization"] if p["y"] is not None)   # API returns newest first
    out, i = [], 0
    while i < len(u):
        t0, y = u[i]
        if y < 0.99:
            i += 1
            continue
        ep = {"start": t0, "supply_usd": sup.get(t0)}
        for lv in LEVELS:
            j = next((k for k in range(i, len(u)) if u[k][1] < lv), None)
            ep[f"hours_to_below_{lv}"] = (u[j][0] - t0) / 3600 if j is not None else None
        t24 = t0 + 24 * 3600
        f0 = (sup.get(t0) or 0) - (bor.get(t0) or 0)
        f24 = (sup.get(t24) or 0) - (bor.get(t24) or 0) if t24 in sup else None
        if f24 is not None and sup.get(t0):
            ep["free_regained_24h_share_of_supply"] = (f24 - f0) / sup[t0]
        out.append(ep)
        j = next((k for k in range(i, len(u)) if u[k][1] < LEVELS[-1]), len(u))
        i = max(j, i + 1)            # next episode only after the market got back below target
    return out


def compute(markets: dict[str, str], offline: bool = False) -> dict:
    res, pooled = {}, []
    for label, mid in markets.items():
        h = history(mid, offline)
        if not h:
            res[label] = {"available": False}
            continue
        eps = episodes(h)
        pooled += eps
        res[label] = {"available": True, "market_id": mid, "n_episodes": len(eps), "episodes": eps,
                      "hours_at_or_above_0.99": sum((p["y"] or 0) >= 0.99 for p in h["utilization"])}

    def med(key):
        v = [e[key] for e in pooled if e.get(key) is not None]
        return {"median": statistics.median(v) if v else None, "p90": sorted(v)[int(0.9 * (len(v) - 1))] if v else None,
                "n": len(v), "n_never_recovered_in_window": sum(e.get(key) is None for e in pooled)}
    summary = {f"hours_to_below_{lv}": med(f"hours_to_below_{lv}") for lv in LEVELS}
    summary["free_regained_24h_share_of_supply"] = med("free_regained_24h_share_of_supply")
    return {"source": "Morpho GraphQL historicalState, hourly, last %d days" % DAYS, "generated_at": int(time.time()),
            "markets": res, "pooled": summary, "n_episodes": len(pooled)}


def load() -> dict:
    return json.loads(OUT.read_text())


if __name__ == "__main__":
    g = json.loads((ROOT / "data" / "graphs" / "hero2.json").read_text())
    mk = {m["collateral_symbol"]: m["market_id"] for m in g["meta"]["q1"]["markets"]}
    out = compute(mk, offline="--offline" in sys.argv)
    OUT.write_text(json.dumps(out, indent=1))
    for k, v in out["markets"].items():
        if v.get("available"):
            print(f"  {k:22s} episodes {v['n_episodes']:3d}  "
                  f"{[round(e.get('hours_to_below_0.9') or -1, 1) for e in v['episodes']][:8]}")
    print("pooled:", json.dumps(out["pooled"]))
