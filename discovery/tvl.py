"""M1.9 TVL concentration: each protocol in the graph, its TVL on the chain and its share of the chain's DeFi
TVL (DefiLlama). A protocol holding a large share of a chain's TVL is a chain-level liquidity event if it
fails: it feeds the correlation structure of Module 2."""
from __future__ import annotations

import re
import time

import requests

from core.fork import DiskCache
from core.schemas import DependencyGraph, NodeType, Provenance

_cache = DiskCache("api")

# graph node (verified contract name / label) -> DefiLlama slug. Heuristic: tagged confidence 0.8.
PROTOCOL_RULES = [
    (r"^morpho|metamorpho|adaptivecurveirm|vaultv2", "morpho-blue"),
    (r"^pendle|^pt-|^sy-|^yt-|pendlemarket", "pendle-v2"),
    (r"ethena|^usde$|^susde$|usdesilo|stakedusde", "ethena-usde"),
    (r"curvestableswap|curve|crvusd|vyper_contract", "curve-dex"),
    (r"poolmanager|uniswap|v4feeadapter", "uniswap-v4"),
    (r"fluid|insta", "fluid-dex"),
    (r"kyber|metaaggregationrouter", "kyberswap-aggregator"),
    (r"frxusd|frax", "frax"),
    (r"dola|inverse|xinv|^inv$|governormills", "inverse-finance-firm"),
]
FLAG_SHARE = 0.05     # assumption: flag protocols holding >= 5% of the chain's DeFi TVL (slider in UI)
LLAMA_CHAIN = {"ethereum": "Ethereum", "solana": "Solana"}


def _get(url: str, key: str, offline: bool, trim=None):
    hit = _cache.get(key)
    if hit is not None or offline:
        return hit
    data = requests.get(url, timeout=120).json()
    data = trim(data) if trim else data
    return _cache.put(key, {"fetched_at": int(time.time()), "data": data})


def concentration(g: DependencyGraph, chain: str = "ethereum", offline: bool = False) -> list[dict]:
    protos = _get("https://api.llama.fi/protocols", "llama_protocols", offline, trim=lambda d: [
        {"slug": p["slug"], "name": p["name"], "category": p.get("category"), "parentProtocol": p.get("parentProtocol"),
         "chainTvls": {k: v for k, v in (p.get("chainTvls") or {}).items() if k in LLAMA_CHAIN.values()}}
        for p in d])
    chains = _get("https://api.llama.fi/v2/chains", "llama_chains", offline)
    if not protos or not chains:
        return []
    lc = LLAMA_CHAIN[chain]
    chain_tvl = next(c["tvl"] for c in chains["data"] if c["name"] == lc)
    by_slug = {p["slug"]: p for p in protos["data"]}
    members: dict[str, list[str]] = {}
    for n in g.nodes.values():
        if not n.address or "eoa" in n.tags:
            continue
        # verified contract name first; labels only for tokens/pools (a "USDe / USD" feed is Chainlink, not Ethena)
        text = n.props.get("contract_name") or (n.label if n.type in (NodeType.ASSET, NodeType.LIQUIDITY_VENUE) else "")
        name = (text or "").lower()
        for rx, slug in PROTOCOL_RULES:
            if any(re.search(rx, part) for part in name.split()):
                n.props["protocol"] = slug
                members.setdefault(slug, []).append(n.id)
                break
    out = []
    for slug, ids in members.items():
        p = by_slug.get(slug)
        if not p:
            continue
        tvl = (p.get("chainTvls") or {}).get(lc, 0.0)
        parent = p.get("parentProtocol")
        parent_tvl = sum((q.get("chainTvls") or {}).get(lc, 0.0) for q in protos["data"]
                         if parent and q.get("parentProtocol") == parent)
        share = tvl / chain_tvl
        out.append({"protocol": slug, "name": p["name"], "category": p.get("category"), "chain": lc,
                    "tvl_usd": tvl, "chain_defi_tvl_usd": chain_tvl, "share_of_chain": share,
                    "parent": parent, "parent_share_of_chain": parent_tvl / chain_tvl if parent else None,
                    "n_graph_nodes": len(ids), "flag": share >= FLAG_SHARE,
                    "provenance": Provenance(source="api", url="https://api.llama.fi/protocols", confidence=0.8,
                                             detail=f"DefiLlama fetched_at={protos['fetched_at']} (live, not at fork "
                                                    f"block); node->protocol mapping by contract name").model_dump()})
    return sorted(out, key=lambda r: -r["share_of_chain"])
