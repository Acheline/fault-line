"""Hero #3 (light): a vault that routes capital into a perp exchange. Ethena sUSDe: deposits become USDe, whose
backing is hedged with short perps on CEXs. The exchange is ONE OFFCHAIN node: Binance, Ethena's largest venue by
collateral (Ethena public API).

On-chain: a handful of reads (sUSDe asset, owner, cooldown, rate), cached. No new fork runs.
Shocks, MODELLED, NOT EXECUTED ON FORK (parametric, through the shared engine):
  venue_halt   Binance freezes withdrawals: its share of backing is stuck; no value loss modelled; the exit can only
               use the DEX (the unstake route still works on-chain but USDe must then be sold into a stressed market).
  venue_loss   Binance loses assets: haircut on Ethena's collateral there, after the reserve fund. Haircut sizes and
               frequency from CEX incidents in the DefiLlama hacks dataset (venues > $1B TVL, 3 years; largest: Bybit,
               Feb 2025).
Exit cost: the $5M sUSDe -> USDC exit EXECUTED on the fork earlier (pocket P3, block 26162857); unstake-then-sell is a
quote only (not executed). Other sizes: not executed.

    python -m decision.hero3   -> data/shocks/hero3.json, data/graphs/hero3.json   (seconds, from caches)
"""
from __future__ import annotations

import collections
import json
import time

from core import addresses as A
from core.config import cfg
from core.fork import ROOT, DiskCache, Fork
from core.schemas import DependencyGraph, Edge, EdgeType, Node, NodeType, Provenance
from risk import base_rates as BR
from risk.engine import DecisionInputs, Driver, Scenario, Surface, decide, monte_carlo

OUT = ROOT / "data" / "shocks" / "hero3.json"
GRAPH = ROOT / "data" / "graphs" / "hero3.json"
API = DiskCache("api")
SUSDE, USDE = A.HERO1["susde"].lower(), A.HERO1["usde"].lower()
ETHENA = "https://ethena.fi/api"
VENUE = "Binance"
LABEL = "modelled, not executed on fork"


def ethena() -> dict:
    col = API.get("ethena_collateral")["data"]["collateral"]
    by = collections.Counter()
    for x in col:
        by[x["exchange"]] += x["usdAmount"] or 0
    tot = sum(by.values())
    rf = API.get("ethena_reserve_fund")["data"]["queryIndex"][0]["yields"]
    y = API.get("ethena_yields")["data"]
    return {"backing_usd": tot, "by_venue": dict(by.most_common()), "venue_usd": by[VENUE],
            "venue_share": by[VENUE] / tot if tot else 0, "unallocated_share": by.get("Unallocated", 0) / tot if tot else 0,
            "reserve_fund_usd": rf[-1]["value"], "reserve_buffer": rf[-1]["value"] / tot if tot else 0,
            "susde_apy_30d": (y.get("avg30dSusdeYield") or {}).get("value", 0) / 100, "source": ETHENA}


def cex_incidents(min_tvl: float = 1e9) -> dict:
    protos = {str(p["id"]): p for p in BR.protocols(True)}
    now, W = time.time(), BR.WINDOW_YEARS * BR.YEAR
    big = [p for p in protos.values() if p.get("category") == "CEX" and (p.get("tvl") or 0) >= min_tvl]
    yrs = sum(min(W, now - (p.get("listedAt") or now - W)) / BR.YEAR for p in big)
    hk = [h for h in BR.hacks(True)["data"] if h.get("date", 0) >= now - W and str(h.get("defillamaId")) in protos
          and protos[str(h["defillamaId"])] in big]
    loss = sorted(({"name": h["name"], "date": time.strftime("%Y-%m-%d", time.gmtime(h["date"])), "usd": h["amount"],
                    "share": min(1.0, h["amount"] / protos[str(h["defillamaId"])]["tvl"])} for h in hk),
                  key=lambda x: -x["usd"])
    return {"venue_years": yrs, "incidents": loss, "annual_rate": (len(loss) + 0.5) / yrs if yrs else None,
            "note": "loss share = amount / the venue's CURRENT TVL (DefiLlama): proxy for its assets at the time"}


def onchain() -> dict:
    """A handful of reads, keyed to the pinned block (cached after the first run)."""
    f = Fork()
    f.fork_block = A.FORK_BLOCK
    c = f.call1
    return {"block": A.FORK_BLOCK, "asset": c(SUSDE, "asset()", "address"), "owner": c(SUSDE, "owner()", "address"),
            "cooldown_s": c(SUSDE, "cooldownDuration()", "uint24"),
            "rate": (c(SUSDE, "convertToAssets(uint256)", "uint256", ["uint256"], [10**18]) or 0) / 1e18,
            "total_assets_usde": (c(SUSDE, "totalAssets()", "uint256") or 0) / 1e18}


def exit_points(size: float) -> dict:
    p3 = json.loads((ROOT / "data" / "graphs" / "pockets" / "P3.json").read_text())["meta"]["exit"]
    dex = {"size_usd": p3["size_usd"], "usdc": p3["usdc_out"], "cost": 1 - p3["usdc_out"] / p3["size_usd"],
           "status": "executed on the fork (pocket P3, block %d)" % A.FORK_BLOCK}
    q = API.get(f"kyber_{USDE}_{int(size * 1e18)}_b{A.FORK_BLOCK}_xuniswap-v4,u")
    qu = (q or {}).get("data") or {}
    uns = {"size_usd": size, "usdc": qu.get("amount_out", 0) / 1e6 if qu else None,
           "cost": 1 - qu["amount_out"] / 1e6 / size if qu else None, "status": "quote only / not executed"}
    # cross-check, no fork: live aggregator quotes at the same $ size and at ~$1.25M (cached API responses)
    from discovery.pockets import kyber_exit
    rate = 1.2523672664500605   # sUSDe.convertToAssets(1e18) at the pinned block (onchain())
    chk = {}
    for usd in (size, 1_252_367.0):
        q = kyber_exit(SUSDE, int(usd / rate * 1e18), False)
        chk[f"{usd / 1e6:.2f}M"] = 1 - q["amount_out"] / 1e6 / usd if q else None
    dex["live_quote_check"] = {"cost_by_size": chk, "source": "KyberSwap API quote, not executed",
                               "verdict": "not a fork artifact: the live quote is as costly at $5M; sUSDe trades at par "
                                          "up to ~$1.25M, then hits a depth wall"}
    return {"dex_now": dex, "unstake_then_sell": uns, "other_sizes": "not executed"}


def graph(et: dict, oc: dict) -> DependencyGraph:
    g = DependencyGraph(position_id="hero3_susde_perp_venue", fork_block=A.FORK_BLOCK)
    rd = lambda d: Provenance(source="onchain_read", block=A.FORK_BLOCK, detail=d)            # noqa: E731
    api = Provenance(source="api", url=f"{ETHENA}/positions/current/collateral", confidence=0.9)
    dis = Provenance(source="disclosure", url="https://docs.ethena.fi", confidence=0.7)
    nodes = [
        Node(id="position:hero3_susde_perp_venue", type=NodeType.POSITION, label="sUSDe deposit (Ethena)"),
        Node(id="chain:ethereum", type=NodeType.CHAIN, label="Ethereum"),
        Node(id=SUSDE, type=NodeType.VAULT, label=f"sUSDe (ERC-4626, cooldown {oc['cooldown_s'] / 3600:.0f} h)",
             address=SUSDE, provenance=[rd("asset(), cooldownDuration()")]),
        Node(id=USDE, type=NodeType.ASSET, label="USDe", address=USDE, provenance=[rd("sUSDe.asset()")]),
        Node(id=(oc["owner"] or "owner").lower(), type=NodeType.GOVERNANCE, label="sUSDe owner", provenance=[rd("owner()")]),
        Node(id="issuer:ethena", type=NodeType.ISSUER, label="Ethena Labs (USDe issuer)", provenance=[dis]),
        Node(id="offchain:ethena_hedge", type=NodeType.OFFCHAIN, label="Delta hedge: short perps", tags={"offchain_disclosed"},
             provenance=[dis]),
        Node(id="offchain:ethena_reserve_fund", type=NodeType.OFFCHAIN,
             label=f"Reserve fund ${et['reserve_fund_usd'] / 1e6:.0f}M", provenance=[api]),
        Node(id="offchain:venue_binance", type=NodeType.OFFCHAIN, tags={"venue", "perp", "cex"},
             label=f"Binance perps ({et['venue_share']:.1%} of backing, ${et['venue_usd'] / 1e6:.0f}M)",
             props={"by_venue": et["by_venue"], "shocks": LABEL}, provenance=[api]),
    ]
    for n in nodes:
        g.add_node(n)
    for s, d, t in [("position:hero3_susde_perp_venue", SUSDE, EdgeType.HOLDS),
                    ("position:hero3_susde_perp_venue", "chain:ethereum", EdgeType.REFERENCES),
                    (SUSDE, USDE, EdgeType.WRAPS), (SUSDE, (oc["owner"] or "owner").lower(), EdgeType.GOVERNS),
                    (USDE, "issuer:ethena", EdgeType.ISSUED_BY), (USDE, "offchain:ethena_hedge", EdgeType.BACKS),
                    ("offchain:ethena_hedge", "offchain:venue_binance", EdgeType.BACKS),
                    (USDE, "offchain:ethena_reserve_fund", EdgeType.BACKS)]:
        g.add_edge(Edge(src=s, dst=d, type=t))
    return g


def run() -> dict:
    size = cfg()["sizing"]["ticket_usd"]
    et, oc = ethena(), onchain()
    out = {"size_usd": size, "ethena": et, "cex": cex_incidents(), "onchain": oc, "exit": exit_points(size),
           "label": LABEL, "generated_at": int(time.time())}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=1, default=str))
    GRAPH.write_text(graph(et, oc).to_json())
    return out


def build(d: dict):
    et, cx = d["ethena"], d["cex"]
    w, buf = et["venue_share"], et["reserve_buffer"]
    D = {"venue_loss": Driver("venue_loss", f"{VENUE} loses assets", cx["annual_rate"],
                              [x["share"] for x in cx["incidents"]] or [0.0], "security_incident", "counterparty_defaults",
                              f"CEX incidents on venues > $1B TVL (DefiLlama hacks): {len(cx['incidents'])} in "
                              f"{cx['venue_years']:.1f} venue-years"),
         "venue_halt": Driver("venue_halt", f"{VENUE} freezes withdrawals", cx["annual_rate"], [1.0], "technical_failure",
                              "counterparty_defaults", "proxy: same venue-incident rate", badge="proxy")}
    sc = [Scenario("venue_loss", f"{VENUE} haircut on {w:.1%} of backing, after the reserve fund ({LABEL})", "venue_loss",
                   Surface([(s, max(0.0, w * s - buf)) for s in (0, .05, .1, .25, .5, .75, 1.0)], measured_on="parametric"),
                   0, "medium", VENUE),
          Scenario("venue_halt", f"{VENUE} freezes withdrawals: exit only via DEX ({LABEL})", "venue_halt",
                   Surface([(1.0, 0.0)], measured_on="parametric"), 0, "medium", VENUE)]
    return D, sc


def headline(lam: float | None = None, horizon_days: float = 30, halted: bool = False,
             overrides: dict | None = None) -> dict:
    d = json.loads(OUT.read_text())
    c = cfg(overrides)            # overrides: Assumptions-page slider values
    lam = c["risk"]["lambda"] if lam is None else lam
    D, sc = build(d)
    size, book = d["size_usd"], c["mandate"]["mandate_usd"]
    ex, oc = d["exit"], d["onchain"]
    carry = d["ethena"]["susde_apy_30d"] * horizon_days / 365.25

    def exit_cost(x, t):          # measured at 1x only: smaller exits use the same rate (labelled), larger not executed
        if x == 0:
            return 0.0, 0.0
        route = ex["unstake_then_sell"] if (t >= (oc["cooldown_s"] or 0) and not halted
                                             and ex["unstake_then_sell"]["cost"] is not None) else ex["dex_now"]
        return route["cost"] * x * size, x * size
    mc = monte_carlo(D, sc, horizon_days, 0.3)
    dec = decide(DecisionInputs(size, book, lam, mc.el, mc.cvar95, mc.var95, horizon_days, exit_cost,
                                c["risk"]["pocket_var95_hard_limit"], carry_per_usd=carry))
    full = next(g for g in dec["grid"] if g["t_s"] == 0 and g["x"] == 1.0)
    w, buf, et = d["ethena"]["venue_share"], d["ethena"]["reserve_buffer"], d["ethena"]
    top = d["cex"]["incidents"][0] if d["cex"]["incidents"] else {}
    return {"scope": "hero3", "size_usd": size, "action": dec["action"], "net_value_exit_now_usd": dec["net_value_exit_now_usd"],
            "net_value_exit_now_bps_book": dec["bps_of_book"], "bps_basis": f"assumed mandate ${book / 1e6:,.0f}M",
            "loss_usd": {"E[L]": mc.el * size, "CVaR95": mc.cvar95 * size},
            "components_full_exit_now": {k: full[k] for k in ("loss_avoided_usd", "yield_forgone_usd", "exit_cost_usd", "net_usd")},
            "haircut_breakeven": buf / w if w else None, "ethena": et, "cex": d["cex"], "exit": ex, "onchain": oc,
            "label": LABEL,
            "reason": [f"Path: sUSDe → USDe → Ethena delta hedge → {VENUE} perps ({w:.1%} of ${et['backing_usd'] / 1e9:.2f}B "
                       f"backing; {et['unallocated_share']:.0%} unallocated).",
                       f"A {VENUE} loss reaches sUSDe holders only above a {buf / w:.1%} haircut (reserve fund "
                       f"${et['reserve_fund_usd'] / 1e6:.0f}M); largest CEX incident in the data: {top.get('name')} "
                       f"{top.get('share', 0):.1%} ({top.get('date')}).",
                       f"Exit: ${ex['dex_now']['size_usd'] / 1e6:.0f}M on DEX costs {ex['dex_now']['cost']:.1%} (executed); "
                       f"unstake waits {oc['cooldown_s'] / 3600:.0f} h then costs "
                       + (f"{ex['unstake_then_sell']['cost']:.2%} (quote only)" if ex['unstake_then_sell']['cost'] is not None
                          else "n/a (not executed)") + (" — frozen venue: DEX only" if halted else "") + "."]}


if __name__ == "__main__":
    o = run()
    print(json.dumps({k: o["ethena"][k] for k in ("backing_usd", "venue_share", "reserve_buffer", "susde_apy_30d")}),
          "| onchain", o["onchain"], "| exit", o["exit"])
    for lam in (0.0, 0.5, 1.0):
        h = headline(lam)
        print(f"λ={lam}: {h['action']} net ${h['net_value_exit_now_usd']:,.0f} ({h['net_value_exit_now_bps_book']:+.2f} bps) "
              f"E[L] ${h['loss_usd']['E[L]']:,.0f} CVaR ${h['loss_usd']['CVaR95']:,.0f}")
    for r in headline()["reason"]:
        print(" -", r)
