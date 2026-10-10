"""Module 4: Portfolio X-ray. Merge per-pocket graphs and find SHARED ANCESTORS: nodes several pockets depend on.

Nothing about which pockets share what is configured: pocket graphs are merged by node identity (on-chain address
or registry id), and a node is a shared ancestor iff it is reachable from several pocket roots in their OWN graphs.

    python -m discovery.xray [--offline]     -> data/xray.json

Outputs:
  - shared ancestors: node -> pockets reaching it, share of the book, and how each pocket reaches it (edge sources)
  - worst single point of failure (excluding the book's numeraire, reported separately)
  - "bets": pockets clustered by shared risk-defining ancestors (issuer, off-chain backing, oracle, lending market,
    vault); effective number of independent bets = 1 / sum(bet weight^2)
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict

import networkx as nx

from core.book import Book, load_book
from core.fork import ROOT
from core.schemas import DependencyGraph, EdgeType, NodeType

OUT = ROOT / "data" / "xray.json"
RISK_DEFINING = {NodeType.ISSUER, NodeType.OFFCHAIN, NodeType.ORACLE, NodeType.LENDING_MARKET, NodeType.VAULT}
REPORTABLE = RISK_DEFINING | {NodeType.ASSET, NodeType.GOVERNANCE, NodeType.CHAIN, NodeType.LIQUIDITY_VENUE}
NUMERAIRE_IDS = {"issuer:circle", "offchain:usdc_reserves"}       # the book's unit of account: book-wide, not a "bet"


DEPENDENCY_EDGES = {EdgeType.HOLDS, EdgeType.WRAPS, EdgeType.BACKS, EdgeType.ISSUED_BY, EdgeType.PRICES,
                    EdgeType.USES_COLLATERAL, EdgeType.LENDS, EdgeType.ALLOCATES_TO, EdgeType.GOVERNS,
                    EdgeType.DELEGATES_TO}


def _is_dependency(e) -> bool:
    """What the pocket's VALUE rests on. Exit/liquidation routes are reported separately (route choice, not
    dependency); getter references only when they carry a structural role (Morpho singleton, IRM, settlement)."""
    if e.type in DEPENDENCY_EDGES:
        return True
    return e.type == EdgeType.REFERENCES and bool(e.props.get("role"))


def _reach(g: DependencyGraph, mode: str = "dependency") -> dict[str, list[str]]:
    """node -> shortest path from the pocket root in the pocket's own graph.
    mode: dependency (value rests on it) | exit (reached by the executed exit route)."""
    root = f"position:{g.position_id}"
    if mode == "dependency":
        es = [e for e in g.edges.values() if _is_dependency(e)]
    else:
        es = [e for e in g.edges.values() if e.type in (EdgeType.EXIT_ROUTE, EdgeType.DELEGATES_TO, EdgeType.HOLDS)]
    G = nx.DiGraph([(e.src, e.dst) for e in es])
    return nx.single_source_shortest_path(G, root) if root in G else {}


def numeraire(graphs: dict[str, DependencyGraph]) -> set[str]:
    """USDC token nodes (any chain) + Circle: identified by the issued_by edge to issuer:circle."""
    ids = set(NUMERAIRE_IDS)
    for g in graphs.values():
        ids |= {e.src for e in g.edges.values() if e.type == EdgeType.ISSUED_BY and e.dst == "issuer:circle"}
    # constant feeds hardcoding USDC = $1 (e.g. Morpho "DummyFeed") encode the numeraire, not an independent risk
    for g in graphs.values():
        ids |= {n.id for n in g.nodes.values() if "fixed_price" in n.tags}
    # whoever governs the numeraire (USDC proxy admin, MasterMinter, its owners) is numeraire risk too
    for g in graphs.values():
        G = nx.DiGraph([(e.src, e.dst) for e in g.edges.values() if e.type in (EdgeType.GOVERNS, EdgeType.DELEGATES_TO)])
        for u in list(ids):
            if u in G:
                ids |= nx.descendants(G, u)
    return ids


def xray(book: Book, graphs: dict[str, DependencyGraph]) -> dict:
    total = sum(p.size_usd or 0 for p in book.positions)
    w = {p.id: (p.size_usd or 0) / total for p in book.positions if p.id in graphs}
    nodes, reached = {}, defaultdict(dict)                   # node -> {pocket: path}
    for pid, g in graphs.items():
        for nid, path in _reach(g).items():
            if nid.startswith("position:"):
                continue
            reached[nid][pid] = path
            nodes.setdefault(nid, g.nodes[nid])
    num = numeraire(graphs)

    def how(pid, path):
        g = graphs[pid]
        hops = []
        for a, b_ in zip(path, path[1:]):
            es = [e for e in g.edges.values() if e.src == a and e.dst == b_]
            hops.append({"to": g.nodes[b_].label, "edge": es[0].type.value if es else "?",
                         "sources": sorted({p.source for e in es for p in e.provenance}) or ["structural"]})
        return hops

    shared = []
    for nid, pk in reached.items():
        n = nodes[nid]
        if len(pk) < 2 or n.type not in REPORTABLE or "implementation" in n.tags:
            continue
        shared.append({"id": nid, "label": n.label, "type": n.type.value, "pockets": sorted(pk),
                       "book_share": sum(w[p] for p in pk), "numeraire": nid in num,
                       "how": {p: how(p, path) for p, path in pk.items()}})
    shared.sort(key=lambda s: (-s["book_share"], s["type"], s["label"]))

    # bets: union pockets sharing a risk-defining, non-numeraire ancestor
    parent = {p: p for p in w}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    links = []
    for s in shared:
        if s["numeraire"] or NodeType(s["type"]) not in RISK_DEFINING:
            continue
        ps = s["pockets"]
        for p in ps[1:]:
            parent[find(p)] = find(ps[0])
        links.append(s)
    bets = defaultdict(list)
    for p in w:
        bets[find(p)].append(p)
    bet_list = []
    for members in bets.values():
        ws = sum(w[m] for m in members)
        why = [s["label"] for s in links if set(s["pockets"]) <= set(members)][:5]
        bet_list.append({"pockets": sorted(members, key=lambda x: int(x[1:]) if x[1:].isdigit() else x),
                         "weight": ws, "shared_ancestors": why})
    bet_list.sort(key=lambda b: -b["weight"])
    n_eff = 1 / sum(b["weight"] ** 2 for b in bet_list) if bet_list else 0

    # shared exit liquidity: pools / venues several pockets' executed exits go through (exit race, Module 3)
    ex_reach = defaultdict(set)
    for pid, g in graphs.items():
        for nid in _reach(g, "exit"):
            if nid in g.nodes and g.nodes[nid].type == NodeType.LIQUIDITY_VENUE:
                ex_reach[nid].add(pid)
                nodes.setdefault(nid, g.nodes[nid])
    shared_exit = sorted(({"id": k, "label": nodes[k].label, "pockets": sorted(v), "book_share": sum(w[p] for p in v)}
                          for k, v in ex_reach.items() if len(v) >= 2), key=lambda x: -x["book_share"])
    risk = [s for s in shared if not s["numeraire"] and NodeType(s["type"]) in RISK_DEFINING]
    spof = risk[0] if risk else None
    return {
        "book": book.name, "n_pockets": len(w), "weights": w,
        "bets": bet_list, "n_bets": len(bet_list), "effective_independent_bets": n_eff,
        "worst_single_point_of_failure": spof,
        "numeraire": [s for s in shared if s["numeraire"]][:3],
        "shared_ancestors": shared,
        "shared_exit_liquidity": shared_exit,
        "headline": (f"These {len(w)} pockets are {len(bet_list)} bets (effective {n_eff:.1f}): "
                     f"{spof['book_share']:.0%} of the book depends on {spof['label']} "
                     f"({', '.join(spof['pockets'])})." if spof else ""),
        "method": "pocket graphs merged by node identity; shared = reachable from >=2 pocket roots in their own graphs; "
                  "bets = union of pockets sharing a non-numeraire issuer / off-chain backing / oracle / lending "
                  "market / vault; N_eff = 1/sum(w_bet^2). Numeraire (USDC, Circle, USDC governance, constant USDC=$1 "
                  "feeds) reported separately. Exit routes reported as shared exit liquidity, not as dependencies.",
    }


def run(book_path=ROOT / "books" / "belem_assumed_book.yaml", offline: bool = True, rediscover: bool = False) -> dict:
    from discovery.pockets import discover_book, load_pocket_graphs
    book = load_book(book_path)
    graphs = discover_book(book, offline) if rediscover else load_pocket_graphs(book)
    res = xray(book, graphs)
    OUT.write_text(json.dumps(res, indent=1, default=str))
    return res


if __name__ == "__main__":
    r = run(offline="--offline" in sys.argv, rediscover="--rediscover" in sys.argv)
    print(r["headline"])
    for b in r["bets"]:
        print(f"  bet {b['weight']:6.1%}  {b['pockets']}  via {b['shared_ancestors'][:3]}")
    print("\nTop shared ancestors:")
    for s in r["shared_ancestors"][:15]:
        print(f"  {s['book_share']:6.1%}  {s['type']:15s} {s['label'][:45]:45s} {s['pockets']}{'  (numeraire)' if s['numeraire'] else ''}")
