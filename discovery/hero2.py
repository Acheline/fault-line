"""M1 / hero #2: a deposit in the RockawayX USDC Yield vault (Belem / RockawayX vaults, Morpho Vault V2, Ethereum).

Lender-side case: the depositor's risk is bad debt in the markets and being UNABLE to withdraw. Three questions,
each answered with numbers measured on the fork at a fixed block:

  Q1 WHERE DOES THE MONEY GO?  roles + timelocks read from the vault, every market of every adapter with
     allocation, caps, collateral, LLTV, oracle (price() traced), IRM, collateral root asset; exposure grouped.
  Q2 CAN BORROWERS REPAY?      real borrowers (Morpho API, re-read on the fork), health-factor distribution,
     collateral exit quote at liquidation size, and per market: oracle pinned at -5/-10/-25/-50%, every
     underwater borrower liquidated on the fork -> bad debt socialized, loss per vault share.
  Q3 CAN DEPOSITORS WITHDRAW?  withdrawable now (idle + liquidity market, + forceDeallocate of other markets at
     the vault's penalty), top depositors from share Transfer logs, and a run executed on the fork in rank order.

    python -m discovery.hero2            # live fork (results cached)
    python -m discovery.hero2 --offline  # replay from cache only
"""
from __future__ import annotations

import sys
import time
from collections import Counter, defaultdict

import requests
from eth_abi import decode, encode
from eth_utils import keccak

from core import addresses as A
from core.etherscan import get_logs
from core.fork import ROOT, DiskCache, Fork, selector
from core.schemas import CriticalPath, Edge, EdgeType, Node, NodeType, Provenance
from discovery import disclosures, oracle_quality, tvl, viz
from discovery.builder import GraphBuilder
from discovery.hero1 import position_slot
from discovery.pockets import kyber_exit
from discovery.report import critical_nodes, depth_report

H = A.HERO2
V = H["vault"].lower()
HARNESS = "0xfa0171fa0171fa0171fa0171fa0171fa0171fa01"   # our simulated liquidator
OUT = ROOT / "data" / "graphs"
API = DiskCache("api")
MP = "(address,address,address,address,uint256)"
WAD = 10**18
YEAR = 365 * 86400
LABEL = "Belem / RockawayX vaults"

# Vault V2 functions whose timelock decides how fast the curator can change what depositors are exposed to
TIMELOCKED = ["addAdapter(address)", "removeAdapter(address)", "increaseAbsoluteCap(bytes,uint256)",
              "increaseRelativeCap(bytes,uint256)", "setIsAllocator(address,bool)", "setForceDeallocatePenalty(address,uint256)",
              "setPerformanceFee(uint256)", "setManagementFee(uint256)", "setPerformanceFeeRecipient(address)",
              "setManagementFeeRecipient(address)", "setReceiveSharesGate(address)", "setSendSharesGate(address)",
              "setReceiveAssetsGate(address)", "setSendAssetsGate(address)", "setAdapterRegistry(address)",
              "increaseTimelock(bytes4,uint256)", "decreaseTimelock(bytes4,uint256)", "abdicate(bytes4)"]
SHOCKS = [-0.05, -0.10, -0.25, -0.50]     # oracle price moves applied on the fork (Module 2 grid)
N_BORROWERS = 30                          # largest borrowers per market fetched from the Morpho API
N_DEPOSITORS = 10                         # depositors simulated in the run


def _api(key, fn, offline):
    hit = API.get(key)
    if hit is not None or offline:
        return (hit or {}).get("data")
    return API.put(key, {"fetched_at": int(time.time()), "data": fn()})["data"]


def _morpho(q: str):
    return requests.post("https://api.morpho.org/graphql", json={"query": q}, timeout=60).json()["data"]


def _trace(fork: Fork, tx: dict, label: str) -> dict:
    tx = {**tx, "gas": hex(30_000_000)}
    return {"label": label, "call": fork.trace_call(tx, "callTracer", label),
            "pre": fork.trace_call(tx, "prestateTracer", label)}


def _topic_addr(t: str) -> str:
    return "0x" + t[-40:]


def lif(lltv: int) -> int:
    """Morpho Blue liquidation incentive factor: min(1.15, 1 / (1 - 0.3 * (1 - lltv)))."""
    return min(115 * WAD // 100, WAD * WAD // (WAD - 3 * (WAD - lltv) // 10))


# =========================================================================== Q1: where does the money go?
def roles(fork: Fork) -> dict:
    """Owner / curator / allocators / sentinels (event history, each re-checked on the fork) + timelocks."""
    c, blk = fork.call1, fork.fork_block
    owner, curator = c(V, "owner()", "address"), c(V, "curator()", "address")

    def members(event: str, getter: str) -> list[str]:
        seen = {_topic_addr(l["topics"][1]) for l in get_logs(V, "0x" + keccak(text=event).hex(), 0, blk)}
        return sorted(a for a in seen if c(V, getter, "bool", ["address"], [a]))

    tl = {}
    for sig in TIMELOCKED:
        sel = selector(sig)
        tl[sig.split("(")[0]] = {"timelock_s": c(V, "timelock(bytes4)", "uint256", ["bytes4"], [sel]),
                                 "abdicated": c(V, "abdicated(bytes4)", "bool", ["bytes4"], [sel])}
    adapters = [c(V, "adapters(uint256)", "address", ["uint256"], [i]).lower()
                for i in range(c(V, "adaptersLength()", "uint256") or 0)]
    return {
        "block": blk, "name": c(V, "name()", "string"), "symbol": c(V, "symbol()", "string"),
        "asset": c(V, "asset()", "address"), "total_assets_usd": (c(V, "totalAssets()", "uint256") or 0) / 1e6,
        "owner": owner.lower(), "curator": curator.lower(),
        "allocators": members("SetIsAllocator(address,bool)", "isAllocator(address)"),
        "sentinels": members("SetIsSentinel(address,bool)", "isSentinel(address)"),
        "timelocks": tl, "adapters": adapters,
        "liquidity_adapter": (c(V, "liquidityAdapter()", "address") or "").lower(),
        "force_deallocate_penalty": {a: (c(V, "forceDeallocatePenalty(address)", "uint256", ["address"], [a]) or 0) / WAD
                                     for a in adapters},
        "performance_fee": (c(V, "performanceFee()", "uint96") or 0) / WAD,
        "management_fee_annual": (c(V, "managementFee()", "uint96") or 0) * YEAR / WAD,
        "gates": {g: c(V, f"{g}()", "address") for g in ("receiveSharesGate", "sendSharesGate",
                                                          "receiveAssetsGate", "sendAssetsGate")},
        "adapter_registry": c(V, "adapterRegistry()", "address"),
    }


def root_asset(fork: Fork, token: str, stop: str, max_hops: int = 4) -> list[str]:
    """Wrapper chain read on-chain: PT -> SY -> yieldToken, ERC-4626 -> asset(). Shared roots = correlated assets.
    Stops before `stop` (the loan asset): a wrapper that deposits USDC is exposed to its own credit, not to USDC."""
    chain = [token.lower()]
    for _ in range(max_hops):
        t = chain[-1]
        sy = fork.call1(t, "SY()", "address")
        nxt = fork.call1(sy, "yieldToken()", "address") if sy else fork.call1(t, "asset()", "address")
        if not nxt or int(nxt, 16) == 0 or nxt.lower() in chain or nxt.lower() == stop or fork.code_size(nxt) == 0:
            break
        chain.append(nxt.lower())
    return chain


def markets(fork: Fork, r: dict) -> list[dict]:
    c = fork.call1
    total = r["total_assets_usd"]
    out = []
    for ad in r["adapters"]:
        for j in range(c(ad, "marketIdsLength()", "uint256") or 0):
            mid = c(ad, "marketIds(uint256)", "bytes32", ["uint256"], [j])
            mp = fork.call(A.MORPHO_BLUE, "idToMarketParams(bytes32)", ["bytes32"], [mid], ["address"] * 4 + ["uint256"])
            mk = fork.call(A.MORPHO_BLUE, "market(bytes32)", ["bytes32"], [mid], ["uint128"] * 6)
            ours = (c(ad, "expectedSupplyAssets(bytes32)", "uint256", ["bytes32"], [mid]) or 0) / 1e6
            # Vault V2 cap ids (MorphoMarketV1Adapter.ids()): market-level and collateral-level
            cap_ids = {"market": keccak(encode(["string", "address", MP], ["this/marketParams", ad, mp])),
                       "collateral": keccak(encode(["string", "address"], ["collateralToken", mp[1]]))}
            caps = {k: {"absolute_usd": (c(V, "absoluteCap(bytes32)", "uint256", ["bytes32"], [i]) or 0) / 1e6,
                        "relative": (c(V, "relativeCap(bytes32)", "uint256", ["bytes32"], [i]) or 0) / WAD}
                    for k, i in cap_ids.items()}
            loan, coll, orc, irm, lltv = mp
            sup, bor = mk[0] / 1e6, mk[2] / 1e6
            roots = root_asset(fork, coll, loan.lower())
            out.append({
                "market_id": "0x" + mid.hex(), "adapter": ad, "params": [loan, coll, orc, irm, lltv],
                "collateral": coll.lower(), "collateral_symbol": c(coll, "symbol()", "string"),
                "collateral_name": c(coll, "name()", "string"), "collateral_decimals": c(coll, "decimals()", "uint8"),
                "root_chain": roots, "root_symbol": c(roots[-1], "symbol()", "string"),
                "oracle": orc.lower(), "irm": irm.lower(), "lltv": lltv / WAD,
                "allocation_usd": ours, "allocation_pct": ours / total if total else 0.0,
                "caps": caps, "market_supply_usd": sup, "market_borrow_usd": bor,
                "utilization": bor / sup if sup else 0.0, "free_liquidity_usd": sup - bor,
                "vault_share_of_market": ours / sup if sup else 0.0,
                "is_liquidity_market": False,
            })
    ld = fork.call(V, "liquidityData()", out_types=["bytes"])
    if ld and len(ld[0]) >= 160:
        lmid = "0x" + keccak(encode([MP], [decode([MP], ld[0])[0]])).hex()
        for m in out:
            m["is_liquidity_market"] = m["market_id"] == lmid
    return sorted(out, key=lambda m: -m["allocation_usd"])


def group_exposure(ms: list[dict], oq: dict) -> dict:
    """Allocation grouped by collateral, root asset (on-chain wrapper chain), oracle, oracle price basis, protocol."""
    basis = oq.get("per_market", {})
    groups: dict[str, Counter] = defaultdict(Counter)
    for m in ms:
        w = m["allocation_pct"]
        groups["collateral"][m["collateral_symbol"]] += w
        groups["root_asset"][m["root_symbol"]] += w
        groups["price_basis"][basis.get(m["collateral_symbol"], {}).get("price_basis", "unknown")] += w
        groups["oracle"][m["oracle"]] += w
        protos = {"Morpho Blue"} | ({"Pendle"} if m["collateral_symbol"].startswith("PT-") else set())
        for p in protos:
            groups["protocol"][p] += w
    return {k: dict(v.most_common()) for k, v in groups.items()}


# =========================================================================== Q2: can borrowers repay?
def borrowers(fork: Fork, m: dict, offline: bool) -> list[dict]:
    """Largest borrowers from the Morpho API; position and health factor re-read on the fork (source of truth)."""
    q = ('{ marketPositions(first:%d, orderBy: BorrowShares, orderDirection: Desc, where:{marketUniqueKey_in:["%s"], '
         'chainId_in:[1]}){ items{ user{address} } } }' % (N_BORROWERS, m["market_id"]))
    items = (_api(f"morpho_borrowers_{m['market_id'][:18]}", lambda: _morpho(q), offline) or {}) \
        .get("marketPositions", {}).get("items", [])
    mid = bytes.fromhex(m["market_id"][2:])
    mk = fork.call(A.MORPHO_BLUE, "market(bytes32)", ["bytes32"], [mid], ["uint128"] * 6)
    price = fork.call1(m["oracle"], "price()", "uint256")
    lltv = int(m["lltv"] * WAD)
    out = []
    for it in items:
        u = it["user"]["address"]
        p = fork.call(A.MORPHO_BLUE, "position(bytes32,address)", ["bytes32", "address"], [mid, u],
                      ["uint256", "uint128", "uint128"])
        if not p or p[1] == 0:
            continue
        debt = -(-p[1] * (mk[2] + 1) // (mk[3] + 10**6))      # round up, as Morpho does
        coll_val = p[2] * price // 10**36 if price else 0
        out.append({"user": u.lower(), "borrow_shares": p[1], "collateral": p[2], "debt_usd": debt / 1e6,
                    "collateral_value_usd": coll_val / 1e6,
                    "hf": coll_val * lltv / WAD / debt if debt else None,
                    "ltv_over_lltv": debt / (coll_val * lltv / WAD) if coll_val else None})
    return sorted(out, key=lambda b: -b["debt_usd"])


def hf_buckets(bs: list[dict]) -> dict:
    edges = [(0, 1.0, "<1.00 (liquidatable)"), (1.0, 1.05, "1.00-1.05"), (1.05, 1.10, "1.05-1.10"),
             (1.10, 1.25, "1.10-1.25"), (1.25, 1e9, ">=1.25")]
    tot = sum(b["debt_usd"] for b in bs) or 1
    return {lab: {"n": sum(1 for b in bs if lo <= (b["hf"] or 0) < hi),
                  "debt_usd": sum(b["debt_usd"] for b in bs if lo <= (b["hf"] or 0) < hi),
                  "debt_share": sum(b["debt_usd"] for b in bs if lo <= (b["hf"] or 0) < hi) / tot}
            for lo, hi, lab in edges}


def collateral_exit(m: dict, bs: list[dict], offline: bool) -> dict:
    """Can a liquidator sell the seized collateral? Aggregator quote at the largest borrower's collateral size."""
    if not bs:
        return {}
    amt = bs[0]["collateral"]
    q = kyber_exit(m["collateral"], amt, offline)
    oracle_val = bs[0]["collateral_value_usd"]
    if not q:
        return {"size_collateral_usd_at_oracle": oracle_val, "route": None,
                "flag": "no aggregator route at liquidation size: liquidators have no on-chain exit"}
    got = q["amount_out"] / 1e6
    return {"size_collateral_usd_at_oracle": oracle_val, "route": "KyberSwap aggregator", "usdc_out": got,
            "discount_vs_oracle": 1 - got / oracle_val if oracle_val else None,
            "liquidation_profitable": got * lif(int(m["lltv"] * WAD)) / WAD >= oracle_val if oracle_val else None}


def shock_market(fork: Fork, m: dict, bs: list[dict], move: float) -> dict:
    """Pin the market oracle at (1+move) x price on the fork, liquidate every underwater borrower with all their
    collateral, and measure what Morpho socializes (market supply drop) and what the vault loses per share."""
    mid = bytes.fromhex(m["market_id"][2:])
    lltv = int(m["lltv"] * WAD)
    L = lif(lltv)
    with fork.snapshot():
        p0 = fork.call1(m["oracle"], "price()", "uint256")
        pps0 = fork.call1(V, "convertToAssets(uint256)", "uint256", ["uint256"], [WAD])
        ta0 = fork.call1(V, "totalAssets()", "uint256")
        sup0 = fork.call(A.MORPHO_BLUE, "market(bytes32)", ["bytes32"], [mid], ["uint128"] * 6)[0]
        p = int(p0 * (1 + move))
        fork.pin_price(m["oracle"], p)
        fork.fund_erc20(A.USDC, HARNESS, 10**9 * 10**6)
        fork.send(HARNESS, A.USDC, selector("approve(address,uint256)") + encode(["address", "uint256"], [A.MORPHO_BLUE, 2**256 - 1]))
        n_liq, frozen_shortfall, errors = 0, 0.0, []
        for b in bs:
            coll_val = b["collateral"] * p // 10**36
            debt = int(b["debt_usd"] * 1e6)
            if coll_val * lltv // WAD >= debt:
                continue
            frozen_shortfall += max(0, debt - coll_val) / 1e6   # if the oracle stayed frozen: silent, unliquidated
            # full repay if the collateral covers debt x LIF, else seize everything (Morpho realizes the rest as bad debt)
            if coll_val * WAD // L >= debt * 1001 // 1000:   # 0.1% margin: seized rounds up
                args = [0, b["borrow_shares"]]
            else:
                args = [b["collateral"], 0]
            data = selector(f"liquidate({MP},address,uint256,uint256,bytes)") + encode(
                [MP, "address", "uint256", "uint256", "bytes"], [tuple(m["params"]), b["user"], *args, b""])
            try:
                fork.send(HARNESS, A.MORPHO_BLUE, data)
                n_liq += 1
            except RuntimeError as e:
                errors.append(f"{b['user'][:10]}: {str(e)[:80]}")
        sup1 = fork.call(A.MORPHO_BLUE, "market(bytes32)", ["bytes32"], [mid], ["uint128"] * 6)[0]
        pps1 = fork.call1(V, "convertToAssets(uint256)", "uint256", ["uint256"], [WAD])
        ta1 = fork.call1(V, "totalAssets()", "uint256")
    bad = max(0, sup0 - sup1) / 1e6
    return {"move": move, "n_liquidated": n_liq, "bad_debt_market_usd": bad,
            "bad_debt_vault_usd": bad * m["vault_share_of_market"],
            "vault_total_assets_change_usd": ((ta1 or 0) - (ta0 or 0)) / 1e6,
            "loss_per_share": 1 - pps1 / pps0 if pps0 and pps1 else None,
            "frozen_oracle_shortfall_usd": frozen_shortfall,
            "errors": errors, "lif": L / WAD,
            "note": "liquidations executed on the fork at the shocked oracle price, assuming a liquidator exists; "
                    "see collateral_exit for whether one could sell the collateral"}


def liquidation_trace(fork: Fork, m: dict, b: dict) -> dict:
    """Trace Morpho.liquidate on this market's largest real borrower, pushed to HF 0.99 by trimming its recorded
    collateral in storage (oracle untouched, so the trace walks the real price path)."""
    mid = bytes.fromhex(m["market_id"][2:])
    lltv = int(m["lltv"] * WAD)
    with fork.snapshot():
        price = fork.call1(m["oracle"], "price()", "uint256")
        debt = int(b["debt_usd"] * 1e6)
        new_coll = int(0.99 * debt * 10**36 * WAD / (price * lltv))
        fork.set_storage(A.MORPHO_BLUE, position_slot(m["market_id"], b["user"]) + 1, b["borrow_shares"] | (new_coll << 128))
        fork.fund_erc20(A.USDC, HARNESS, 10**9 * 10**6)
        fork.send(HARNESS, A.USDC, selector("approve(address,uint256)") + encode(["address", "uint256"], [A.MORPHO_BLUE, 2**256 - 1]))
        data = selector(f"liquidate({MP},address,uint256,uint256,bytes)") + encode(
            [MP, "address", "uint256", "uint256", "bytes"], [tuple(m["params"]), b["user"], new_coll // 10, 0, b""])
        return _trace(fork, {"from": HARNESS, "to": A.MORPHO_BLUE, "data": "0x" + data.hex()},
                      f"liquidation:{m['collateral_symbol']}.morpho.liquidate")


# =========================================================================== Q3: can depositors withdraw?
def depositors(fork: Fork) -> tuple[list[dict], dict]:
    """Vault share balances rebuilt from Transfer logs (Etherscan), each re-read with balanceOf on the fork."""
    bal: Counter = Counter()
    for l in get_logs(V, "0x" + keccak(text="Transfer(address,address,uint256)").hex(), 0, fork.fork_block):
        v = int(l["data"], 16)
        bal[_topic_addr(l["topics"][1])] -= v
        bal[_topic_addr(l["topics"][2])] += v
    bal.pop("0x" + "0" * 40, None)
    supply = fork.call1(V, "totalSupply()", "uint256") or 1
    out = []
    for a, _ in bal.most_common(N_DEPOSITORS * 2):
        sh = fork.call1(V, "balanceOf(address)", "uint256", ["address"], [a]) or 0
        if sh == 0:
            continue
        out.append({"address": a, "shares": sh, "share_of_vault": sh / supply, "is_contract": fork.code_size(a) > 0,
                    "assets_usd": (fork.call1(V, "convertToAssets(uint256)", "uint256", ["uint256"], [sh]) or 0) / 1e6})
    out = sorted(out, key=lambda d: -d["shares"])
    hhi = sum(d["share_of_vault"] ** 2 for d in out)
    return out[:N_DEPOSITORS], {"n_holders_with_balance": sum(1 for v in bal.values() if v > 0),
                                "top1_share": out[0]["share_of_vault"] if out else None,
                                "top5_share": sum(d["share_of_vault"] for d in out[:5]),
                                "top10_share": sum(d["share_of_vault"] for d in out[:10]),
                                "hhi_top20": hhi}


def withdrawable_now(r: dict, ms: list[dict]) -> dict:
    idle = 0.0   # filled by caller from USDC.balanceOf(vault)
    liq = next((m for m in ms if m["is_liquidity_market"]), None)
    instant = min(liq["allocation_usd"], liq["free_liquidity_usd"]) if liq else 0.0
    forced = {m["collateral_symbol"]: min(m["allocation_usd"], m["free_liquidity_usd"])
              for m in ms if not m["is_liquidity_market"]}
    pen = r["force_deallocate_penalty"].get(r["liquidity_adapter"]) or max(r["force_deallocate_penalty"].values() or [0])
    return {"idle_usd": idle, "liquidity_market": liq and liq["collateral_symbol"],
            "instant_from_liquidity_market_usd": instant,
            "force_deallocatable_usd": forced, "force_deallocate_penalty": pen,
            "total_reachable_usd": instant + sum(forced.values())}


def irm_apr(fork: Fork, m: dict) -> float | None:
    mid = bytes.fromhex(m["market_id"][2:])
    mk = fork.call(A.MORPHO_BLUE, "market(bytes32)", ["bytes32"], [mid], ["uint128"] * 6)
    r = fork.call1(m["irm"], f"borrowRateView({MP},(uint128,uint128,uint128,uint128,uint128,uint128))", "uint256",
                   [MP, "(uint128,uint128,uint128,uint128,uint128,uint128)"], [tuple(m["params"]), tuple(mk)])
    return r * YEAR / WAD if r is not None else None


def run_simulation(fork: Fork, r: dict, ms: list[dict], deps: list[dict]) -> dict:
    """Bank run executed on the fork: depositors exit in rank order, each force-deallocating from every market
    with free liquidity (paying the penalty) then withdrawing through the liquidity market. Each exit drains
    liquidity for the next one."""
    vault_ms = {m["market_id"]: m for m in ms}
    rows = []
    with fork.snapshot():
        for rank, d in enumerate(deps, 1):
            a = d["address"]
            sh = fork.call1(V, "balanceOf(address)", "uint256", ["address"], [a]) or 0
            owned = fork.call1(V, "convertToAssets(uint256)", "uint256", ["uint256"], [sh]) or 0
            usdc0 = fork.call1(A.USDC, "balanceOf(address)", "uint256", ["address"], [a]) or 0
            need, steps = owned, []
            for m in sorted(ms, key=lambda x: -x["free_liquidity_usd"]):
                if m["is_liquidity_market"] or need <= 10**6:
                    continue
                mid = bytes.fromhex(m["market_id"][2:])
                mk = fork.call(A.MORPHO_BLUE, "market(bytes32)", ["bytes32"], [mid], ["uint128"] * 6)
                ours = fork.call1(m["adapter"], "expectedSupplyAssets(bytes32)", "uint256", ["bytes32"], [mid]) or 0
                amt = min(need, mk[0] - mk[2], ours)
                if amt <= 10**6:
                    continue
                try:
                    fork.send(a, V, selector("forceDeallocate(address,bytes,uint256,address)") + encode(
                        ["address", "bytes", "uint256", "address"], [m["adapter"], encode([MP], [tuple(m["params"])]), amt, a]))
                    need -= amt
                    steps.append({"force_deallocate": m["collateral_symbol"], "usd": amt / 1e6})
                except RuntimeError as e:
                    steps.append({"force_deallocate": m["collateral_symbol"], "error": str(e)[:80]})
            # withdraw what the vault can pay: idle + free liquidity of the liquidity market (capped by what we own)
            sh = fork.call1(V, "balanceOf(address)", "uint256", ["address"], [a]) or 0
            mine = fork.call1(V, "convertToAssets(uint256)", "uint256", ["uint256"], [sh]) or 0
            idle = fork.call1(A.USDC, "balanceOf(address)", "uint256", ["address"], [V]) or 0
            liq = next((m for m in ms if m["is_liquidity_market"]), None)
            liq_free = 0
            if liq:
                mid = bytes.fromhex(liq["market_id"][2:])
                mk = fork.call(A.MORPHO_BLUE, "market(bytes32)", ["bytes32"], [mid], ["uint128"] * 6)
                ours = fork.call1(liq["adapter"], "expectedSupplyAssets(bytes32)", "uint256", ["bytes32"], [mid]) or 0
                liq_free = min(mk[0] - mk[2], ours)
            w = max(0, min(mine, idle + liq_free) - 2)     # -2 wei: share rounding
            if w > 10**6:
                try:
                    fork.send(a, V, selector("withdraw(uint256,address,address)") + encode(["uint256", "address", "address"], [w, a, a]))
                    steps.append({"withdraw_usd": w / 1e6})
                except RuntimeError as e:
                    steps.append({"withdraw_usd": w / 1e6, "error": str(e)[:80]})
            got = (fork.call1(A.USDC, "balanceOf(address)", "uint256", ["address"], [a]) or 0) - usdc0
            rows.append({"rank": rank, "address": a, "owned_usd": owned / 1e6, "recovered_usd": got / 1e6,
                         "recovered_pct": got / owned if owned else None, "steps": steps})
        after = []
        for m in vault_ms.values():
            mid = bytes.fromhex(m["market_id"][2:])
            mk = fork.call(A.MORPHO_BLUE, "market(bytes32)", ["bytes32"], [mid], ["uint128"] * 6)
            after.append({"market": m["collateral_symbol"], "utilization": mk[2] / mk[0] if mk[0] else None,
                          "borrow_apr": irm_apr(fork, m)})
    tot_owned = sum(x["owned_usd"] for x in rows)
    tot_got = sum(x["recovered_usd"] for x in rows)
    return {"ranks": rows, "after_run": after, "total_owned_usd": tot_owned, "total_recovered_usd": tot_got,
            "locked_usd": tot_owned - tot_got,
            "note": "remaining deposits wait for borrower repayments or for the IRM rate (after_run.borrow_apr) to "
                    "pull new supply in; time to full exit is modelled in Module 3"}


# =========================================================================== build
def build(offline: bool = False):
    fork = Fork(offline=offline)
    if fork.offline:
        fork.fork_block = A.FORK_BLOCK
    elif fork.fork_block != A.FORK_BLOCK:
        print(f"⚠️  fork head {fork.fork_block} != pinned {A.FORK_BLOCK}; traces will be keyed to {fork.fork_block}")
    blk = fork.fork_block
    b = GraphBuilder(fork, H["position_id"], f"Deposit in RockawayX USDC Yield ({LABEL})")
    g = b.g
    prov_s = lambda d: Provenance(source="storage", block=blk, detail=d)   # noqa: E731

    print("▶ Q1 roles + timelocks ...")
    r = roles(fork)
    print("▶ Q1 markets ...")
    ms = markets(fork, r)
    idle = (fork.call1(A.USDC, "balanceOf(address)", "uint256", ["address"], [V]) or 0) / 1e6

    # ---- graph: vault, roles, adapters, markets
    g.add_node(Node(id="chain:ethereum", type=NodeType.CHAIN, label="Ethereum"))
    b.ensure(V, prov_s("hero #2 vault"), CriticalPath.VALUE)
    g.nodes[V].tags.add("belem_rockawayx")
    g.add_edge(Edge(src=b.root, dst=V, type=EdgeType.HOLDS, props={"role": "depositor"}))
    g.add_edge(Edge(src=b.root, dst="chain:ethereum", type=EdgeType.REFERENCES, props={"role": "settlement"}))
    for role, addrs in (("owner", [r["owner"]]), ("curator", [r["curator"]]), ("allocator", r["allocators"]),
                        ("sentinel", r["sentinels"])):
        for a in addrs:
            b._gov_edge(V, a, f"{role}()" if role in ("owner", "curator") else f"is{role.capitalize()}", "onchain_read")
            g.nodes[a.lower()].props.setdefault("vault_roles", []).append(role)
    for ad in r["adapters"]:
        b.ensure(ad, prov_s("vault.adapters(i)"), CriticalPath.VALUE)
        g.add_edge(Edge(src=V, dst=ad, type=EdgeType.ALLOCATES_TO, provenance=[prov_s("vault.adapters(i)")]))
    traces = [(CriticalPath.VALUE, _trace(fork, {"to": V, "data": "0x" + selector("totalAssets()").hex()},
                                         "value:vault.totalAssets"), V)]
    for m in ms:
        mn = f"morpho_market:{m['market_id']}"
        m["node"] = mn
        p = prov_s("adapter.marketIds + Morpho.idToMarketParams")
        for a in (m["collateral"], m["oracle"], m["irm"], A.USDC, A.MORPHO_BLUE):
            b.ensure(a, p, CriticalPath.VALUE if a in (m["collateral"], m["oracle"]) else None)
        g.add_node(Node(id=mn, type=NodeType.LENDING_MARKET,
                        label=f"Morpho {m['collateral_symbol']}/USDC {m['lltv'] * 100:.1f}%",
                        props={k: m[k] for k in ("market_id", "lltv", "allocation_usd", "allocation_pct", "utilization",
                                                 "free_liquidity_usd", "market_supply_usd", "is_liquidity_market")},
                        paths={CriticalPath.VALUE}, provenance=[p]))
        g.add_edge(Edge(src=m["adapter"], dst=mn, type=EdgeType.ALLOCATES_TO,
                        props={"allocation_usd": m["allocation_usd"], "caps": m["caps"]}, provenance=[p]))
        g.add_edge(Edge(src=mn, dst=A.MORPHO_BLUE.lower(), type=EdgeType.REFERENCES, props={"role": "singleton"}, provenance=[p]))
        g.add_edge(Edge(src=mn, dst=m["oracle"], type=EdgeType.PRICES, provenance=[p]))
        g.add_edge(Edge(src=mn, dst=m["irm"], type=EdgeType.REFERENCES, props={"role": "irm"}, provenance=[p]))
        g.add_edge(Edge(src=mn, dst=m["collateral"], type=EdgeType.USES_COLLATERAL, provenance=[p]))
        g.add_edge(Edge(src=mn, dst=A.USDC.lower(), type=EdgeType.LENDS, provenance=[p]))
        for x, y in zip(m["root_chain"], m["root_chain"][1:]):   # wrapper chain read on-chain
            b.ensure(y, Provenance(source="onchain_read", block=blk, detail="SY().yieldToken() / asset()"))
            g.add_edge(Edge(src=x, dst=y, type=EdgeType.WRAPS,
                            provenance=[Provenance(source="onchain_read", block=blk, detail="SY().yieldToken() / asset()")]))
        traces.append((CriticalPath.VALUE, _trace(fork, {"from": A.MORPHO_BLUE, "to": m["oracle"],
                                                         "data": "0x" + selector("price()").hex()},
                                                  f"value:{m['collateral_symbol']}.oracle.price"), mn))

    print("▶ Q2 borrowers, collateral exit, shocks on the fork ...")
    q2 = []
    for m in ms:
        bs = borrowers(fork, m, offline)
        rec = {"market": m["collateral_symbol"], "market_id": m["market_id"], "n_borrowers_read": len(bs),
               "debt_covered_usd": sum(x["debt_usd"] for x in bs), "market_borrow_usd": m["market_borrow_usd"],
               "largest": bs[:5], "hf_buckets": hf_buckets(bs), "collateral_exit": collateral_exit(m, bs, offline),
               "shocks": [shock_market(fork, m, bs, s) for s in SHOCKS] if bs else []}
        if bs:
            traces.append((CriticalPath.LIQUIDATION, liquidation_trace(fork, m, bs[0]), m["node"]))
            g.nodes[m["node"]].paths.add(CriticalPath.LIQUIDATION)
        q2.append(rec)
        worst = rec["shocks"][-1] if rec["shocks"] else {}
        print(f"   {m['collateral_symbol']:22s} {len(bs):3d} borrowers  HF<1.05: "
              f"{rec['hf_buckets']['<1.00 (liquidatable)']['debt_share'] + rec['hf_buckets']['1.00-1.05']['debt_share']:5.1%} of debt"
              f"  @-50%: vault bad debt ${worst.get('bad_debt_vault_usd', 0):,.0f}")

    print("▶ Q3 depositors + run on the fork ...")
    deps, conc = depositors(fork)
    wn = withdrawable_now(r, ms)
    wn["idle_usd"] = idle
    wn["total_reachable_usd"] += idle
    run = run_simulation(fork, r, ms, deps) if deps else {}
    if deps:   # EXIT trace: the top depositor withdrawing what the vault can pay instantly
        a = deps[0]["address"]
        w = int(min(deps[0]["assets_usd"], wn["idle_usd"] + wn["instant_from_liquidity_market_usd"]) * 1e6) - 2
        if w > 0:
            traces.append((CriticalPath.EXIT, _trace(fork, {"from": a, "to": V, "data": "0x" + (
                selector("withdraw(uint256,address,address)") + encode(["uint256", "address", "address"], [w, a, a])).hex()},
                "exit:vault.withdraw(top depositor)"), V))

    for path, t, entry in traces:
        b.ingest_trace(t["call"], t["pre"], path, t["label"], entry_src=entry)
    print("▶ resolving proxies / admins / owners / stored addresses ...")
    b.resolve({CriticalPath.VALUE: 2, CriticalPath.LIQUIDATION: 1, CriticalPath.EXIT: 1})
    disclosures.apply(g)
    for m in ms:   # oracle params (feeds, vaults, scale) for the feed-quality analysis
        if m["oracle"] in g.nodes:
            b.read_params(m["oracle"])
    oq = oracle_quality.analyse(b, fork.block_timestamp(), ms[0]["oracle"] if ms else "", "value:vault.totalAssets")
    oq["per_market"] = {}
    for m in ms:
        executed = b.touched.get(f"value:{m['collateral_symbol']}.oracle.price", set())
        leaves = [g.nodes[x] for x in executed if x in g.nodes and g.nodes[x].type == NodeType.ORACLE
                  and "implementation" not in g.nodes[x].tags
                  and ("chainlink_interface" in g.nodes[x].tags or "morpho_oracle_interface" not in g.nodes[x].tags)]
        # one source per description (an EAC proxy and its OCR aggregator are the same feed); the loan-asset quote
        # (USDC / USD) prices the debt, not the collateral
        src: dict[str, str] = {}
        for n in leaves:
            key = n.props.get("description") or n.label
            if key.upper().startswith("USDC / USD"):
                continue
            src.setdefault(key, oracle_quality._kind(n)[1])
        kinds = sorted(set(src.values()))
        rec = {"executed_leaf_feeds": sorted(src), "kinds": src,
               "n_market_derived": sum(k == oracle_quality.MARKET for k in src.values()),
               "price_basis": "market" if oracle_quality.MARKET in kinds else
                              "issuer_reported" if oracle_quality.ISSUER_REPORTED in kinds else
                              "exchange_rate" if oracle_quality.EXCHANGE_RATE in kinds else
                              "hardcoded" if set(kinds) & set(oracle_quality.HARDCODED) else "unknown"}
        if rec["n_market_derived"] == 0:
            rec["flag"] = (f"NO market-derived feed: collateral priced by {rec['price_basis'].replace('_', ' ')} "
                           "(the market cannot signal a loss; issuer or schedule sets the price)")
        elif rec["n_market_derived"] == 1:
            rec["flag"] = "asset priced by a SINGLE market feed"
        oq["per_market"][m["collateral_symbol"]] = rec
    conc_tvl = tvl.concentration(g, "ethereum", offline=fork.offline)

    q1 = {"roles": r, "markets": [{k: v for k, v in m.items() if k not in ("params",)} for m in ms],
          "exposure": group_exposure(ms, oq), "idle_usd": idle}
    q3 = {"withdrawable_now": wn, "depositor_concentration": conc, "top_depositors": deps, "run": run}
    g.meta = {"label": LABEL, "vault": V, "fork_block": blk, "q1": q1, "q2": q2, "q3": q3,
              "oracle_quality": oq, "tvl_concentration": conc_tvl, "depth": depth_report(g),
              "critical_nodes": critical_nodes(g), "findings": findings(q1, q2, q3, oq),
              "n_nodes": len(g.nodes), "n_edges": len(g.edges)}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "hero2.json").write_text(g.to_json())
    viz.export(OUT / "hero2.json", ROOT / "output" / "hero2_graph.html")
    return g


def findings(q1: dict, q2: list[dict], q3: dict, oq: dict) -> list[dict]:
    """Plain statements of what the data shows. No breach is asserted beyond the measured numbers."""
    out = []
    r, wn = q1["roles"], q3["withdrawable_now"]
    tot = r["total_assets_usd"] or 1
    out.append({"q": "Q3", "kind": "instant_liquidity",
                "why": f"instantly withdrawable ${wn['idle_usd'] + wn['instant_from_liquidity_market_usd']:,.0f} "
                       f"({(wn['idle_usd'] + wn['instant_from_liquidity_market_usd']) / tot:.1%} of ${tot:,.0f}) via the "
                       f"{wn['liquidity_market']} liquidity market; ${wn['total_reachable_usd']:,.0f} reachable with "
                       f"forceDeallocate at a {wn['force_deallocate_penalty']:.2%} penalty"})
    c = q3["depositor_concentration"]
    if c.get("top1_share"):
        out.append({"q": "Q3", "kind": "depositor_concentration",
                    "why": f"top depositor holds {c['top1_share']:.1%} of shares, top 5 hold {c['top5_share']:.1%}"})
    if r["owner"] == r["curator"]:
        out.append({"q": "Q1", "kind": "governance", "why": f"owner and curator are the same address {r['owner']}"})
    zero = [k for k, v in r["timelocks"].items() if v["timelock_s"] == 0 and not v["abdicated"]]
    if zero:
        out.append({"q": "Q1", "kind": "zero_timelock", "why": "no timelock (immediate): " + ", ".join(zero)})
    for k, v in q1["exposure"]["root_asset"].items():
        if v >= 0.10:
            out.append({"q": "Q1", "kind": "root_asset_share", "why": f"{v:.1%} of the vault ultimately rests on {k}"})
    for m, rec in oq.get("per_market", {}).items():
        if rec.get("flag"):
            out.append({"q": "Q1", "kind": "oracle", "why": f"{m}: {rec['flag']} ({', '.join(rec['executed_leaf_feeds']) or 'none'})"})
    for rec in q2:
        ce = rec["collateral_exit"]
        if ce.get("flag"):
            out.append({"q": "Q2", "kind": "collateral_exit", "why": f"{rec['market']}: {ce['flag']}"})
        near = rec["hf_buckets"]["<1.00 (liquidatable)"]["debt_share"] + rec["hf_buckets"]["1.00-1.05"]["debt_share"]
        if near > 0.25:
            out.append({"q": "Q2", "kind": "borrowers_near_lltv", "why": f"{rec['market']}: {near:.0%} of read debt has HF < 1.05"})
    for f in out:
        f["label"] = f["q"]
    return out


def print_summary(g):
    m = g.meta
    r = m["q1"]["roles"]
    print(f"\n=== HERO #2 · {m['label']} · {r['name']} ({r['symbol']}) · block {m['fork_block']} ===")
    print(f"totalAssets ${r['total_assets_usd']:,.0f} · owner {r['owner']} · curator {r['curator']}")
    print(f"allocators {r['allocators']} · sentinels {r['sentinels']}")
    print("\nQ1 WHERE DOES THE MONEY GO?")
    for x in m["q1"]["markets"]:
        print(f"  {x['collateral_symbol']:22s} ${x['allocation_usd']:>12,.0f} {x['allocation_pct']:6.1%}  LLTV {x['lltv']:.1%}  "
              f"util {x['utilization']:.1%}  cap ${x['caps']['market']['absolute_usd']:,.0f}  root {x['root_symbol']}"
              f"{'  [LIQUIDITY MARKET]' if x['is_liquidity_market'] else ''}")
    print("  exposure by root asset:", {k: f"{v:.1%}" for k, v in m["q1"]["exposure"]["root_asset"].items()})
    print("\nQ2 CAN BORROWERS REPAY?")
    for rec in m["q2"]:
        sh = {f"{s['move']:+.0%}": f"${s['bad_debt_vault_usd']:,.0f}" for s in rec["shocks"]}
        print(f"  {rec['market']:22s} vault bad debt by oracle move: {sh}  exit: "
              f"{rec['collateral_exit'].get('discount_vs_oracle') if rec['collateral_exit'].get('route') else 'NO ROUTE'}")
    print("\nQ3 CAN DEPOSITORS WITHDRAW?")
    wn = m["q3"]["withdrawable_now"]
    print(f"  instant ${wn['idle_usd'] + wn['instant_from_liquidity_market_usd']:,.0f} · reachable with forceDeallocate "
          f"${wn['total_reachable_usd']:,.0f} (penalty {wn['force_deallocate_penalty']:.2%})")
    for x in m["q3"]["run"].get("ranks", []):
        print(f"  rank {x['rank']:2d} {x['address'][:10]} owns ${x['owned_usd']:>12,.0f} → recovered {x['recovered_pct'] or 0:6.1%}")
    print("\nFINDINGS")
    for f in m["findings"]:
        print(f"  [{f['q']}] {f['why']}")
    print(f"\n{m['n_nodes']} nodes, {m['n_edges']} edges → data/graphs/hero2.json, output/hero2_graph.html")


if __name__ == "__main__":
    print_summary(build(offline="--offline" in sys.argv))
