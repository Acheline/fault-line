"""Graph analytics: depth from the position, layer breakdown, critical nodes, HTML render."""
from __future__ import annotations

from collections import Counter, defaultdict

import networkx as nx

from core.schemas import DependencyGraph, EdgeType, NodeType

PLUMBING = {NodeType.CONTRACT}       # router facets, helpers: real code, not an economic layer


SEMANTIC = {EdgeType.HOLDS, EdgeType.WRAPS, EdgeType.BACKS, EdgeType.ISSUED_BY, EdgeType.USES_COLLATERAL,
            EdgeType.LENDS, EdgeType.PRICES, EdgeType.ALLOCATES_TO}


def to_nx(g: DependencyGraph, contract_delegates: bool = True, edge_types: set | None = None) -> nx.DiGraph:
    G = nx.DiGraph()
    alias = {}
    if contract_delegates:   # proxy+implementation = one logical contract
        for e in g.edges.values():
            if e.type == EdgeType.DELEGATES_TO:
                alias[e.dst] = alias.get(e.src, e.src)
    for nid, n in g.nodes.items():
        if nid not in alias:
            G.add_node(nid, type=n.type.value, label=n.label)
    for e in g.edges.values():
        if edge_types is not None and e.type not in edge_types:
            continue
        s, d = alias.get(e.src, e.src), alias.get(e.dst, e.dst)
        if s != d and s in G and d in G:
            G.add_edge(s, d, type=e.type.value)
    return G


def _deepest(G: nx.DiGraph, g: DependencyGraph, root: str) -> tuple[int, list[str]]:
    paths = nx.single_source_shortest_path(G, root)
    far = max(paths, key=lambda n: len(paths[n]))
    return len(paths[far]) - 1, [f"{g.nodes[x].label} [{g.nodes[x].type.value}]" for x in paths[far]]


def longest_chain(G: nx.DiGraph, g: DependencyGraph, root: str) -> list[str]:
    """Longest dependency chain from root (cycles broken deterministically, latest-found edge dropped)."""
    H = G.subgraph(nx.descendants(G, root) | {root}).copy()
    while True:
        try:
            cyc = nx.find_cycle(H, source=root)
        except nx.NetworkXNoCycle:
            break
        H.remove_edge(*cyc[-1][:2])
    # longest path starting at root: DP over topological order
    best = {root: [root]}
    for n in nx.topological_sort(H):
        if n not in best:
            continue
        for m in H.successors(n):
            if len(best[n]) + 1 > len(best.get(m, [])):
                best[m] = best[n] + [m]
    far = max(best.values(), key=len)
    return [f"{g.nodes[x].label} [{g.nodes[x].type.value}]" for x in far]


def depth_report(g: DependencyGraph) -> dict:
    """economic depth = layers below the position along semantic edges only (holds/wraps/backs/issued_by/
    prices/collateral/lends): the asset & pricing stack, excluding router plumbing and governance.
    governance depth = longest admin chain (contract -> admin -> owner -> ...)."""
    root = f"position:{g.position_id}"
    G_all = to_nx(g)
    dist = nx.single_source_shortest_path_length(G_all, root)
    G_sem = to_nx(g, edge_types=SEMANTIC)
    econ_d, econ_chain = _deepest(G_sem, g, root)
    econ_reach = nx.descendants(G_sem, root)
    stack = longest_chain(G_sem, g, root)
    asset_stack = longest_chain(to_nx(g, edge_types={EdgeType.HOLDS, EdgeType.USES_COLLATERAL, EdgeType.WRAPS,
                                                     EdgeType.BACKS, EdgeType.ISSUED_BY}), g, root)
    pricing_stack = longest_chain(to_nx(g, edge_types={EdgeType.HOLDS, EdgeType.PRICES}), g, root)
    Gg = to_nx(g, edge_types={EdgeType.GOVERNS})
    gov_d, gov_chain = 0, []
    for n in econ_reach & set(Gg.nodes):   # who can change what this position economically depends on
        if Gg.out_degree(n) > 0:
            d, ch = _deepest(Gg, g, n)
            if d > gov_d:
                gov_d, gov_chain = d, ch
    layers = defaultdict(Counter)
    for n, d in nx.single_source_shortest_path_length(G_sem, root).items():
        layers[d][g.nodes[n].type.value] += 1
    return {
        "raw_depth": max(dist.values()),
        "stack_depth": len(stack) - 1,
        "deepest_chain": stack,
        "min_hops_to_farthest": econ_d,
        "asset_stack": asset_stack,
        "pricing_stack": pricing_stack,
        "governance_depth": gov_d,
        "governance_chain": gov_chain,
        "economic_layers": {d: dict(c) for d, c in sorted(layers.items())},
        "unreachable": [n for n in g.nodes if n not in dist],
    }


def critical_nodes(g: DependencyGraph) -> list[dict]:
    out = []
    for n in g.nodes.values():
        if len(n.paths) >= 2 and "implementation" not in n.tags:
            n.tags.add("critical")
            out.append({"id": n.id, "label": n.label, "type": n.type.value,
                        "paths": sorted(p.value for p in n.paths)})
    return sorted(out, key=lambda x: (-len(x["paths"]), x["label"]))



BRIEF_LAYERS = ["1. settlement chain", "2. yield source & issuer", "3. oracle", "4. PT AMM", "5. lending market"]
BEYOND = {"gov": "+ governance: proxy admins, multisigs, timelocks",
          "feeds": "+ feed sources behind the oracle",
          "offchain": "+ custodians & venues (off-chain, disclosed)",
          "exit": "+ exit liquidity: DEX pools, tokens & routers on the executed exit",
          "code": "+ contract code: implementations & libraries"}


def brief_layers(g: DependencyGraph, market_node: str, market_oracle: str) -> dict:
    """Map every node onto the brief's 5-layer Pendle picture, then the layers we found beyond it.
    Writes props['brief_layer'] on each node; returns {layer: [labels]}."""
    G = to_nx(g, contract_delegates=False, edge_types={EdgeType.WRAPS, EdgeType.ISSUED_BY, EdgeType.BACKS,
                                                       EdgeType.PRICES})
    pt = next((e.dst for e in g.edges.values() if e.src == market_node and e.type == EdgeType.USES_COLLATERAL), None)
    yield_stack = nx.descendants(to_nx(g, contract_delegates=False, edge_types={EdgeType.WRAPS, EdgeType.ISSUED_BY,
                                                                              EdgeType.BACKS}), pt) if pt in G else set()
    loan = {e.dst for e in g.edges.values() if e.src == market_node and e.type == EdgeType.LENDS}
    irm = {e.dst for e in g.edges.values() if e.src == market_node and e.props.get("role") in ("irm", "singleton")}
    oracle_ids = {market_oracle}
    out: dict[str, list[str]] = {k: [] for k in BRIEF_LAYERS + list(BEYOND.values())}
    for n in g.nodes.values():
        proto = n.props.get("protocol") or ""
        tags = n.tags
        if n.type == NodeType.POSITION:
            continue
        if n.type == NodeType.CHAIN:
            layer = BRIEF_LAYERS[0]
        elif n.id in oracle_ids:
            layer = BRIEF_LAYERS[2]
        elif n.type == NodeType.ORACLE:
            layer = BEYOND["feeds"]
        elif n.type == NodeType.GOVERNANCE:
            layer = BEYOND["gov"]
        elif n.type == NodeType.OFFCHAIN and tags & {"cex", "custodian"}:
            layer = BEYOND["offchain"]
        elif n.type in (NodeType.ISSUER, NodeType.OFFCHAIN) or n.id in yield_stack and proto != "pendle-v2" \
                or proto == "ethena-usde" and "implementation" not in tags:
            layer = BRIEF_LAYERS[1]
        elif n.type == NodeType.LENDING_MARKET or n.id in loan | irm or "morpho_blue" in tags:
            layer = BRIEF_LAYERS[4]
        elif "implementation" in tags:
            layer = BEYOND["code"]
        elif "router" in n.label.lower() and not tags & {"pendle_market", "pendle_pt", "pendle_sy"}:
            layer = BEYOND["exit"]          # routers (Pendle, aggregators) execute the exit; they are not the PT AMM
        elif proto == "pendle-v2" or tags & {"pendle_market", "pendle_pt", "pendle_sy"}:
            layer = BRIEF_LAYERS[3]
        else:
            layer = BEYOND["exit"]
        n.props["brief_layer"] = layer
        out[layer].append(n.label)
    return {k: sorted(v) for k, v in out.items()}
