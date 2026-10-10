"""M1.8 Oracle feed-quality analysis. For every oracle node: provider, kind (market-derived / exchange-rate /
hardcoded / issuer-reported), independent sources, heartbeat & deviation trigger observed over 30 days of
on-chain events, staleness at the fork block, deviation from executed/DEX/CEX spot, and who can change it."""
from __future__ import annotations

import statistics

import networkx as nx
from eth_utils import keccak

from core.etherscan import get_logs
from core.schemas import EdgeType, NodeType
from discovery.builder import GraphBuilder

ANSWER_UPDATED = "0x" + keccak(text="AnswerUpdated(int256,uint256,uint256)").hex()
BLOCKS_30D = 30 * 7200

MARKET = "market_derived"
EXCHANGE_RATE = "exchange_rate"
HARDCODED_SCHEDULE = "hardcoded_schedule"
HARDCODED_CONSTANT = "hardcoded_constant"
ISSUER_REPORTED = "issuer_reported"
COMPOSITE = "composite"
SWITCH = "switch"
HARDCODED = (HARDCODED_SCHEDULE, HARDCODED_CONSTANT)


def _kind(n) -> tuple[str, str]:
    """(provider, kind) from verified contract name + probed interface."""
    name = (n.props.get("contract_name") or "").lower()
    desc = (n.props.get("description") or "").lower()
    if "fixed_schedule" in n.tags:
        return "Pendle/Spark linear discount", HARDCODED_SCHEDULE
    if "fixed_price" in n.tags:
        return "constant", HARDCODED_CONSTANT
    if "nav" in name or "nav" in desc or "issuer_reported" in n.tags:
        return "issuer", ISSUER_REPORTED
    if "metaoracle" in name:
        return "Morpho MetaOracle (primary/backup)", SWITCH
    if "morphochainlinkoracle" in name:
        return "Morpho (feed composition)", COMPOSITE
    if "pendlepylporacle" in name or "pendlechainlinkoracle" in name:
        return "Pendle AMM TWAP", MARKET
    if "aggregator" in name or "ocr" in name or n.props.get("description"):
        return "Chainlink", MARKET
    if "erc4626" in n.tags or "exchangerate" in name:
        return "vault exchange rate", EXCHANGE_RATE
    return n.props.get("contract_name") or "unknown", "unknown"


def _governance(b: GraphBuilder, nid: str) -> dict:
    """Who can change this oracle: walk governs edges from the node and from any proxy in front of it."""
    g = b.g
    starts = {nid} | {e.src for e in g.edges.values() if e.type == EdgeType.DELEGATES_TO and e.dst == nid}
    G = nx.DiGraph([(e.src, e.dst) for e in g.edges.values() if e.type == EdgeType.GOVERNS])
    chain = set()
    for s in starts:
        if s in G:
            chain |= nx.descendants(G, s)
    if not chain:
        upgradeable = any("proxy" in g.nodes[s].tags for s in starts)
        return {"who": [], "min_timelock_s": None,
                "summary": "upgradeable proxy, admin not resolved" if upgradeable else "immutable (no admin, no proxy)"}
    delays = [g.nodes[c].props.get("min_delay_s") for c in chain if "timelock" in g.nodes[c].tags]
    direct = [c for c in chain if "safe" in g.nodes[c].tags or "eoa" in g.nodes[c].tags]
    # a Safe/EOA governing the oracle directly (no timelock in between) = can change it now
    first_hop = {e.dst for e in g.edges.values() if e.type == EdgeType.GOVERNS and e.src in starts}
    immediate = any("timelock" not in g.nodes[h].tags for h in first_hop)
    return {"who": sorted(g.nodes[c].label for c in chain),
            "min_timelock_s": 0 if immediate else (min(d for d in delays if d is not None) if delays else None),
            "summary": ("changeable with NO timelock by " if immediate else "changeable after timelock by ")
                       + ", ".join(sorted(g.nodes[h].label for h in first_hop))}


def _history(fork, aggregator: str, to_block: int) -> dict:
    logs = get_logs(aggregator, ANSWER_UPDATED, to_block - BLOCKS_30D, to_block)
    if not logs:
        return {"n_updates_30d": 0}
    ts = sorted(int(x["timeStamp"], 16) for x in logs)
    ans = [int(x["topics"][1], 16) for x in sorted(logs, key=lambda x: int(x["timeStamp"], 16))]
    ans = [a - 2**256 if a >= 2**255 else a for a in ans]
    gaps = [b - a for a, b in zip(ts, ts[1:])]
    hb = max(gaps) if gaps else None
    # deviation-triggered updates = those well inside the heartbeat; their move size ~ deviation threshold
    dev_moves = [abs(b - a) / abs(a) for (a, b), gap in zip(zip(ans, ans[1:]), gaps) if hb and gap < 0.9 * hb and a]
    return {"n_updates_30d": len(logs), "heartbeat_s_observed": hb,
            "median_gap_s": statistics.median(gaps) if gaps else None,
            "deviation_trigger_observed_pct": round(100 * min(dev_moves), 4) if dev_moves else None,
            "n_deviation_updates_30d": len(dev_moves),
            "answer_min_30d": min(ans), "answer_max_30d": max(ans), "source": "etherscan AnswerUpdated logs"}


def analyse(b: GraphBuilder, block_ts: int, market_oracle: str, executed_call: str,
            spot_checks: dict[str, list[dict]] | None = None) -> dict:
    """Returns {"oracles": [...], "position_price_path": {...}}; also writes props['feed_quality'] on nodes."""
    g, fork = b.g, b.fork
    spot_checks = spot_checks or {}
    out = []
    oracles = [n for n in g.nodes.values() if n.type == NodeType.ORACLE and "implementation" not in n.tags]
    for n in oracles:
        provider, kind = _kind(n)
        rec = {"id": n.id, "label": n.label, "provider": provider, "kind": kind, "flags": []}
        if "chainlink_interface" in n.tags:
            upd = n.props.get("updated_at") or 0
            rec["staleness_s"] = (block_ts - upd) if upd else None
            agg = next((e.dst for e in g.edges.values() if e.src == n.id and e.props.get("getter") == "aggregator"), None)
            target = agg or (n.id if kind == MARKET else None)
            if target:
                tx = fork.call(target, "getTransmitters()", out_types=["address[]"])
                rec["n_transmitters"] = len(tx[0]) if tx else None
                rec.update(_history(fork, target, g.fork_block))
                hb = rec.get("heartbeat_s_observed")
                if hb and rec["staleness_s"] and rec["staleness_s"] > 1.1 * hb:
                    rec["flags"].append("stale")
        if kind == COMPOSITE:
            prm = n.props.get("params", {})
            comps = [e.dst for e in g.edges.values() if e.src == n.id and e.type == EdgeType.PRICES
                     and (e.props.get("getter") or "").startswith(("BASE_", "QUOTE_"))]
            rec["components"] = sorted(g.nodes[c].label for c in comps)
            ck = [_kind(g.nodes[c])[1] for c in comps]
            rec["n_market_components"] = sum(k == MARKET for k in ck)
            if comps and all(k in HARDCODED for k in ck):
                rec["kind"] = HARDCODED_SCHEDULE if HARDCODED_SCHEDULE in ck else HARDCODED_CONSTANT
                rec["flags"].append("no_market_feed")
            rec["scale_factor"] = prm.get("SCALE_FACTOR")
        if kind == SWITCH:
            prm = n.props.get("params", {})
            rec.update({k: prm.get(k) for k in ("deviationThreshold", "challengeTimelockDuration",
                                                  "healingTimelockDuration", "isPrimary", "getDeviation")})
        if kind in HARDCODED:
            rec["flags"].append("hardcoded")
        if kind == ISSUER_REPORTED:
            rec["flags"].append("issuer_reported: issuer is both the asset and its price")
        rec["who_can_change"] = _governance(b, n.id)
        if rec["who_can_change"]["min_timelock_s"] == 0:
            rec["flags"].append("changeable_without_timelock")
        rec["spot_checks"] = spot_checks.get(n.id, [])
        for s in rec["spot_checks"]:
            if s.get("deviation_pct") is not None and abs(s["deviation_pct"]) > 0.5:
                rec["flags"].append(f"deviates {s['deviation_pct']:+.2f}% vs {s['reference']}")
        n.props["feed_quality"] = rec
        out.append(rec)

    # the price the position is LIQUIDATED on: which market-derived leaf feeds did price() actually execute?
    executed = b.touched.get(executed_call, set())
    leaves = [g.nodes[a] for a in executed if a in g.nodes and g.nodes[a].type == NodeType.ORACLE
              and "implementation" not in g.nodes[a].tags and "chainlink_interface" in g.nodes[a].tags]
    market_leaves = [n for n in leaves if _kind(n)[1] == MARKET]
    pp = {"oracle": market_oracle, "executed_leaf_feeds": sorted(n.label for n in leaves),
          "n_market_derived_sources": len(market_leaves)}
    if len(market_leaves) == 0:
        pp["flag"] = "NO market-derived feed: the asset is priced by a hardcoded schedule/constant"
    elif len(market_leaves) == 1:
        pp["flag"] = f"asset priced by a SINGLE feed: {market_leaves[0].label}"
    return {"oracles": out, "position_price_path": pp}
