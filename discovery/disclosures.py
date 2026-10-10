"""Off-chain layers no trace can see. Added from PUBLIC disclosures only, tagged offchain_disclosed, each with a link.
No sizes/allocations here: those change and must be read live from the linked page.

Disclosures are keyed by ASSET ADDRESS (a registry), never by position: they attach to whatever asset discovery
found in a graph. So a shared off-chain dependency between two pockets only appears if both pockets' traces reached
the same asset.
"""
from __future__ import annotations

from core.schemas import DependencyGraph, Edge, EdgeType, Node, NodeType, Provenance

ETHENA_TRANSPARENCY = "https://app.ethena.fi/dashboards/transparency"
ETHENA_DOCS = "https://docs.ethena.fi"
CIRCLE_TRANSPARENCY = "https://www.circle.com/transparency"
SKY_DOCS = "https://developers.sky.money"
MAPLE_DOCS = "https://docs.maple.finance"
HYPERLIQUID_DOCS = "https://hyperliquid.gitbook.io/hyperliquid-docs"

USDE = "0x4c9edd5852cd905f086c759e8383e09bff1e68b3"
SUSDE = "0x9d39a5de30e57443bff2a8307a4256c8797a3497"
USDC_ETH = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
USDC_SOL = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v".lower()   # Solana mint (ids are lowercased)
USDS = "0xdc035d45d973e3ec169d2276ddab16f1e407384f"
SUSDS = "0xa3931d71877c0e7a3148cb7eb4463524fec27fbd"
SYRUP_USDC = "0x80ac24aa929eaf5013f6436cda2a7ba190f5cc0b"

ETHENA_VENUES = ["Binance", "Bybit", "OKX", "Deribit", "Bitget"]
ETHENA_CUSTODIANS = ["Copper", "Ceffu", "Cobo"]


def _prov(url: str, conf: float = 0.6) -> Provenance:
    return Provenance(source="disclosure", url=url, confidence=conf,
                      detail="public disclosure; lists and sizes must be re-verified live")


def _n(g, nid, t, label, url, conf=0.6, tags=()):
    g.add_node(Node(id=nid, type=t, label=label, tags={"offchain_disclosed", *tags}, provenance=[_prov(url, conf)]))


def _e(g, src, dst, t, url, conf=0.6):
    g.add_edge(Edge(src=src, dst=dst, type=t, provenance=[_prov(url, conf)]))


def _ethena(g: DependencyGraph, asset: str):
    _n(g, "issuer:ethena", NodeType.ISSUER, "Ethena Labs (USDe issuer)", ETHENA_DOCS, 0.9)
    _e(g, asset, "issuer:ethena", EdgeType.ISSUED_BY, ETHENA_DOCS, 0.9)
    if asset != USDE:
        return
    for nid, label, url in (("offchain:ethena_hedge", "Ethena delta hedge (short perps on CEXs)", ETHENA_DOCS),
                            ("offchain:ethena_custody", "Ethena off-exchange custodians (OES)", ETHENA_TRANSPARENCY),
                            ("offchain:ethena_reserve_fund", "Ethena reserve fund", ETHENA_TRANSPARENCY)):
        _n(g, nid, NodeType.OFFCHAIN, label, url)
        _e(g, asset, nid, EdgeType.BACKS, url)
    for v in ETHENA_VENUES:
        _n(g, f"offchain:cex_{v.lower()}", NodeType.OFFCHAIN, f"CEX: {v}", ETHENA_TRANSPARENCY, 0.5, ("cex", "venue"))
        _e(g, "offchain:ethena_hedge", f"offchain:cex_{v.lower()}", EdgeType.BACKS, ETHENA_TRANSPARENCY, 0.5)
    for c in ETHENA_CUSTODIANS:
        _n(g, f"offchain:custodian_{c.lower()}", NodeType.OFFCHAIN, f"Custodian: {c}", ETHENA_TRANSPARENCY, 0.5, ("custodian",))
        _e(g, "offchain:ethena_custody", f"offchain:custodian_{c.lower()}", EdgeType.BACKS, ETHENA_TRANSPARENCY, 0.5)
    _e(g, "offchain:ethena_hedge", "offchain:ethena_custody", EdgeType.BACKS, ETHENA_DOCS, 0.7)


def _circle(g: DependencyGraph, asset: str):
    _n(g, "issuer:circle", NodeType.ISSUER, "Circle (USDC issuer)", CIRCLE_TRANSPARENCY, 0.9)
    _n(g, "offchain:usdc_reserves", NodeType.OFFCHAIN, "USDC reserves (cash + T-bills)", CIRCLE_TRANSPARENCY, 0.9)
    _e(g, asset, "issuer:circle", EdgeType.ISSUED_BY, CIRCLE_TRANSPARENCY, 0.9)
    _e(g, "issuer:circle", "offchain:usdc_reserves", EdgeType.BACKS, CIRCLE_TRANSPARENCY, 0.9)


def _sky(g: DependencyGraph, asset: str):
    _n(g, "issuer:sky", NodeType.ISSUER, "Sky (USDS issuer, ex-Maker)", SKY_DOCS, 0.9)
    _n(g, "offchain:sky_rwa", NodeType.OFFCHAIN, "Sky RWA / T-bill vaults (off-chain arrangers)", SKY_DOCS, 0.5)
    _e(g, asset, "issuer:sky", EdgeType.ISSUED_BY, SKY_DOCS, 0.9)
    _e(g, "issuer:sky", "offchain:sky_rwa", EdgeType.BACKS, SKY_DOCS, 0.5)


def _maple(g: DependencyGraph, asset: str):
    _n(g, "issuer:maple", NodeType.ISSUER, "Maple Finance (syrup pool manager)", MAPLE_DOCS, 0.9)
    _n(g, "offchain:maple_borrowers", NodeType.OFFCHAIN, "Maple institutional borrowers (overcollateralized loans)",
       MAPLE_DOCS, 0.6)
    _e(g, asset, "issuer:maple", EdgeType.ISSUED_BY, MAPLE_DOCS, 0.9)
    _e(g, "issuer:maple", "offchain:maple_borrowers", EdgeType.BACKS, MAPLE_DOCS, 0.6)


REGISTRY = {USDE: _ethena, SUSDE: _ethena, USDC_ETH: _circle, USDC_SOL: _circle, USDS: _sky, SUSDS: _sky,
            SYRUP_USDC: _maple}


def apply(g: DependencyGraph) -> list[str]:
    """Attach disclosed off-chain layers to every registry asset discovery put in the graph. Returns matches."""
    hits = [nid for nid in list(g.nodes) if nid in REGISTRY]
    for nid in hits:
        REGISTRY[nid](g, nid)
    return hits
