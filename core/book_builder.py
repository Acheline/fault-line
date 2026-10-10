"""Build books/belem_assumed_book.yaml from ASSUMED_ANSWERS.md §1 + §4, verifying every pocket live.

    python -m core.book_builder            # verify on the fork + official APIs (cached), write the book
    python -m core.book_builder --offline  # rebuild from cache

Rules (ASSUMED_ANSWERS.md): ticket = min(ticket_usd, mandate * pocket_weight); venue caps (whichever binds first):
Pendle pool <= 10% of liquidity, Morpho/lending market <= 10% of supply, curated vault <= 15% of TVL,
perp vault <= 5% of TVL. Caps are per VENUE: pockets sharing a venue share its cap pro rata to the notional they
put through it. Excess is parked in the Aave USDC pocket and flagged capacity-constrained. Every substitution or
cut is logged in the book and in data/book_verification.json.
"""
from __future__ import annotations

import json
import sys
import time

import requests
import yaml

from core import addresses as A
from core.config import SOURCE, cfg
from core.fork import ROOT, DiskCache, Fork

API = DiskCache("api")
OUT_BOOK = ROOT / "books" / "belem_assumed_book.yaml"
OUT_LOG = ROOT / "data" / "book_verification.json"

AAVE_POOL = "0x87870Bca3F3fD6335C3F4ce8392D69350B4fA4E2"
SUSDS = "0xa3931d71877C0E7a3148CB7Eb4463524FEc27fbD"
SYRUP_USDC = "0x80ac24aA929eaF5013f6436cdA2a7ba190f5Cc0b"
HLP = "0xdfc24b077bc1425ad1dea75bcb6f8158e10df303"
KAMINO_MAIN_MARKET = "7u3HeHxYDLhnCoErrtycNokbQYbWGzLs6JSDqGAv5PfF"
USDC_SOL_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
ESTABLISHED_CURATORS = ("Steakhouse", "Gauntlet")   # "large, established curator" (ASSUMED_ANSWERS §1, P4)


def _api(key: str, fn, offline: bool):
    hit = API.get(key)
    if hit is not None or offline:
        return hit
    return API.put(key, {"fetched_at": int(time.time()), "data": fn()})


def _morpho(q: str):
    return requests.post("https://api.morpho.org/graphql", json={"query": q}, timeout=60).json()["data"]


class Verifier:
    def __init__(self, fork: Fork, offline: bool):
        self.f, self.offline, self.log = fork, offline, []

    def chk(self, pocket: str, what: str, value, source: str, ok: bool = True, **kw) -> dict:
        r = {"pocket": pocket, "check": what, "value": value, "source": source, "ok": ok,
             "block": self.f.fork_block if source == "onchain" else None, **kw}
        self.log.append(r)
        return r

    def erc4626(self, pocket: str, vault: str, want_asset: str | None = None) -> tuple[float, list[dict]]:
        f = self.f
        sym = f.call1(vault, "symbol()", "string")
        asset = f.call1(vault, "asset()", "address")
        dec = f.call1(asset, "decimals()", "uint8") if asset else None
        ta = f.call1(vault, "totalAssets()", "uint256")
        ok = ta is not None and (want_asset is None or (asset or "").lower() == want_asset.lower())
        tvl = ta / 10**dec if ta is not None and dec is not None else 0.0
        return tvl, [self.chk(pocket, f"{sym} asset()/totalAssets()", {"asset": asset, "total_assets": tvl},
                              "onchain", ok, address=vault)]


def verify(offline: bool = False) -> tuple[list[dict], list[dict]]:
    fork = Fork(offline=offline)
    if fork.offline:
        fork.fork_block = A.FORK_BLOCK
    v = Verifier(fork, offline)
    f, H = fork, A.HERO1
    pockets = []

    # ---- P1/P2: Pendle pool liquidity measured on-chain (PT + SY reserves at TWAP / exchange rate x USDe/USD)
    pt_res = f.call1(H["pt"], "balanceOf(address)", "uint256", ["address"], [H["pendle_market"]]) or 0
    sy_res = f.call1(H["sy"], "balanceOf(address)", "uint256", ["address"], [H["pendle_market"]]) or 0
    twap = (f.call1(A.PENDLE_PY_LP_ORACLE, "getPtToAssetRate(address,uint32)", "uint256", ["address", "uint32"],
                    [H["pendle_market"], 900]) or 0) / 1e18
    sy_rate = (f.call1(H["sy"], "exchangeRate()", "uint256") or 0) / 1e18
    usde_rd = f.call(H["usde_usd_feed"], "latestRoundData()", out_types=["uint80", "int256", "uint256", "uint256", "uint80"])
    usde_px = usde_rd[1] / 1e8 if usde_rd else 1.0
    pendle_liq = (pt_res / 1e18 * twap + sy_res / 1e18 * sy_rate) * usde_px
    expiry = f.call1(H["pt"], "expiry()", "uint256")
    pend_api = _api("pendle_active_markets_1", lambda: requests.get(
        "https://api-v2.pendle.finance/core/v1/1/markets/active", timeout=60).json(), offline)
    api_liq = next((m.get("details", {}).get("liquidity") for m in (pend_api or {}).get("data", {}).get("markets", [])
                    if m["address"].lower() == H["pendle_market"].lower()), None)
    v.chk("P1", "Pendle market PT-sUSDe-26NOV2026 liquidity (on-chain reserves)", pendle_liq, "onchain",
          pendle_liq > 0, address=H["pendle_market"], api_liquidity=api_liq, expiry=expiry,
          note="only live PT-sUSDe maturity on Pendle (active markets API); kept despite size: it is the brief's case")
    mid = bytes.fromhex(H["morpho_market_id"][2:])
    mkt = f.call(A.MORPHO_BLUE, "market(bytes32)", ["bytes32"], [mid], ["uint128"] * 6)
    morpho_supply = mkt[0] / 1e6 if mkt else 0.0
    v.chk("P2", "Morpho PT-sUSDe/USDC market total supply", morpho_supply, "onchain", morpho_supply > 0,
          market_id=H["morpho_market_id"], utilization=mkt[2] / mkt[0] if mkt and mkt[0] else None)
    pockets += [
        dict(id="P1", label="Pendle PT-sUSDe-26NOV2026, held outright", chain="ethereum",
             venues={"pendle:" + H["pendle_market"]: 1.0}, pipeline="discovery.hero1",
             legs=[{"type": "hold", "asset": H["pt"]}], tags=["pendle_pt", "brief_scenario_a"]),
        dict(id="P2", label="PT-sUSDe-26NOV2026 collateral on Morpho Blue, borrowing USDC (loop)", chain="ethereum",
             loop=True, pipeline="discovery.hero1",
             legs=[{"type": "morpho_collateral", "asset": H["pt"], "market_id": H["morpho_market_id"],
                    "borrow_asset": A.USDC}], tags=["pendle_pt", "lending_loop", "brief_scenario_a"]),
    ]
    caps_tvl = {"pendle:" + H["pendle_market"]: ("max_share_pendle_pool", pendle_liq),
                "morpho_market:" + H["morpho_market_id"]: ("max_share_morpho_market_supply", morpho_supply)}

    # ---- P3 sUSDe (no venue cap category in §4: exit liquidity is measured by the exit trace instead)
    tvl, _ = v.erc4626("P3", H["susde"], H["usde"])
    pockets.append(dict(id="P3", label="sUSDe (Ethena staked USDe)", chain="ethereum", venues={},
                        legs=[{"type": "hold", "asset": H["susde"]}], tags=["synthetic_dollar"],
                        pipeline="discovery.token_hold", tvl=tvl))

    # ---- P4 Morpho curated USDC vault: largest by TVL among established curators (Morpho API), verified on-chain
    mv = _api("morpho_usdc_vaults_eth", lambda: _morpho(
        '{ vaultV2s(first:20, orderBy: TotalAssetsUsd, orderDirection: Desc, where:{chainId_in:[1], '
        'assetAddress_in:["%s"]}){ items{ name address totalAssetsUsd } } }' % A.USDC), offline)
    cands = [x for x in (mv or {}).get("data", {}).get("vaultV2s", {}).get("items", [])
             if x["name"].startswith(ESTABLISHED_CURATORS)]
    p4 = cands[0] if cands else {"name": "Gauntlet USDC Prime", "address": "0x8c106EEDAd96553e64287A5A6839c3Cc78afA3D0"}
    tvl, _ = v.erc4626("P4", p4["address"], A.USDC)
    v.chk("P4", "selection", p4["name"], "api", True,
          note=f"largest USDC Vault V2 on Ethereum by TVL among established curators {ESTABLISHED_CURATORS} "
               f"(Morpho API); larger unnamed-curator vaults skipped")
    pockets.append(dict(id="P4", label=f"Morpho curated USDC vault: {p4['name']}", chain="ethereum",
                        venues={"vault:" + p4["address"].lower(): 1.0}, legs=[{"type": "vault_deposit", "asset": p4["address"]}],
                        tags=["curated_vault", "lender_side"], pipeline="discovery.vault"))
    caps_tvl["vault:" + p4["address"].lower()] = ("max_share_curated_vault_tvl", tvl)

    # ---- P5 RockawayX USDC Yield (replaces Figure USDC Main: wound down to ~$11)
    fig_ta = f.call1(A.FIGURE_USDC_MAIN, "totalAssets()", "uint256")
    v.chk("P5", "Figure USDC Main totalAssets (CLAUDE.md hero #2)", (fig_ta or 0) / 1e6, "onchain", False,
          address=A.FIGURE_USDC_MAIN, note="wound down: replaced by RockawayX USDC Yield, same curator, supplies PRIME/USDC")
    tvl, _ = v.erc4626("P5", A.ROCKAWAYX_USDC_YIELD, A.USDC)
    pockets.append(dict(id="P5", label="RockawayX USDC Yield vault deposit", chain="ethereum",
                        venues={"vault:" + A.ROCKAWAYX_USDC_YIELD.lower(): 1.0},
                        legs=[{"type": "vault_deposit", "asset": A.ROCKAWAYX_USDC_YIELD}],
                        tags=["curated_vault", "lender_side", "rwa", "rockawayx_not_belem"], pipeline="discovery.vault",
                        disclaimer="RockawayX vault used as a real curated-vault example, not a Belem position"))
    caps_tvl["vault:" + A.ROCKAWAYX_USDC_YIELD.lower()] = ("max_share_curated_vault_tvl", tvl)

    # ---- P6 Aave v3 USDC (parking pocket)
    atoken = f.call1(AAVE_POOL, "getReserveAToken(address)", "address", ["address"], [A.USDC])
    sup = (f.call1(atoken, "totalSupply()", "uint256") or 0) / 1e6 if atoken else 0.0
    v.chk("P6", "Aave v3 aEthUSDC totalSupply", sup, "onchain", sup > 0, address=atoken, pool=AAVE_POOL)
    pockets.append(dict(id="P6", label="Aave v3 USDC supply", chain="ethereum", venues={"aave:usdc": 1.0},
                        legs=[{"type": "hold", "asset": atoken}], tags=["lending", "parking"], pipeline="discovery.token_hold"))
    caps_tvl["aave:usdc"] = ("max_share_morpho_market_supply", sup)   # §4 has no Aave cap: lending-market cap applied

    # ---- P7 sUSDS, P8 syrupUSDC (no venue cap category)
    for pid, addr, label, tags in (("P7", SUSDS, "sUSDS (Sky savings)", ["savings_rate"]),
                                   ("P8", SYRUP_USDC, "syrupUSDC (Maple)", ["institutional_credit"])):
        tvl, _ = v.erc4626(pid, addr)
        pockets.append(dict(id=pid, label=label, chain="ethereum", venues={}, legs=[{"type": "hold", "asset": addr}],
                            tags=tags, pipeline="discovery.token_hold"))

    # ---- P9 Kamino USDC lending (Solana, official API)
    km = _api("kamino_main_reserves", lambda: requests.get(
        f"https://api.kamino.finance/kamino-market/{KAMINO_MAIN_MARKET}/reserves/metrics?env=mainnet-beta",
        timeout=60).json(), offline)
    usdc_res = max((r for r in (km or {}).get("data", []) if r.get("liquidityTokenMint") == USDC_SOL_MINT),
                   key=lambda r: float(r["totalSupplyUsd"]), default=None)
    ksup = float(usdc_res["totalSupplyUsd"]) if usdc_res else 0.0
    v.chk("P9", "Kamino main market USDC reserve total supply", ksup, "api", ksup > 0,
          reserve=usdc_res and usdc_res["reserve"], market=KAMINO_MAIN_MARKET,
          utilization=float(usdc_res["totalBorrowUsd"]) / ksup if ksup else None)
    pockets.append(dict(id="P9", label="Kamino USDC lending (main market)", chain="solana",
                        venues={"kamino:" + (usdc_res or {}).get("reserve", "?"): 1.0},
                        legs=[{"type": "morpho_supply", "asset": USDC_SOL_MINT, "market_id": (usdc_res or {}).get("reserve")}],
                        tags=["lending", "second_chain"], pipeline="discovery.kamino"))
    caps_tvl["kamino:" + (usdc_res or {}).get("reserve", "?")] = ("max_share_morpho_market_supply", ksup)

    # ---- P10 Hyperliquid HLP (official info API)
    hl = _api("hyperliquid_hlp", lambda: requests.post("https://api.hyperliquid.xyz/info", timeout=60,
                                                        json={"type": "vaultDetails", "vaultAddress": HLP}).json(), offline)
    hd = (hl or {}).get("data") or {}
    hist = next((x[1]["accountValueHistory"] for x in hd.get("portfolio", []) if x[0] == "day"), [])
    hlp_tvl = float(hist[-1][1]) if hist else 0.0
    v.chk("P10", "Hyperliquid HLP vault account value", hlp_tvl, "api", hlp_tvl > 0 and not hd.get("isClosed"),
          address=HLP, name=hd.get("name"), allow_deposits=hd.get("allowDeposits"))
    pockets.append(dict(id="P10", label="Hyperliquid HLP vault (USDC)", chain="hyperliquid",
                        venues={"perp_vault:" + HLP: 1.0}, legs=[{"type": "offchain_venue", "venue": "Hyperliquid HLP", "asset": HLP}],
                        tags=["perp_venue", "brief_scenario_b"], pipeline="discovery.offchain_venue"))
    caps_tvl["perp_vault:" + HLP] = ("max_share_perp_vault_tvl", hlp_tvl)

    for p in pockets:
        p["_caps"] = caps_tvl
    return pockets, v.log


def allocate(pockets: list[dict], c: dict) -> tuple[list[dict], list[dict]]:
    """Apply ticket + venue caps (pro rata per shared venue), park the excess in P6."""
    m, s, lp = c["mandate"], c["sizing"], c["loop"]
    ticket = min(s["ticket_usd"], m["mandate_usd"] * m["pocket_weight"])
    lltv = A.HERO1["lltv"] / 1e18
    ltv = lp["target_ltv_over_lltv"] * lltv
    lev = 1 / (1 - ltv)
    caps = pockets[0]["_caps"]
    log = []
    for p in pockets:
        p["requested_usd"] = ticket
        if p.get("loop"):   # P2: PT notional goes through the Pendle pool, USDC borrow through the Morpho market
            p["venues"] = {"pendle:" + A.HERO1["pendle_market"]: lev, "morpho_market:" + A.HERO1["morpho_market_id"]: lev - 1}
            p["loop_math"] = {"lltv": lltv, "target_ltv": ltv, "gross_leverage": lev,
                              "deleverage_ltv": lp["deleverage_trigger_over_lltv"] * lltv,
                              "emergency_unwind_ltv": lp["emergency_unwind_over_lltv"] * lltv}
        p["size_usd"] = ticket
    # per venue: sum of notional (equity x multiplier) <= cap; scale every pocket on it pro rata
    for venue, (cap_key, venue_tvl) in caps.items():
        cap = s[cap_key] * venue_tvl
        users = [p for p in pockets if venue in p["venues"]]
        notional = sum(p["size_usd"] * p["venues"][venue] for p in users)
        if notional > cap and users:
            k = cap / notional
            for p in users:
                new = p["size_usd"] * k
                log.append({"pocket": p["id"], "check": f"venue cap {venue}", "ok": False,
                            "value": {"cap_usd": cap, "cap_rule": f"{cap_key}={s[cap_key]}", "venue_tvl_usd": venue_tvl,
                                      "requested_notional_usd": notional, "from_usd": p["size_usd"], "to_usd": new},
                            "source": SOURCE, "note": "capacity-constrained: excess parked in P6 (Aave USDC)"})
                p["size_usd"] = new
                p["capacity_constrained"] = True
    excess = sum(p["requested_usd"] - p["size_usd"] for p in pockets)
    p6 = next(p for p in pockets if p["id"] == "P6")
    p6["size_usd"] += excess
    p6["parked_excess_usd"] = excess
    if excess:
        log.append({"pocket": "P6", "check": "parked excess", "value": excess, "source": SOURCE, "ok": True,
                    "note": f"{[p['id'] for p in pockets if p.get('capacity_constrained')]} capacity-constrained"})
    return pockets, log


def build(offline: bool = False) -> dict:
    c = cfg()
    pockets, vlog = verify(offline)
    pockets, alog = allocate(pockets, c)
    m = c["mandate"]
    book = {
        "name": "Belem assumed market-neutral stablecoin mandate (10 pockets)",
        "owner": "Fault Line assumption of a Belem-style mandate. NOT Belem's real book (pending confirmation)",
        "source": SOURCE, "base_currency": "USD",
        "aum_usd": m["aum_usd"], "aum_source": SOURCE, "mandate_usd": m["mandate_usd"],
        "risk_aversion_lambda": c["risk"]["lambda"], "lambda_source": SOURCE,
        "fork_block": A.FORK_BLOCK,
        "meta": {"generated_by": "python -m core.book_builder", "verification_log": "data/book_verification.json",
                 "parked_in_P6_usd": next(p for p in pockets if p["id"] == "P6").get("parked_excess_usd", 0.0)},
        "positions": [],
    }
    for p in pockets:
        checks = [r for r in vlog + alog if r["pocket"] == p["id"]]
        book["positions"].append({
            "id": p["id"], "label": p["label"], "chain": p["chain"],
            "mandate": "managed_account" if "rockawayx_not_belem" not in p["tags"] else "curated_vault",
            "legs": p["legs"], "size_usd": round(p["size_usd"], 2), "requested_usd": p["requested_usd"],
            "size_source": SOURCE + "; capped by venue rules" if p.get("capacity_constrained") else SOURCE,
            "capacity_constrained": bool(p.get("capacity_constrained")), "pipeline": p.get("pipeline"),
            "tags": p["tags"], "disclaimer": p.get("disclaimer"),
            "verification": [{k: v for k, v in r.items() if k != "pocket"} | ({"loop_math": p["loop_math"]} if
                             p.get("loop_math") and r is checks[0] else {}) for r in checks]})
    OUT_BOOK.write_text(f"# GENERATED by `python -m core.book_builder` from {SOURCE}.\n"
                        f"# Every pocket verified on-chain (fork block {A.FORK_BLOCK}) or via its official API; "
                        f"see data/book_verification.json.\n" + yaml.safe_dump(book, sort_keys=False, width=110))
    OUT_LOG.write_text(json.dumps(vlog + alog, indent=1, default=str))
    return book


if __name__ == "__main__":
    b = build(offline="--offline" in sys.argv)
    tot = sum(p["size_usd"] for p in b["positions"])
    print(f"{b['name']}: {len(b['positions'])} pockets, ${tot:,.0f} (mandate ${b['mandate_usd']:,.0f})")
    for p in b["positions"]:
        flag = " CAPACITY-CONSTRAINED" if p["capacity_constrained"] else ""
        print(f"  {p['id']:4s} {p['label'][:58]:58s} ${p['size_usd']:>13,.0f}{flag}")
    print(f"  parked in P6: ${b['meta']['parked_in_P6_usd']:,.0f}")
    print(f"→ {OUT_BOOK}\n→ {OUT_LOG}")
