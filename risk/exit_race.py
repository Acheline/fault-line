"""Module 3, lender side: the race to exit a curated vault (generic for Morpho Vault V2 / MetaMorpho depositors).

t = 0 is MEASURED on the fork (discovery.hero2.run_simulation): depositors exit in rank order through the liquidity
market and forceDeallocate, each draining what the next one can get. After t = 0, liquidity comes back as it did in
practice: per market, the free liquidity regained in the 24 h after past 100%-utilization episodes (risk.liquidity_
recovery, Morpho history), as a share of market supply. The vault only gets its pro-rata share of what comes back
(other lenders in the same market are running too): assumption, shown and in the tornado.

Queue: `rank` = your place in the line. The depositors ahead of you are the real largest holders (Transfer logs),
largest first. Your recovered amount at time t = min(your size, liquidity reachable by t - claims ahead of you),
minus the force-deallocate penalty on the part that had to be force-deallocated.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from core import addresses as A
from core.fork import ROOT, Fork, selector
from eth_abi import encode

from risk.engine import TIME_GRID_S

AAVE_POOL = "0x87870Bca3F3fD6335C3F4ce8392D69350B4fA4E2"
RAY = 10**27


@dataclass
class MarketLiquidity:
    label: str
    vault_alloc: float          # vault supply in the market ($)
    free_now: float             # market free liquidity now ($)
    supply: float               # market total supply ($)
    vault_share: float          # vault supply / market supply
    refill_24h_share: float     # free liquidity regained in 24 h after a 100% episode, share of supply (measured)
    instant: bool               # the vault's liquidity market (no penalty)


def markets_from(meta: dict, lr: dict, vault_claim_share: float | None = None) -> list[MarketLiquidity]:
    pooled = lr["pooled"]["free_regained_24h_share_of_supply"]["median"] or 0.0
    out = []
    for m in meta["q1"]["markets"]:
        rec = lr["markets"].get(m["collateral_symbol"], {})
        eps = [e["free_regained_24h_share_of_supply"] for e in rec.get("episodes", [])
               if e.get("free_regained_24h_share_of_supply") is not None]
        r = sorted(eps)[len(eps) // 2] if len(eps) >= 2 else pooled
        out.append(MarketLiquidity(m["collateral_symbol"], m["allocation_usd"], m["free_liquidity_usd"],
                                   m["market_supply_usd"],
                                   m["vault_share_of_market"] if vault_claim_share is None else vault_claim_share,
                                   max(0.0, r), m["is_liquidity_market"]))
    return out


def reachable(mk: list[MarketLiquidity], t_s: float, idle: float = 0.0, refill_scale: float = 1.0) -> tuple[float, float]:
    """(instant $, force-deallocate $) the vault can pay out by time t, capped by its allocation in each market."""
    inst, forced = idle, 0.0
    for m in mk:
        refill = m.supply * m.refill_24h_share * refill_scale * (t_s / 86400) * m.vault_share
        v = min(m.vault_alloc, m.free_now + refill)
        if m.instant:
            inst += v
        else:
            forced += v
    return inst, forced


def recovered(size: float, ahead: float, mk: list[MarketLiquidity], t_s: float, penalty: float,
              idle: float = 0.0, refill_scale: float = 1.0) -> dict:
    """What you get by t when `ahead` $ of claims are served before you. Instant liquidity is used first."""
    inst, forced = reachable(mk, t_s, idle, refill_scale)
    inst_left = max(0.0, inst - ahead)
    forced_left = max(0.0, forced - max(0.0, ahead - inst))
    from_inst = min(size, inst_left)
    from_forced = min(size - from_inst, forced_left)
    got = from_inst + from_forced * (1 - penalty)
    return {"t_s": t_s, "recovered_usd": got, "recovered_pct": got / size if size else 0.0,
            "penalty_usd": from_forced * penalty, "from_instant": from_inst, "from_forced": from_forced,
            "locked_usd": size - from_inst - from_forced}


def time_to_full_exit(size: float, ahead: float, mk: list[MarketLiquidity], penalty: float, idle: float = 0.0,
                      refill_scale: float = 1.0, max_days: float = 365) -> float | None:
    """Seconds until your whole position is reachable (bisection on the refill model). None if never within max_days."""
    def ok(t):
        return recovered(size, ahead, mk, t, penalty, idle, refill_scale)["locked_usd"] <= 1.0
    if ok(0):
        return 0.0
    hi = max_days * 86400
    if not ok(hi):
        return None
    lo = 0.0
    for _ in range(50):
        mid = (lo + hi) / 2
        lo, hi = (lo, mid) if ok(mid) else (mid, hi)
    return hi


def race_table(size: float, rank: int, depositors: list[dict], mk: list[MarketLiquidity], penalty: float,
               idle: float = 0.0, refill_scale: float = 1.0) -> dict:
    ahead = sum(d["assets_usd"] for d in depositors[:max(0, rank - 1)])
    rows = {k: recovered(size, ahead, mk, t, penalty, idle, refill_scale) for k, t in TIME_GRID_S.items()}
    return {"rank": rank, "ahead_usd": ahead, "by_time": rows,
            "time_to_full_exit_s": time_to_full_exit(size, ahead, mk, penalty, idle, refill_scale)}


def rank_curve(depositors: list[dict], mk: list[MarketLiquidity], penalty: float, idle: float = 0.0) -> list[dict]:
    """Every real top depositor, in order: % recovered at each time point and time to full exit."""
    out, ahead = [], 0.0
    for i, d in enumerate(depositors, 1):
        s = d["assets_usd"]
        row = {"rank": i, "address": d["address"], "size_usd": s}
        for k, t in TIME_GRID_S.items():
            row[k] = recovered(s, ahead, mk, t, penalty, idle)["recovered_pct"]
        row["time_to_full_exit_s"] = time_to_full_exit(s, ahead, mk, penalty, idle)
        out.append(row)
        ahead += s
    return out


# ------------------------------------------------------------------------------- fork measurements
def governance_penalty_run(fork: Fork, meta: dict, penalty: float = 0.02) -> dict:
    """Curator (owner Safe) submits setForceDeallocatePenalty(adapter, 2%) and executes it in the same block (no
    timelock), then the measured depositor run is replayed. Time-to-impact 0."""
    from discovery import hero2
    r = meta["q1"]["roles"]
    V = hero2.V
    with fork.snapshot():
        for ad in r["adapters"]:
            inner = selector("setForceDeallocatePenalty(address,uint256)") + encode(["address", "uint256"], [ad, int(penalty * 1e18)])
            fork.send(r["curator"], V, selector("submit(bytes)") + encode(["bytes"], [inner]))
            fork.send(r["curator"], V, inner)
        got = {ad: (fork.call1(V, "forceDeallocatePenalty(address)", "uint256", ["address"], [ad]) or 0) / 1e18
               for ad in r["adapters"]}
        ms = []
        for m in meta["q1"]["markets"]:
            mid = bytes.fromhex(m["market_id"][2:])
            params = list(fork.call(A.MORPHO_BLUE, "idToMarketParams(bytes32)", ["bytes32"], [mid], ["address"] * 4 + ["uint256"]))
            ms.append(dict(m, params=params))
        run = hero2.run_simulation(fork, r, ms, meta["q3"]["top_depositors"])
    return {"penalty_set": got, "time_to_impact_s": 0, "run": run,
            "how": "curator Safe submit(setForceDeallocatePenalty) + execute in the same block, on the fork"}


def aave_usdc_apy(fork: Fork) -> float | None:
    raw = fork.call(AAVE_POOL, "getReserveData(address)", ["address"], [A.USDC])
    if not raw or len(raw) < 96:
        return None
    rate = int.from_bytes(raw[64:96], "big") / RAY      # word 2 = currentLiquidityRate (ray, APR)
    return (1 + rate / 31_536_000) ** 31_536_000 - 1


def load_inputs() -> tuple[dict, dict]:
    meta = json.loads((ROOT / "data" / "graphs" / "hero2.json").read_text())["meta"]
    lr = json.loads((ROOT / "data" / "liquidity_recovery.json").read_text())
    return meta, lr
