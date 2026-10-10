"""M1 / hero #1: PT-sUSDe-26NOV2026 held outright AND posted as Morpho collateral borrowing USDC.

Executes the three critical paths on the anvil fork, traces each with callTracer + prestateTracer,
resolves every touched address, and writes data/graphs/hero1.{json,html}.

    python -m discovery.hero1            # live fork (results cached)
    python -m discovery.hero1 --offline  # replay from cache only
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import requests
from eth_abi import decode, encode

from core import addresses as A
from core.fork import ROOT, DiskCache, Fork, selector
from core.schemas import CriticalPath, Edge, EdgeType, Node, NodeType, Provenance, stable_hash
from discovery import disclosures, oracle_quality, tvl
from discovery.builder import GraphBuilder
from discovery import viz
from discovery.report import brief_layers, critical_nodes, depth_report

H = A.HERO1
HARNESS = "0xfa0171fa0171fa0171fa0171fa0171fa0171fa01"   # our simulated holder / liquidator
OUT = ROOT / "data" / "graphs"
MARKET_NODE = f"morpho_market:{H['morpho_market_id']}"
MP_TYPES = ["(address,address,address,address,uint256)"]


def market_params():
    return (A.USDC, H["pt"], H["morpho_oracle"], H["morpho_irm"], H["lltv"])


def trace_both(fork: Fork, tx: dict, label: str) -> dict:
    tx = {**tx, "gas": hex(30_000_000)}
    return {"label": label, "tx": tx,
            "call": fork.trace_call(tx, "callTracer", label),
            "pre": fork.trace_call(tx, "prestateTracer", label)}


# --------------------------------------------------------------------------- VALUE path
def value_traces(fork: Fork) -> list[tuple[CriticalPath, dict, str | None]]:
    out = []
    calls = [
        ("value:morpho_oracle.price", {"from": A.MORPHO_BLUE, "to": H["morpho_oracle"],
                                       "data": "0x" + selector("price()").hex()}, MARKET_NODE),
        ("value:pendle_twap.getPtToAssetRate(900s)", {"to": A.PENDLE_PY_LP_ORACLE, "data": "0x" + (
            selector("getPtToAssetRate(address,uint32)") + encode(["address", "uint32"], [H["pendle_market"], 900])).hex()}, H["pt"].lower()),
        ("value:sy.exchangeRate", {"to": H["sy"], "data": "0x" + selector("exchangeRate()").hex()}, H["sy"].lower()),
        ("value:susde.convertToAssets", {"to": H["susde"], "data": "0x" + (
            selector("convertToAssets(uint256)") + encode(["uint256"], [10**18])).hex()}, H["susde"].lower()),
        ("value:usde_usd.latestRoundData", {"to": H["usde_usd_feed"], "data": "0x" + selector("latestRoundData()").hex()}, H["usde"].lower()),
    ]
    for label, tx, entry in calls:
        out.append((CriticalPath.VALUE, trace_both(fork, tx, label), entry))
    return out


# --------------------------------------------------------------------------- EXIT path
def pendle_exit_calldata(amount: int) -> dict:
    cache = DiskCache("api")
    params = {"receiver": HARNESS, "slippage": "0.01", "enableAggregator": "true", "tokensIn": H["pt"],
              "amountsIn": str(amount), "tokensOut": A.USDC}
    key = "pendle_convert_" + stable_hash(params)
    hit = cache.get(key)
    if hit:
        return hit
    r = requests.get("https://api-v2.pendle.finance/core/v2/sdk/1/convert", params=params, timeout=60).json()
    route = r["routes"][0]
    return cache.put(key, {"to": route["tx"]["to"], "data": route["tx"]["data"], "outputs": route.get("outputs"),
                           "route": route.get("data"), "params": params})


def exit_trace(fork: Fork) -> tuple[dict, dict]:
    q = pendle_exit_calldata(H["exit_size_pt"])
    with fork.snapshot():
        fork.fund_erc20(H["pt"], HARNESS, H["exit_size_pt"])
        fork.send(HARNESS, H["pt"], selector("approve(address,uint256)") + encode(["address", "uint256"], [q["to"], 2**256 - 1]))
        t = trace_both(fork, {"from": HARNESS, "to": q["to"], "data": q["data"]}, "exit:pendle_router.PT->USDC")
    out = t["call"].get("output") or "0x"
    proceeds = int(out[2:66], 16) if len(out) >= 66 and not t["call"].get("error") else None
    return t, {"size_pt": H["exit_size_pt"] / 1e18, "usdc_out": proceeds / 1e6 if proceeds else None,
               "api_quote_usdc": int(q["outputs"][0]["amount"]) / 1e6 if q.get("outputs") else None,
               "aggregator": (q.get("route") or {}).get("aggregatorType"),
               "error": t["call"].get("error")}


# --------------------------------------------------------------------------- LIQUIDATION path
def position_slot(mid: str, user: str) -> int:
    from eth_utils import keccak
    inner = keccak(encode(["bytes32", "uint256"], [bytes.fromhex(mid[2:]), 2]))
    return int.from_bytes(keccak(encode(["address", "bytes32"], [user, inner])), "big")


def liquidation_trace(fork: Fork) -> tuple[dict, dict]:
    mid, user = H["morpho_market_id"], H["liq_borrower"]
    mid_b = bytes.fromhex(mid[2:])
    with fork.snapshot():
        pos = fork.call(A.MORPHO_BLUE, "position(bytes32,address)", ["bytes32", "address"], [mid_b, user],
                        ["uint256", "uint128", "uint128"])
        mkt = fork.call(A.MORPHO_BLUE, "market(bytes32)", ["bytes32"], [mid_b], ["uint128"] * 6)
        price = fork.call1(H["morpho_oracle"], "price()", "uint256")
        _, bshares, coll = pos
        debt = bshares * (mkt[2] + 1) // (mkt[3] + 10**6)
        hf = coll * price // 10**36 * H["lltv"] / 10**18 / debt
        # synthetic setup: push this REAL borrower to HF 0.99 by trimming recorded collateral in Morpho storage.
        # The oracle is untouched, so the liquidation trace walks the real price path.
        new_coll = int(0.99 * debt * 10**36 * 10**18 / (price * H["lltv"]))
        slot = position_slot(mid, user) + 1
        fork.set_storage(A.MORPHO_BLUE, slot, bshares | (new_coll << 128))
        check = fork.call(A.MORPHO_BLUE, "position(bytes32,address)", ["bytes32", "address"], [mid_b, user],
                          ["uint256", "uint128", "uint128"])
        assert check[2] == new_coll and check[1] == bshares, "Morpho position slot layout mismatch"
        seize = new_coll // 10
        fork.fund_erc20(A.USDC, HARNESS, 50_000_000 * 10**6)
        fork.send(HARNESS, A.USDC, selector("approve(address,uint256)") + encode(["address", "uint256"], [A.MORPHO_BLUE, 2**256 - 1]))
        data = selector(f"liquidate({MP_TYPES[0]},address,uint256,uint256,bytes)") + encode(
            MP_TYPES + ["address", "uint256", "uint256", "bytes"], [market_params(), user, seize, 0, b""])
        t = trace_both(fork, {"from": HARNESS, "to": A.MORPHO_BLUE, "data": "0x" + data.hex()},
                       "liquidation:morpho.liquidate")
    out = t["call"].get("output") or "0x"
    seized, repaid = decode(["uint256", "uint256"], bytes.fromhex(out[2:])) if len(out) >= 130 else (None, None)
    return t, {"borrower": user, "debt_usdc": debt / 1e6, "collateral_pt": coll / 1e18, "hf_on_fork": hf,
               "setup": "collateral trimmed in storage to HF=0.99 (synthetic); oracle untouched",
               "seized_pt": seized / 1e18 if seized else None, "repaid_usdc": repaid / 1e6 if repaid else None,
               "error": t["call"].get("error")}


# --------------------------------------------------------------------------- build
def build(offline: bool = False):
    fork = Fork(offline=offline)
    if fork.offline:
        fork.fork_block = A.FORK_BLOCK
    elif fork.fork_block != A.FORK_BLOCK:
        print(f"⚠️  fork head {fork.fork_block} != pinned {A.FORK_BLOCK}; traces will be keyed to {fork.fork_block}")
    blk = fork.fork_block
    b = GraphBuilder(fork, H["position_id"], "PT-sUSDe-26NOV2026 (outright + Morpho collateral)")
    g = b.g

    # logical nodes read from storage
    mp_prov = Provenance(source="storage", block=blk, detail="Morpho.idToMarketParams(id)")
    g.add_node(Node(id="chain:ethereum", type=NodeType.CHAIN, label="Ethereum"))
    g.add_node(Node(id=MARKET_NODE, type=NodeType.LENDING_MARKET, label="Morpho PT-sUSDe-26NOV/USDC 91.5%",
                    props={"market_id": H["morpho_market_id"], "lltv": H["lltv"] / 1e18}, provenance=[mp_prov]))

    print("▶ tracing VALUE path ...")
    traces = value_traces(fork)
    print("▶ tracing EXIT path (Pendle SDK route, executed on fork) ...")
    ex_t, ex_meta = exit_trace(fork)
    traces.append((CriticalPath.EXIT, ex_t, None))
    print("▶ tracing LIQUIDATION path (real borrower, Morpho.liquidate) ...")
    lq_t, lq_meta = liquidation_trace(fork)
    traces.append((CriticalPath.LIQUIDATION, lq_t, MARKET_NODE))

    # each value call hangs off the asset whose value it determines (not the root): depth = real stack
    for a in (H["pt"], H["sy"], H["susde"], H["usde"]):
        b.ensure(a, mp_prov, CriticalPath.VALUE)
    for path, t, entry in traces:
        b.ingest_trace(t["call"], t["pre"], path, t["label"], entry_src=entry)

    # structural edges from storage reads
    for a in (H["pt"], A.MORPHO_BLUE, H["morpho_oracle"], H["morpho_irm"], A.USDC):
        b.ensure(a, mp_prov)
    root = b.root
    g.add_edge(Edge(src=root, dst=H["pt"].lower(), type=EdgeType.HOLDS, props={"role": "outright"}))
    g.add_edge(Edge(src=root, dst=MARKET_NODE, type=EdgeType.HOLDS, props={"role": "collateral, borrows USDC"}))
    g.add_edge(Edge(src=root, dst="chain:ethereum", type=EdgeType.REFERENCES, props={"role": "settlement"}))
    g.add_edge(Edge(src=MARKET_NODE, dst=A.MORPHO_BLUE.lower(), type=EdgeType.REFERENCES, props={"role": "singleton"}, provenance=[mp_prov]))
    g.add_edge(Edge(src=MARKET_NODE, dst=H["morpho_oracle"].lower(), type=EdgeType.PRICES, provenance=[mp_prov]))
    g.add_edge(Edge(src=MARKET_NODE, dst=H["morpho_irm"].lower(), type=EdgeType.REFERENCES, props={"role": "irm"}, provenance=[mp_prov]))
    g.add_edge(Edge(src=MARKET_NODE, dst=H["pt"].lower(), type=EdgeType.USES_COLLATERAL, provenance=[mp_prov]))
    g.add_edge(Edge(src=MARKET_NODE, dst=A.USDC.lower(), type=EdgeType.LENDS, provenance=[mp_prov]))
    g.nodes[MARKET_NODE].paths |= {CriticalPath.VALUE, CriticalPath.LIQUIDATION}

    print("▶ resolving proxies / admins / owners / stored addresses ...")
    b.resolve({CriticalPath.VALUE: 2, CriticalPath.LIQUIDATION: 2, CriticalPath.EXIT: 1})
    disclosures.apply(g)        # registry keyed by asset address: attaches to whatever discovery found

    findings = analyse(b)
    oq = oracle_quality.analyse(b, fork.block_timestamp(), H["morpho_oracle"].lower(), "value:morpho_oracle.price",
                                spot_checks(b, ex_meta))
    if oq["position_price_path"].get("flag"):
        findings.append({"kind": "single_feed", "node": H["morpho_oracle"].lower(), "label": "Morpho collateral price",
                         "why": oq["position_price_path"]["flag"]})
    conc = tvl.concentration(g, "ethereum", offline=fork.offline)
    for r in conc:
        if r["flag"]:
            findings.append({"kind": "tvl_concentration", "node": r["protocol"], "label": r["name"],
                             "why": f"{r['share_of_chain']:.1%} of Ethereum DeFi TVL (${r['tvl_usd'] / 1e9:.2f}B): "
                                    "its failure is a chain-level liquidity event for every position here"})
    rep = depth_report(g)
    crit = critical_nodes(g)
    layers = brief_layers(g, MARKET_NODE, H["morpho_oracle"].lower())
    g.meta = {"exit": ex_meta, "liquidation": lq_meta, "depth": rep, "brief_layers": layers,
              "critical_nodes": crit, "findings": findings, "oracle_quality": oq, "tvl_concentration": conc,
              "n_nodes": len(g.nodes), "n_edges": len(g.edges)}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "hero1.json").write_text(g.to_json())
    viz.export(OUT / "hero1.json", ROOT / "output" / "hero1_graph.html")
    return g


def spot_checks(b: GraphBuilder, ex_meta: dict) -> dict[str, list[dict]]:
    """Deviation of each oracle on the price path vs an executed / market reference at the fork block.
    Oracles are found by what discovery tagged them (fixed_schedule, fixed_price), not by address."""
    fork, g = b.fork, b.g
    RD = ["uint80", "int256", "uint256", "uint256", "uint80"]

    def dev(o, r):
        return None if (o is None or not r) else round(100 * (o / r - 1), 4)

    def chk(ref, ref_v, orc_v, src):
        return {"reference": ref, "ref_value": ref_v, "oracle_value": orc_v, "deviation_pct": dev(orc_v, ref_v),
                "source": src}

    twap = fork.call1(A.PENDLE_PY_LP_ORACLE, "getPtToAssetRate(address,uint32)", "uint256",
                      ["address", "uint32"], [H["pendle_market"], 900])
    twap = twap / 1e18 if twap else None
    usde_rd = fork.call(H["usde_usd_feed"], "latestRoundData()", out_types=RD)
    usdc_rd = fork.call(A.CHAINLINK_USDC_USD, "latestRoundData()", out_types=RD)
    curve = fork.call1(A.CURVE_USDE_USDC, "get_dy(int128,int128,uint256)", "uint256",
                       ["int128", "int128", "uint256"], [0, 1, 1000 * 10**18])
    morpho_px = fork.call1(H["morpho_oracle"], "price()", "uint256")
    usde = usde_rd[1] / 1e8 if usde_rd else None
    curve_px = curve / 1e9 if curve else None              # USDC (1e6) per 1000 USDe
    exec_px = ex_meta["usdc_out"] / ex_meta["size_pt"] if ex_meta.get("usdc_out") else None
    morpho = morpho_px / 1e24 if morpho_px else None        # USDC per PT (Morpho scale 1e36 * 1e6/1e18)
    out = {
        H["morpho_oracle"].lower(): [
            chk(f"executed exit PT->USDC on fork ({ex_meta['size_pt']:,.0f} PT)", exec_px, morpho, "trace"),
            chk("Pendle 15m TWAP x Chainlink USDe/USD", twap * usde if twap and usde else None, morpho, "onchain_read")],
        H["usde_usd_feed"].lower(): [chk("Curve USDe/USDC get_dy(1k USDe)", curve_px, usde, "onchain_read")],
    }
    for n in g.nodes.values():
        if "fixed_schedule" in n.tags and n.props.get("answer"):
            out[n.id] = [chk("Pendle 15m TWAP PT->USDe", twap, n.props["answer"] / 1e18, "onchain_read")]
        if "fixed_price" in n.tags and usdc_rd:
            out[n.id] = [chk("Chainlink USDC/USD", usdc_rd[1] / 1e8, 1.0, "onchain_read")]
    return out


def analyse(b: GraphBuilder) -> list[dict]:
    """Automatic flags, each derived from an executed trace or an on-chain read."""
    g, out = b.g, []
    oracles = [n for n in g.nodes.values() if n.type == NodeType.ORACLE]
    for n in oracles:
        b.read_params(n.id)
        slots = sum(n.props.get("storage_slots_read", {}).values())
        if CriticalPath.VALUE in n.paths and "chainlink_interface" in n.tags and slots == 0 \
                and n.props.get("updated_at") == 0:
            n.tags.add("fixed_schedule")
        if "fixed_schedule" in n.tags:
            prm = n.props["params"]
            out.append({"kind": "fixed_schedule_oracle", "node": n.id, "label": n.label,
                        "why": f"price = f(immutables, block.timestamp): {slots} storage slots read, updatedAt=0, "
                               f"discount {prm.get('baseDiscountPerYear', 0) / 1e16:.1f}%/yr to maturity {prm.get('maturity')}. "
                               "Not market-derived: cannot see a PT or USDe dislocation."})
        if "fixed_price" in n.tags:
            out.append({"kind": "fixed_price_feed", "node": n.id, "label": n.label,
                        "why": f"constant answer {n.props.get('answer')}: the quote asset (USDC) is assumed at par"})
    # Meta-oracle switch (primary -> backup) and its timelock = time-to-impact of a deviation
    for n in oracles:
        prm = n.props.get("params", {})
        if "deviationThreshold" in prm and "challengeTimelockDuration" in prm:
            out.append({"kind": "oracle_switch_timelock", "node": n.id, "label": n.label,
                        "why": f"switches primary->backup only after deviation > {prm['deviationThreshold'] / 1e16:.2f}% "
                               f"is challenged and {prm['challengeTimelockDuration'] / 3600:.0f}h pass "
                               f"(healing {prm.get('healingTimelockDuration', 0) / 3600:.0f}h); "
                               f"now: deviation {prm.get('getDeviation', 0) / 1e16:.3f}%, isPrimary={prm.get('isPrimary')}",
                        "params": {k: prm.get(k) for k in ("deviationThreshold", "challengeTimelockDuration",
                                                             "healingTimelockDuration", "getDeviation", "isPrimary")}})
    # executed blind spots: what the Morpho oracle.price() call actually touched
    executed = b.touched["value:morpho_oracle.price"]
    backup_reach = set()
    for e in g.edges.values():
        if e.src == H["morpho_oracle"].lower() and e.props.get("getter") == "backupOracle":
            import networkx as nx
            from discovery.report import to_nx
            backup_reach = nx.descendants(to_nx(g, contract_delegates=False, edge_types={EdgeType.PRICES}), e.dst) | {e.dst}
    for name, addr in (("Pendle AMM / TWAP", H["pendle_market"]), ("USDe/USD Chainlink feed", H["usde_usd_feed"]),
                       ("sUSDe exchange rate", H["susde"]), ("SY exchange rate", H["sy"])):
        if addr.lower() not in executed:
            via_backup = addr.lower() in backup_reach
            out.append({"kind": "oracle_blind_spot", "node": H["morpho_oracle"].lower(), "label": name,
                        "why": f"Morpho collateral oracle.price() does NOT execute {name}"
                               + (" (only the BACKUP oracle reads it, after the switch timelock)" if via_backup else "")
                               + ": a move there triggers no liquidation here until then; losses surface as bad debt."})
    return out


def print_summary(g):
    m = g.meta
    print(f"\n=== {g.position_id} @ block {g.fork_block}: {m['n_nodes']} nodes, {m['n_edges']} edges ===")
    by_type = {}
    for n in g.nodes.values():
        by_type.setdefault(n.type.value, []).append(n.label)
    for t, ls in sorted(by_type.items()):
        print(f"  {t:16s} {len(ls):3d}  {', '.join(sorted(ls)[:8])}{' …' if len(ls) > 8 else ''}")
    d = m["depth"]
    print(f"\nDepth: stack {d['stack_depth']} layers below the position (brief's example: 5), "
          f"governance chain {d['governance_depth']}, raw call depth {d['raw_depth']}")
    print("Deepest dependency chain (semantic edges):\n   " + "\n → ".join(d["deepest_chain"]))
    print(f"Asset stack ({len(d['asset_stack'])-1} layers):\n   " + "\n → ".join(d["asset_stack"]))
    print(f"Pricing stack ({len(d['pricing_stack'])-1} layers):\n   " + "\n → ".join(d["pricing_stack"]))
    print("Deepest governance chain:\n   " + "\n → ".join(d["governance_chain"]))
    print("Economic layers:", d["economic_layers"])
    print("\nBrief's 5-layer picture -> what Fault Line found:")
    for layer, labels in m["brief_layers"].items():
        print(f"  {layer:55s} {len(labels):3d}  {', '.join(labels[:5])}{' …' if len(labels) > 5 else ''}")
    print("\nOracle feed quality:")
    for o in m["oracle_quality"]["oracles"]:
        hist = (f"{o.get('n_updates_30d')} upd/30d, heartbeat~{(o.get('heartbeat_s_observed') or 0) / 3600:.0f}h, "
                f"stale {(o.get('staleness_s') or 0) / 3600:.1f}h, {o.get('n_transmitters')} transmitters"
                if o.get("n_updates_30d") else "no update events (computed on read)")
        print(f"  {o['label'][:44]:44s} {o['kind']:19s} {hist}")
        print(f"  {'':44s} who can change: {o['who_can_change']['summary'][:90]}")
        for c in o["spot_checks"]:
            print(f"  {'':44s} vs {c['reference']}: {c['deviation_pct']:+.3f}%" if c["deviation_pct"] is not None else "")
        if o["flags"]:
            print(f"  {'':44s} FLAGS: {o['flags']}")
    print("  Position price path:", m["oracle_quality"]["position_price_path"])
    print("\nTVL concentration (DefiLlama, share of Ethereum DeFi TVL):")
    for r in m["tvl_concentration"]:
        print(f"  {r['name']:28s} {r['share_of_chain']:6.2%}  ${r['tvl_usd'] / 1e9:6.2f}B  {'FLAG' if r['flag'] else ''}")
    print("\nCritical nodes (on ≥2 critical paths):")
    for c in m["critical_nodes"][:15]:
        print(f"  {c['label']:45s} {c['type']:16s} {c['paths']}")
    print("\nExit:", json.dumps(m["exit"]))
    print("Liquidation:", json.dumps(m["liquidation"]))
    print("\nFindings:")
    for f in m["findings"]:
        print(f"  [{f['kind']}] {f['label']}: {f['why']}")
    gov = [n for n in g.nodes.values() if n.type == NodeType.GOVERNANCE and "eoa" not in n.tags]
    print("\nGovernance (contracts):")
    for n in gov:
        gov_of = sorted({g.nodes[e.src].label for e in g.edges.values() if e.dst == n.id and e.type == EdgeType.GOVERNS})
        print(f"  {n.label:40s} governs {gov_of[:6]}")


if __name__ == "__main__":
    graph = build(offline="--offline" in sys.argv)
    print_summary(graph)
    print(f"\n→ {OUT/'hero1.json'}\n→ {ROOT/'output'/'hero1_graph.html'}")
