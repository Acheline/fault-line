"""Hero #1 (light): PT-sUSDe-26NOV2026 held outright (P1) + posted on Morpho, borrowing USDC (P2 loop), on the same
engine as hero #2. Every loss below is measured on the fork; probabilities are computed base rates.

  usde_depeg     USDe -2/-5/-10/-25%. The Morpho oracle is a MetaOracle whose primary is a hardcoded linear-discount
                 schedule: the depeg does not move it. We pin the BACKUP oracle at the depegged price, challenge,
                 advance 16 h (challengeTimelockDuration, read on-chain) and accept: the oracle's own logic switches.
                 Then our loop's liquidation is attempted. P1 loss = mark-to-market on the PT.
  oracle_shock   the Morpho oracle price itself -2/-5/-8/-15% (technical failure): liquidation attempted on our loop.
  pendle_liq     the largest LPs (impersonated) burn 50% / 80% of the Pendle pool's LP supply; the PT -> USDC exit is
                 re-executed at 0.25/0.5/1/2x position size: the extra exit cost is the loss if you must exit.
Exit curve: PT -> USDC through the Pendle router at 0.25/0.5/1/2x the position size, executed on the fork.

    python -m risk.scenarios_hero1 [--offline]   -> data/shocks/hero1.json
"""
from __future__ import annotations

import json
import math
import sys
import time
from collections import Counter

import requests
from eth_abi import encode
from eth_utils import keccak

from core import addresses as A
from core.config import cfg
from core.etherscan import get_logs
from core.fork import ROOT, DiskCache, Fork, selector
from discovery.hero1 import MP_TYPES, market_params, position_slot
from discovery.hero2 import execute_exit, pendle_route
from risk import base_rates as BR
from risk.engine import Driver, Scenario, Surface

H = A.HERO1
OUT = ROOT / "data" / "shocks" / "hero1.json"
API = DiskCache("api")
ME = "0xfa0171fa0171fa0171fa0171fa0171fa0171fa02"        # our simulated P2 account on the fork
LIQ = "0xfa0171fa0171fa0171fa0171fa0171fa0171fa03"
WAD = 10**18
MULTS = [0.25, 0.5, 1.0, 2.0]
USDE_GRID = [0.02, 0.05, 0.10, 0.25]
ORACLE_GRID = [0.02, 0.05, 0.08, 0.15]
LIQ_GRID = [0.50, 0.80]


def sizes() -> dict:
    """P1 / P2 equity from the assumed book; loop math from ASSUMED_ANSWERS §1."""
    import yaml
    b = yaml.safe_load((ROOT / "books" / "belem_assumed_book.yaml").read_text())
    pos = {p["id"]: p for p in b["positions"]}
    lm = next((v["loop_math"] for v in pos["P2"]["verification"] if v.get("loop_math")), None)
    return {"p1_usd": pos["P1"]["size_usd"], "p2_equity_usd": pos["P2"]["size_usd"], "loop": lm}


# ------------------------------------------------------------------------------------------ fork helpers
def pt_price_usd(fork: Fork) -> float:
    return (fork.call1(H["morpho_oracle"], "price()", "uint256") or 0) / 1e36 * 1e18 / 1e6


def exit_two_legs(fork: Fork, amt: int, offline: bool, amm_only: bool = False) -> dict:
    """PT -> sUSDe through the Pendle AMM (router, aggregator off: the SY's own token out), then the sUSDe received -> USDC through
    KyberSwap without Uniswap v4 (its builder-set price limits trip on fork state). Both legs executed on the fork;
    the PT is real collateral moved out of Morpho Blue (impersonated)."""
    from discovery.hero2 import HARNESS, NO_V4
    from discovery.pockets import kyber_exit
    rt = pendle_route(H["pt"], amt, offline, fork.fork_block, token_out=H["susde"], aggregator=False,
                      limit_orders=not amm_only)
    if not rt:
        return {"usde_out": None, "usdc_out": None}
    with fork.snapshot():
        try:
            fork.send(A.MORPHO_BLUE, H["pt"], selector("transfer(address,uint256)") + encode(["address", "uint256"], [HARNESS, amt]))
            fork.send(HARNESS, H["pt"], selector("approve(address,uint256)") + encode(["address", "uint256"], [rt["to"], 2**256 - 1]))
            fork.send(HARNESS, rt["to"], rt["data"], gas=12_000_000)
            susde = fork.call1(H["susde"], "balanceOf(address)", "uint256", ["address"], [HARNESS]) or 0
            usde = fork.call1(H["susde"], "convertToAssets(uint256)", "uint256", ["uint256"], [susde]) or 0 if susde else 0
        except RuntimeError:
            return {"usde_out": None, "usdc_out": None, "quoted_susde": rt["amount_out"] / 1e18}
        q = kyber_exit(H["susde"], susde, offline, fork.fork_block, exclude=NO_V4) if susde else None
        usdc = None
        if q:
            try:
                fork.send(HARNESS, H["susde"], selector("approve(address,uint256)") + encode(["address", "uint256"], [q["to"], 2**256 - 1]))
                u0 = fork.call1(A.USDC, "balanceOf(address)", "uint256", ["address"], [HARNESS]) or 0
                fork.send(HARNESS, q["to"], q["data"], gas=12_000_000)
                usdc = ((fork.call1(A.USDC, "balanceOf(address)", "uint256", ["address"], [HARNESS]) or 0) - u0) / 1e6
            except RuntimeError:
                usdc = None
    return {"usde_out": usde / 1e18, "susde_out": susde / 1e18, "usdc_out": usdc, "quoted_susde": rt["amount_out"] / 1e18}


def exit_curve(fork: Fork, usd: float, offline: bool, mults=MULTS, amm_only: bool = False) -> list[dict]:
    px = pt_price_usd(fork)
    out = []
    for k in mults:
        amt = int(usd * k / px * 1e18)
        r = exit_two_legs(fork, amt, offline, amm_only)
        ref = amt / 1e18 * px
        got = r["usdc_out"]
        out.append({"x": k, "pt": amt / 1e18, "oracle_value_usd": ref, **r,
                    "amm_cost": 1 - r["usde_out"] / ref if r["usde_out"] else None,     # Pendle leg, sUSDe at its USDe rate
                    "cost": 1 - got / ref if got else None, "executed": got is not None})
    return out


def open_loop(fork: Fork, equity_usd: float, target_ltv: float) -> dict:
    """Our P2 on the fork: PT collateral (moved out of Morpho, impersonated) and a USDC borrow at the target LTV."""
    px = pt_price_usd(fork)
    lev = 1 / (1 - target_ltv)
    coll = int(equity_usd * lev / px * 1e18)
    debt = int(equity_usd * (lev - 1) * 1e6)
    mp = market_params()
    fork.send(A.MORPHO_BLUE, H["pt"], selector("transfer(address,uint256)") + encode(["address", "uint256"], [ME, coll]))
    fork.send(ME, H["pt"], selector("approve(address,uint256)") + encode(["address", "uint256"], [A.MORPHO_BLUE, 2**256 - 1]))
    fork.send(ME, A.MORPHO_BLUE, selector(f"supplyCollateral({MP_TYPES[0]},uint256,address,bytes)") +
              encode(MP_TYPES + ["uint256", "address", "bytes"], [mp, coll, ME, b""]))
    fork.send(ME, A.MORPHO_BLUE, selector(f"borrow({MP_TYPES[0]},uint256,uint256,address,address)") +
              encode(MP_TYPES + ["uint256", "uint256", "address", "address"], [mp, debt, 0, ME, ME]))
    return {"collateral_pt": coll, "debt_usdc": debt, "pt_price": px, "leverage": lev}


def my_position(fork: Fork) -> tuple[int, int]:
    mid = bytes.fromhex(H["morpho_market_id"][2:])
    p = fork.call(A.MORPHO_BLUE, "position(bytes32,address)", ["bytes32", "address"], [mid, ME], ["uint256", "uint128", "uint128"])
    mk = fork.call(A.MORPHO_BLUE, "market(bytes32)", ["bytes32"], [mid], ["uint128"] * 6)
    debt = -(-p[1] * (mk[2] + 1) // (mk[3] + 10**6)) if p else 0
    return (p[2] if p else 0), debt


def try_liquidate_me(fork: Fork) -> dict:
    coll, debt = my_position(fork)
    price = fork.call1(H["morpho_oracle"], "price()", "uint256")
    hf = coll * price / 1e36 * H["lltv"] / WAD / debt if debt else None
    out = {"hf": hf, "liquidated": False, "seized_pt": 0.0, "repaid_usdc": 0.0}
    if hf is None or hf >= 1:
        return out
    fork.fund_erc20(A.USDC, LIQ, 10**8 * 10**6)
    fork.send(LIQ, A.USDC, selector("approve(address,uint256)") + encode(["address", "uint256"], [A.MORPHO_BLUE, 2**256 - 1]))
    mid = bytes.fromhex(H["morpho_market_id"][2:])
    p = fork.call(A.MORPHO_BLUE, "position(bytes32,address)", ["bytes32", "address"], [mid, ME], ["uint256", "uint128", "uint128"])
    data = selector(f"liquidate({MP_TYPES[0]},address,uint256,uint256,bytes)") + encode(
        MP_TYPES + ["address", "uint256", "uint256", "bytes"], [market_params(), ME, 0, p[1], b""])
    try:
        fork.send(LIQ, A.MORPHO_BLUE, data)
        c1, d1 = my_position(fork)
        out.update(liquidated=True, seized_pt=(coll - c1) / 1e18, repaid_usdc=(debt - d1) / 1e6)
    except RuntimeError as e:      # full repay can exceed collateral: seize everything instead
        try:
            fork.send(LIQ, A.MORPHO_BLUE, selector(f"liquidate({MP_TYPES[0]},address,uint256,uint256,bytes)") + encode(
                MP_TYPES + ["address", "uint256", "uint256", "bytes"], [market_params(), ME, coll, 0, b""]))
            c1, d1 = my_position(fork)
            out.update(liquidated=True, seized_pt=(coll - c1) / 1e18, repaid_usdc=(debt - d1) / 1e6)
        except RuntimeError as e2:
            out["error"] = str(e2)[:80]
    return out


def switch_to_backup(fork: Fork, backup_price: int) -> dict:
    """Pin the backup oracle, then let the MetaOracle's own challenge -> timelock -> accept logic switch to it."""
    O = H["morpho_oracle"]
    bo = fork.call1(O, "backupOracle()", "address")
    tl = fork.call1(O, "challengeTimelockDuration()", "uint256") or 0
    fork.pin_price(bo, backup_price)
    steps = {}
    for fn in ("challenge()",):
        try:
            fork.send(LIQ, O, selector(fn))
            steps[fn] = "ok"
        except RuntimeError as e:
            steps[fn] = f"revert: {str(e)[:60]}"
    if not fork.offline:
        fork.rpc("evm_increaseTime", [tl + 1])
        fork.rpc("evm_mine", [])
    fork.mark_setup(f"warp{tl + 1}")
    fork.pin_price(bo, backup_price)            # re-pin after the warp (same code; keeps the setup id explicit)
    try:
        fork.send(LIQ, O, selector("acceptChallenge()"))
        steps["acceptChallenge()"] = "ok"
    except RuntimeError as e:
        steps["acceptChallenge()"] = f"revert: {str(e)[:60]}"
    return {"timelock_s": tl, "steps": steps, "is_backup": fork.call1(O, "isBackup()", "bool"),
            "price_now": fork.call1(O, "price()", "uint256")}


# ------------------------------------------------------------------------------------------ scenarios
def usde_depeg(fork: Fork, d: float, sz: dict) -> dict:
    lp = sz["loop"]
    with fork.snapshot():
        pos = open_loop(fork, sz["p2_equity_usd"], lp["target_ltv"])
        frozen = try_liquidate_me(fork)                                # oracle unchanged (primary = schedule)
        bo = fork.call1(H["morpho_oracle"], "backupOracle()", "address")
        b0 = fork.call1(bo, "price()", "uint256")
        sw = switch_to_backup(fork, int(b0 * (1 - d)))
        after = try_liquidate_me(fork)
    px = pos["pt_price"]
    coll_usd = pos["collateral_pt"] / 1e18 * px
    p1_loss = sz["p1_usd"] * d                                          # PT marked to USDe at (1 - d)
    # loop: equity falls by the collateral's move; if liquidated, the liquidator also takes the bonus on what it seized
    p2_mtm = coll_usd * d
    pen = 0.0
    if after["liquidated"]:
        pen = max(0.0, after["seized_pt"] * px * (1 - d) - after["repaid_usdc"])
    p2_loss = min(sz["p2_equity_usd"], p2_mtm + pen)
    tot = sz["p1_usd"] + sz["p2_equity_usd"]
    return {"severity": d, "frozen_phase": frozen, "switch": sw, "after_switch": after,
            "p1_loss_usd": p1_loss, "p2_loss_usd": p2_loss, "liquidation_penalty_usd": pen,
            "loss_per_usd": (p1_loss + p2_loss) / tot, "time_to_liquidation_s": sw["timelock_s"]}


def oracle_shock(fork: Fork, s: float, sz: dict) -> dict:
    with fork.snapshot():
        pos = open_loop(fork, sz["p2_equity_usd"], sz["loop"]["target_ltv"])
        p0 = fork.call1(H["morpho_oracle"], "price()", "uint256")
        fork.pin_price(H["morpho_oracle"], int(p0 * (1 - s)))
        r = try_liquidate_me(fork)
    px = pos["pt_price"]
    pen = max(0.0, r["seized_pt"] * px - r["repaid_usdc"]) if r["liquidated"] else 0.0   # true value unchanged
    tot = sz["p1_usd"] + sz["p2_equity_usd"]
    return {"severity": s, **r, "liquidation_penalty_usd": pen, "loss_per_usd": pen / tot}


def lp_holders(fork: Fork) -> list[tuple[str, int]]:
    M = H["pendle_market"]
    bal: Counter = Counter()
    for l in get_logs(M, "0x" + keccak(text="Transfer(address,address,uint256)").hex(), 0, fork.fork_block):
        v = int(l["data"], 16)
        bal["0x" + l["topics"][1][-40:]] -= v
        bal["0x" + l["topics"][2][-40:]] += v
    for k in ("0x" + "0" * 40, M.lower()):
        bal.pop(k, None)
    out = [(a, fork.call1(M, "balanceOf(address)", "uint256", ["address"], [a]) or 0) for a, _ in bal.most_common(60)]
    return sorted([x for x in out if x[1] > 0], key=lambda x: -x[1])


def pendle_liquidity(fork: Fork, frac: float, sz: dict, offline: bool) -> dict:
    M = H["pendle_market"]
    with fork.snapshot():
        ts = fork.call1(M, "totalSupply()", "uint256")
        target, burned, who = int(ts * frac), 0, []
        for a, b in lp_holders(fork):
            if burned >= target:
                break
            amt = min(b, target - burned)
            try:
                fork.send(a, M, selector("transfer(address,uint256)") + encode(["address", "uint256"], [M, amt]))
                fork.send(a, M, selector("burn(address,address,uint256)") + encode(["address", "address", "uint256"], [a, a, amt]))
                burned += amt
                who.append(a)
            except RuntimeError:
                continue
        curve = exit_curve(fork, sz["p1_usd"] + sz["p2_equity_usd"] / (1 - sz["loop"]["target_ltv"]), offline, amm_only=True)
    return {"severity": frac, "lp_burned_share": burned / ts if ts else 0, "lps_impersonated": len(who), "curve": curve,
            "note": "AMM only (Pendle limit orders excluded): the LP withdrawal acts on the AMM"}


# ------------------------------------------------------------------------------------------ base rates
def pendle_liquidity_drops(offline: bool, levels=(0.5, 0.8), skip_days_before_expiry: int = 14) -> dict:
    """Daily TVL drops >= 50% / 80% across active Pendle markets on Ethereum (Pendle API history), excluding the last
    14 days before expiry (liquidity leaves by design)."""
    def get(key, url):
        hit = API.get(key)
        if hit is not None or offline:
            return (hit or {}).get("data")
        r = requests.get(url, timeout=60).json()
        return API.put(key, {"fetched_at": int(time.time()), "data": r})["data"]
    act = get("pendle_active_1", "https://api-v2.pendle.finance/core/v1/1/markets/active") or {}
    days, drops = 0, {lv: 0 for lv in levels}
    for m in act.get("markets", []):
        h = get(f"pendle_hist_{m['address']}", f"https://api-v2.pendle.finance/core/v1/1/markets/{m['address']}/"
                                                 "historical-data?time_frame=day") or {}
        exp = time.mktime(time.strptime(m["expiry"][:10], "%Y-%m-%d"))
        ts, tvl = h.get("timestamp") or [], [float(x) for x in (h.get("tvl") or [])]
        for i in range(1, len(tvl)):
            if ts[i] > exp - skip_days_before_expiry * 86400 or tvl[i - 1] < 100_000:
                continue
            days += 1
            for lv in levels:
                if tvl[i] <= tvl[i - 1] * (1 - lv):
                    drops[lv] += 1
            if not offline:
                pass
    yrs = days / 365.25
    return {"market_days": days, "market_years": yrs, "drops": drops,
            "annual_rate": {str(lv): (drops[lv] + 0.5) / yrs if yrs else None for lv in levels},
            "n_markets": len(act.get("markets", []))}


def drivers(offline: bool) -> dict[str, Driver]:
    br = json.loads(BR.OUT.read_text())
    syn = br["values"]["depeg"]["value"]["classes"]["synthetic"]["coins"]["ethena-usde"]
    us = Driver("usde", "USDe depeg", (syn["episodes<0.99"] + 0.5) / syn["years"], [1 - t for t in syn["troughs"]],
                "market_disruption", "counterparty_defaults",
                f"USDe's own daily prices: {syn['episodes<0.99']} episodes < $0.99 in {syn['years']} years "
                f"(min {syn['min_price']:.3f})")
    st = br["values"]["oracle_stale"]
    orc = Driver("oracle", "Morpho oracle / feed failure", st["value"] if isinstance(st["value"], float) else 0.2,
                 ORACLE_GRID, "technical_failure", "liquidations",
                 "oracle staleness events per feed-year (base_rates oracle_stale); severity: the tested grid "
                 "(no data on mispricing size)", badge="severity_grid")
    pl = pendle_liquidity_drops(offline)
    r50 = pl["annual_rate"]["0.5"] or 0.0
    r80 = pl["annual_rate"]["0.8"] or 0.0
    liq = Driver("pendle_liq", "Pendle pool liquidity withdrawal", r50,
                 [0.8] * int(round(100 * r80 / r50)) + [0.5] * (100 - int(round(100 * r80 / r50))) if r50 else [0.5],
                 "market_disruption", "liquidations",
                 f"daily TVL drops across {pl['n_markets']} active Pendle markets: {pl['drops']} in "
                 f"{pl['market_years']:.1f} market-years (Jeffreys)")
    return {"usde": us, "oracle": orc, "pendle_liq": liq}, pl


# ------------------------------------------------------------------------------------------ run / build
def run(offline: bool = False) -> dict:
    fork = Fork(offline=offline)
    if fork.offline:
        fork.fork_block = A.FORK_BLOCK
    sz = sizes()
    pos_usd = sz["p1_usd"] + sz["p2_equity_usd"] / (1 - sz["loop"]["target_ltv"])   # PT to sell for a full unwind
    base_curve = exit_curve(fork, pos_usd, offline)                       # realistic route (limit orders + AMM)
    base_amm = exit_curve(fork, pos_usd, offline, amm_only=True)          # reference for the LP shock
    usde = [usde_depeg(fork, d, sz) for d in USDE_GRID]
    orc = [oracle_shock(fork, s, sz) for s in ORACLE_GRID]
    liq = [pendle_liquidity(fork, f, sz, offline) for f in LIQ_GRID]
    for r in liq:                        # loss if you must exit during the shock: extra cost vs normal, at 1x size
        b = next(c for c in base_amm if c["x"] == 1.0)
        c = next(c for c in r["curve"] if c["x"] == 1.0)
        # the LP shock acts on the Pendle AMM leg: compare that leg (executed) at 1x size
        r["extra_exit_cost"] = (c["amm_cost"] - b["amm_cost"]) if c["amm_cost"] is not None and b["amm_cost"] is not None else None
        r["loss_per_usd"] = max(0.0, r["extra_exit_cost"] or 0.0) * pos_usd / (sz["p1_usd"] + sz["p2_equity_usd"])
    D, pl = drivers(offline)
    mid = bytes.fromhex(H["morpho_market_id"][2:])
    mk = fork.call(A.MORPHO_BLUE, "market(bytes32)", ["bytes32"], [mid], ["uint128"] * 6)
    rate = fork.call1(H["morpho_irm"], f"borrowRateView({MP_TYPES[0]},(uint128,uint128,uint128,uint128,uint128,uint128))",
                      "uint256", MP_TYPES + ["(uint128,uint128,uint128,uint128,uint128,uint128)"], [market_params(), tuple(mk)])
    pend = requests.get(f"https://api-v2.pendle.finance/core/v2/1/markets/{H['pendle_market']}/data", timeout=60).json() \
        if not offline else {}
    out = {"fork_block": fork.fork_block, "sizes": sz, "unwind_pt_usd": pos_usd, "exit_curve": base_curve,
           "exit_curve_amm_only": base_amm,
           "usde_depeg": usde, "oracle_shock": orc, "pendle_liquidity": liq, "liquidity_base_rates": pl,
           "drivers": {k: vars(d) for k, d in D.items()},
           "borrow_apr": rate * 31_536_000 / WAD if rate is not None else None,
           "pt_implied_apy": pend.get("impliedApy"), "generated_at": int(time.time())}
    prev = json.loads(OUT.read_text()) if OUT.exists() else {}
    if offline and prev.get("pt_implied_apy") is not None:
        out["pt_implied_apy"] = prev["pt_implied_apy"]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=1, default=str))
    return out


def load() -> dict:
    return json.loads(OUT.read_text())


def build(data: dict | None = None) -> tuple[dict[str, Driver], list[Scenario]]:
    data = data or load()
    D = {k: Driver(**v) for k, v in data["drivers"].items()}
    tl = data["usde_depeg"][0]["time_to_liquidation_s"] if data["usde_depeg"] else 0
    sc = [Scenario("usde_depeg", "USDe depeg (oracle schedule frozen, switch after challenge)", "usde",
                   Surface([(r["severity"], r["loss_per_usd"]) for r in data["usde_depeg"]] + [(1.0, 1.0)]), 0,
                   "high", "USDe / Ethena",
                   notes=f"mark-to-market immediate; liquidation only after the {tl / 3600:.0f} h challenge timelock"),
          Scenario("oracle_shock", "Morpho oracle mispricing (technical)", "oracle",
                   Surface([(r["severity"], r["loss_per_usd"]) for r in data["oracle_shock"]]), 0, "medium",
                   "Morpho oracle"),
          Scenario("pendle_liq", "Pendle LP withdrawal (exit cost if forced to exit)", "pendle_liq",
                   Surface([(r["severity"], r["loss_per_usd"]) for r in data["pendle_liquidity"]]), 0, "medium",
                   "Pendle AMM")]
    return D, sc


if __name__ == "__main__":
    o = run(offline="--offline" in sys.argv)
    print("amm-only:", [(c["x"], c["executed"], round(c["amm_cost"] or 0, 5)) for c in o["exit_curve_amm_only"]])
    print("exit curve:", [(c["x"], c["executed"], round(c["amm_cost"] or 0, 5), round(c["cost"] or 0, 5)) for c in o["exit_curve"]])
    for r in o["usde_depeg"]:
        print(f"  USDe -{r['severity']:.0%}: frozen hf {r['frozen_phase']['hf']:.3f} | switch {r['switch']['steps']} "
              f"backup={r['switch']['is_backup']} | after hf {r['after_switch']['hf']:.3f} liquidated "
              f"{r['after_switch']['liquidated']} | loss/$ {r['loss_per_usd']:.4f}")
    for r in o["oracle_shock"]:
        print(f"  oracle -{r['severity']:.0%}: hf {r['hf']:.3f} liquidated {r['liquidated']} loss/$ {r['loss_per_usd']:.4f}")
    for r in o["pendle_liquidity"]:
        print(f"  LP -{r['severity']:.0%}: burned {r['lp_burned_share']:.1%} by {r['lps_impersonated']} LPs | curve "
              f"{[(c['x'], c['executed'], round(c['amm_cost'] or 0, 4)) for c in r['curve']]} | extra {r['extra_exit_cost']} | loss/$ {r['loss_per_usd']:.4f}")
    print("drivers:", {k: round(v["annual_rate"], 3) for k, v in o["drivers"].items()}, "| liquidity rates", o["liquidity_base_rates"])
    print("borrow APR", o["borrow_apr"], "PT implied APY", o["pt_implied_apy"])
