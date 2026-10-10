"""Off-chain layers no trace can see. Added from PUBLIC disclosures only, tagged offchain_disclosed,
each with a link. No sizes/allocations here: those change and must be read live from the linked page."""
from __future__ import annotations

from core.schemas import DependencyGraph, Edge, EdgeType, Node, NodeType, Provenance

ETHENA_TRANSPARENCY = "https://app.ethena.fi/dashboards/transparency"
ETHENA_DOCS = "https://docs.ethena.fi"
CIRCLE_TRANSPARENCY = "https://www.circle.com/transparency"

# (node_id, type, label, url)
ETHENA = [
    ("offchain:ethena_hedge", NodeType.OFFCHAIN, "Ethena delta hedge (short perps on CEXs)", ETHENA_DOCS),
    ("offchain:ethena_custody", NodeType.OFFCHAIN, "Ethena off-exchange custodians (OES)", ETHENA_TRANSPARENCY),
    ("offchain:ethena_reserve_fund", NodeType.OFFCHAIN, "Ethena reserve fund", ETHENA_TRANSPARENCY),
]
ETHENA_VENUES = ["Binance", "Bybit", "OKX", "Deribit", "Bitget"]
ETHENA_CUSTODIANS = ["Copper", "Ceffu", "Cobo"]


def _prov(url: str, conf: float = 0.6) -> Provenance:
    return Provenance(source="disclosure", url=url, confidence=conf,
                      detail="public disclosure; venue/custodian list must be re-verified live")


def add_ethena(g: DependencyGraph, usde: str, susde: str):
    usde, susde = usde.lower(), susde.lower()
    g.add_node(Node(id="issuer:ethena", type=NodeType.ISSUER, label="Ethena Labs (USDe issuer)",
                    tags={"offchain_disclosed"}, provenance=[_prov(ETHENA_DOCS, 0.9)]))
    for a in (usde, susde):
        if a in g.nodes:
            g.add_edge(Edge(src=a, dst="issuer:ethena", type=EdgeType.ISSUED_BY, provenance=[_prov(ETHENA_DOCS, 0.9)]))
    for nid, t, label, url in ETHENA:
        g.add_node(Node(id=nid, type=t, label=label, tags={"offchain_disclosed"}, provenance=[_prov(url)]))
        g.add_edge(Edge(src=usde, dst=nid, type=EdgeType.BACKS, provenance=[_prov(url)]))
    for v in ETHENA_VENUES:
        nid = f"offchain:cex_{v.lower()}"
        g.add_node(Node(id=nid, type=NodeType.OFFCHAIN, label=f"CEX: {v}", tags={"offchain_disclosed", "cex"},
                        provenance=[_prov(ETHENA_TRANSPARENCY, 0.5)]))
        g.add_edge(Edge(src="offchain:ethena_hedge", dst=nid, type=EdgeType.BACKS,
                        provenance=[_prov(ETHENA_TRANSPARENCY, 0.5)]))
    for c in ETHENA_CUSTODIANS:
        nid = f"offchain:custodian_{c.lower()}"
        g.add_node(Node(id=nid, type=NodeType.OFFCHAIN, label=f"Custodian: {c}",
                        tags={"offchain_disclosed", "custodian"}, provenance=[_prov(ETHENA_TRANSPARENCY, 0.5)]))
        g.add_edge(Edge(src="offchain:ethena_custody", dst=nid, type=EdgeType.BACKS,
                        provenance=[_prov(ETHENA_TRANSPARENCY, 0.5)]))
        # hedges sit at the CEX but collateral sits with the custodian: hedge depends on custody
    g.add_edge(Edge(src="offchain:ethena_hedge", dst="offchain:ethena_custody", type=EdgeType.BACKS,
                    provenance=[_prov(ETHENA_DOCS, 0.7)]))


def add_circle(g: DependencyGraph, usdc: str):
    usdc = usdc.lower()
    g.add_node(Node(id="issuer:circle", type=NodeType.ISSUER, label="Circle (USDC issuer)",
                    tags={"offchain_disclosed"}, provenance=[_prov(CIRCLE_TRANSPARENCY, 0.9)]))
    g.add_node(Node(id="offchain:usdc_reserves", type=NodeType.OFFCHAIN, label="USDC reserves (cash + T-bills)",
                    tags={"offchain_disclosed"}, provenance=[_prov(CIRCLE_TRANSPARENCY, 0.9)]))
    if usdc in g.nodes:
        g.add_edge(Edge(src=usdc, dst="issuer:circle", type=EdgeType.ISSUED_BY, provenance=[_prov(CIRCLE_TRANSPARENCY, 0.9)]))
    g.add_edge(Edge(src="issuer:circle", dst="offchain:usdc_reserves", type=EdgeType.BACKS,
                    provenance=[_prov(CIRCLE_TRANSPARENCY, 0.9)]))
