"""Generic per-pocket discovery for a book (Module 4 input). Each pocket gets its own graph, built only from what its
own transactions touch on the fork (or, off-EVM, what its official API returns):

  token_hold      value call (ERC-4626 rate / Aave index) + EXIT executed on the fork (KyberSwap route, or Aave withdraw)
  vault           Vault V2: totalAssets() trace + redeem/withdraw executed as a holder + adapter markets read on-chain,
                  each market's oracle.price() traced
  hero1           P1 / P2 carved out of the hero #1 graph (PT outright vs Morpho collateral loop)
  kamino          Kamino API (Solana): market, reserves, collateral
  offchain_venue  Hyperliquid API: HLP vault, bridge, settlement chain

    python -m discovery.pockets [--offline]   -> data/graphs/pockets/<id>.json
"""
from __future__ import annotations

import copy
import sys
import time

import networkx as nx
import requests
from eth_abi import encode

from core import addresses as A
from core.book import Book, Position, load_book
from core.fork import ROOT, DiskCache, Fork, selector
from core.schemas import (CriticalPath, DependencyGraph, Edge, EdgeType, Node, NodeType, Provenance,
                          stable_hash)
from discovery import disclosures
from discovery.builder import GraphBuilder

HARNESS = "0xfa0171fa0171fa0171fa0171fa0171fa0171fa01"
OUT = ROOT / "data" / "graphs" / "pockets"
API = DiskCache("api")
AAVE_POOL = "0x87870Bca3F3fD6335C3F4ce8392D69350B4fA4E2"
KYBER = "https://aggregator-api.kyberswap.com/ethereum/api/v1"


def _api(key, fn, offline):
    hit = API.get(key)
    if hit is not None or offline:
        return (hit or {}).get("data")
    return API.put(key, {"fetched_at": int(time.time()), "data": fn()})["data"]


def _trace(fork: Fork, tx: dict, label: str) -> dict:
    tx = {**tx, "gas": hex(30_000_000)}
    return {"label": label, "call": fork.trace_call(tx, "callTracer", label),
            "pre": fork.trace_call(tx, "prestateTracer", label)}


def _root(b: GraphBuilder, pos: Position, chain: str = "ethereum"):
    b.g.add_node(Node(id=f"chain:{chain}", type=NodeType.CHAIN, label=chain.capitalize()))
    b.g.add_edge(Edge(src=b.root, dst=f"chain:{chain}", type=EdgeType.REFERENCES, props={"role": "settlement"}))
    b.g.nodes[b.root].props.update(size_usd=pos.size_usd, pocket=pos.id)


# --------------------------------------------------------------------------- token_hold
def kyber_exit(token: str, amount: int, offline: bool) -> dict | None:
    def fetch():
        r = requests.get(f"{KYBER}/routes", params={"tokenIn": token, "tokenOut": A.USDC, "amountIn": str(amount)},
                         headers={"x-client-id": "fault-line"}, timeout=60).json()
        rs = r["data"]["routeSummary"]
        bld = requests.post(f"{KYBER}/route/build", headers={"x-client-id": "fault-line"}, timeout=60, json={
            "routeSummary": rs, "sender": HARNESS, "recipient": HARNESS, "slippageTolerance": 100}).json()["data"]
        return {"to": bld["routerAddress"], "data": bld["data"], "amount_out": int(bld["amountOut"]),
                "amount_in_usd": float(rs.get("amountInUsd") or 0), "amount_out_usd": float(rs.get("amountOutUsd") or 0)}
    try:
        return _api(f"kyber_{token.lower()}_{amount}", fetch, offline)
    except Exception:
        return None


def token_price_usd(token: str, dec: int, offline: bool) -> float | None:
    q = kyber_exit(token, 10**dec, offline)
    return q["amount_out"] / 1e6 if q else None


def token_hold(pos: Position, fork: Fork, offline: bool) -> tuple[DependencyGraph, dict]:
    token = pos.legs[0].asset.lower()
    b = GraphBuilder(fork, pos.id, pos.label)
    _root(b, pos)
    node = b.ensure(token, Provenance(source="api", detail="book.yaml leg asset"), CriticalPath.VALUE)
    b.g.add_edge(Edge(src=b.root, dst=token, type=EdgeType.HOLDS))
    dec = node.props.get("decimals") or 18
    meta: dict = {}
    traces = []
    under = fork.call1(token, "UNDERLYING_ASSET_ADDRESS()", "address")
    if "erc4626" in node.tags:
        traces.append((CriticalPath.VALUE, _trace(fork, {"to": token, "data": "0x" + (
            selector("convertToAssets(uint256)") + encode(["uint256"], [10**dec])).hex()}, f"value:{pos.id}.convertToAssets"), token))
    if under:   # Aave aToken: value = reserve normalized income; exit = Pool.withdraw
        traces.append((CriticalPath.VALUE, _trace(fork, {"to": AAVE_POOL, "data": "0x" + (
            selector("getReserveNormalizedIncome(address)") + encode(["address"], [under])).hex()},
            f"value:{pos.id}.aave_income"), token))
        amt = int((pos.size_usd or 0) * 10**6)
        with fork.snapshot():
            fork.fund_erc20(under, HARNESS, amt)
            fork.send(HARNESS, under, selector("approve(address,uint256)") + encode(["address", "uint256"], [AAVE_POOL, 2**256 - 1]))
            fork.send(HARNESS, AAVE_POOL, selector("supply(address,uint256,address,uint16)") +
                      encode(["address", "uint256", "address", "uint16"], [under, amt, HARNESS, 0]))
            t = _trace(fork, {"from": HARNESS, "to": AAVE_POOL, "data": "0x" + (selector("withdraw(address,uint256,address)") +
                              encode(["address", "uint256", "address"], [under, 2**256 - 1, HARNESS])).hex()},
                       f"exit:{pos.id}.aave_withdraw")   # max = withdraw all (an exact amount reverts on index rounding)
        traces.append((CriticalPath.EXIT, t, token))
        out = t["call"].get("output") or "0x"
        meta["exit"] = {"route": "Aave Pool.withdraw", "size_usd": pos.size_usd, "error": t["call"].get("error"),
                        "usdc_out": int(out[2:66], 16) / 1e6 if len(out) >= 66 and not t["call"].get("error") else None}
    else:
        px = token_price_usd(token, dec, offline)
        amt = int((pos.size_usd or 0) / px * 10**dec) if px else 0
        q = kyber_exit(token, amt, offline) if amt else None
        if q:
            with fork.snapshot():
                fork.fund_erc20(token, HARNESS, amt)
                fork.send(HARNESS, token, selector("approve(address,uint256)") + encode(["address", "uint256"], [q["to"], 2**256 - 1]))
                t = _trace(fork, {"from": HARNESS, "to": q["to"], "data": q["data"]}, f"exit:{pos.id}.kyber")
            out = t["call"].get("output") or "0x"
            got = int(out[2:66], 16) / 1e6 if len(out) >= 66 and not t["call"].get("error") else None
            traces.append((CriticalPath.EXIT, t, token))
            meta["exit"] = {"route": "KyberSwap aggregator", "size_usd": pos.size_usd, "token_price_usd": px,
                            "usdc_out": got, "quote_usdc": q["amount_out"] / 1e6, "error": t["call"].get("error")}
    for path, t, entry in traces:
        b.ingest_trace(t["call"], t["pre"], path, t["label"], entry_src=entry)
    return b, meta


# --------------------------------------------------------------------------- vault (Morpho Vault V2)
def vault(pos: Position, fork: Fork, offline: bool) -> tuple[GraphBuilder, dict]:
    v = pos.legs[0].asset.lower()
    b = GraphBuilder(fork, pos.id, pos.label)
    _root(b, pos)
    b.ensure(v, Provenance(source="api", detail="book.yaml leg asset"), CriticalPath.VALUE)
    b.g.add_edge(Edge(src=b.root, dst=v, type=EdgeType.HOLDS))
    traces = [(CriticalPath.VALUE, _trace(fork, {"to": v, "data": "0x" + selector("totalAssets()").hex()},
                                          f"value:{pos.id}.totalAssets"), v)]
    meta: dict = {"markets": []}
    # adapters -> Morpho markets (on-chain), each market's oracle traced
    blk = fork.fork_block
    n_ad = fork.call1(v, "adaptersLength()", "uint256") or 0
    for i in range(n_ad):
        ad = fork.call1(v, "adapters(uint256)", "address", ["uint256"], [i])
        if not ad:
            continue
        ad = ad.lower()
        b.ensure(ad, Provenance(source="storage", block=blk, detail=f"vault.adapters({i})"))
        b.g.add_edge(Edge(src=v, dst=ad, type=EdgeType.ALLOCATES_TO, provenance=[Provenance(source="storage", block=blk,
                                                                                           detail=f"adapters({i})")]))
        n_m = fork.call1(ad, "marketIdsLength()", "uint256") or 0
        for j in range(n_m):
            mid = fork.call1(ad, "marketIds(uint256)", "bytes32", ["uint256"], [j])
            if not mid:
                continue
            alloc = (fork.call1(ad, "expectedSupplyAssets(bytes32)", "uint256", ["bytes32"], [mid]) or 0) / 1e6
            mp = fork.call(A.MORPHO_BLUE, "idToMarketParams(bytes32)", ["bytes32"], [mid],
                           ["address", "address", "address", "address", "uint256"])
            if not mp or alloc <= 0:
                continue
            loan, coll, orc, irm, lltv = mp
            mnode = f"morpho_market:0x{mid.hex()}"
            prov = Provenance(source="storage", block=blk, detail="adapter.marketIds + Morpho.idToMarketParams")
            for a in (coll, orc, loan):
                if int(a, 16):
                    b.ensure(a, prov, CriticalPath.VALUE)
            csym = b.g.nodes[coll.lower()].label if int(coll, 16) else "idle"
            b.g.add_node(Node(id=mnode, type=NodeType.LENDING_MARKET, label=f"Morpho {csym}/USDC {lltv / 1e16:.1f}%",
                              props={"market_id": "0x" + mid.hex(), "lltv": lltv / 1e18, "allocation_usd": alloc},
                              paths={CriticalPath.VALUE}, provenance=[prov]))
            b.g.add_edge(Edge(src=ad, dst=mnode, type=EdgeType.ALLOCATES_TO, props={"allocation_usd": alloc}, provenance=[prov]))
            b.g.add_edge(Edge(src=mnode, dst=A.MORPHO_BLUE.lower(), type=EdgeType.REFERENCES, props={"role": "singleton"}, provenance=[prov]))
            b.ensure(A.MORPHO_BLUE, prov)
            if int(coll, 16):
                b.g.add_edge(Edge(src=mnode, dst=coll.lower(), type=EdgeType.USES_COLLATERAL, provenance=[prov]))
            b.g.add_edge(Edge(src=mnode, dst=loan.lower(), type=EdgeType.LENDS, provenance=[prov]))
            if int(orc, 16):
                b.g.add_edge(Edge(src=mnode, dst=orc.lower(), type=EdgeType.PRICES, provenance=[prov]))
                traces.append((CriticalPath.VALUE, _trace(fork, {"from": A.MORPHO_BLUE, "to": orc, "data": "0x" + selector("price()").hex()},
                                                          f"value:{pos.id}.{csym}.oracle.price"), mnode))
            meta["markets"].append({"market_id": "0x" + mid.hex(), "collateral": csym, "allocation_usd": alloc,
                                    "lltv": lltv / 1e18, "oracle": orc})
    # EXIT (lender side): withdrawable NOW = idle + free liquidity of the liquidity market, capped by our allocation.
    # Vault V2 maxWithdraw() returns 0 by design, so we measure it from Morpho state.
    amt = int((pos.size_usd or 0) * 1e6)
    idle = fork.call1(A.USDC, "balanceOf(address)", "uint256", ["address"], [v]) or 0
    liq_free, liq_mid = 0, None
    ld = fork.call(v, "liquidityData()", out_types=["bytes"])
    liq_ad = (fork.call1(v, "liquidityAdapter()", "address") or "").lower()
    if ld and len(ld[0]) >= 160:
        from eth_abi import decode as _dec
        from eth_utils import keccak
        mp = _dec(["(address,address,address,address,uint256)"], ld[0])[0]
        liq_mid = keccak(encode(["(address,address,address,address,uint256)"], [mp]))
        mk = fork.call(A.MORPHO_BLUE, "market(bytes32)", ["bytes32"], [liq_mid], ["uint128"] * 6)
        ours = fork.call1(liq_ad, "expectedSupplyAssets(bytes32)", "uint256", ["bytes32"], [liq_mid]) or 0 if liq_ad else 0
        liq_free = min(ours, (mk[0] - mk[2]) if mk else 0)
    withdrawable = idle + liq_free
    w = min(amt, withdrawable)
    meta["exit"] = {"route": "vault.redeem via liquidity adapter", "size_usd": pos.size_usd,
                    "withdrawable_now_usd": withdrawable / 1e6, "idle_usd": idle / 1e6,
                    "liquidity_market_free_usd": liq_free / 1e6,
                    "liquidity_market": "0x" + liq_mid.hex() if liq_mid else None,
                    "locked_usd": max(0, amt - withdrawable) / 1e6}
    if w > 0:
        shares = fork.call1(v, "convertToShares(uint256)", "uint256", ["uint256"], [w]) or 0
        with fork.snapshot():
            try:
                fork.fund_erc20(v, HARNESS, shares)   # totalSupply untouched: shares priced at the real rate
                t = _trace(fork, {"from": HARNESS, "to": v, "data": "0x" + (selector("redeem(uint256,address,address)") +
                                  encode(["uint256", "address", "address"], [shares, HARNESS, HARNESS])).hex()},
                           f"exit:{pos.id}.redeem")
                traces.append((CriticalPath.EXIT, t, v))
                out = t["call"].get("output") or "0x"
                meta["exit"].update(traced_redeem_usd=int(out[2:66], 16) / 1e6 if len(out) >= 66 and not t["call"].get("error") else None,
                                    error=t["call"].get("error"))
            except RuntimeError as e:
                meta["exit"]["error"] = str(e)
    for path, t, entry in traces:
        b.ingest_trace(t["call"], t["pre"], path, t["label"], entry_src=entry)
    return b, meta


# --------------------------------------------------------------------------- hero #1 split
def hero1_split(pos: Position) -> DependencyGraph:
    """P1 = PT outright (holds PT + exit route); P2 = Morpho loop (market + liquidation + exit to unwind)."""
    g = DependencyGraph.model_validate_json((ROOT / "data" / "graphs" / "hero1.json").read_text())
    old = f"position:{g.position_id}"
    new = f"position:{pos.id}"
    loop = any(l.type.value == "morpho_collateral" for l in pos.legs)
    keep_root = []
    for e in g.edges.values():
        if e.src != old:
            continue
        if e.type == EdgeType.HOLDS and (("borrows" in e.props.get("role", "")) != loop):
            continue                               # P1 drops the market leg, P2 drops the outright leg
        if e.path == CriticalPath.VALUE and loop:
            continue
        keep_root.append(e)
    out = DependencyGraph(position_id=pos.id, fork_block=g.fork_block)
    out.add_node(Node(id=new, type=NodeType.POSITION, label=pos.label, props={"size_usd": pos.size_usd, "pocket": pos.id}))
    edges = [e for e in g.edges.values() if e.src != old] + keep_root
    G = nx.DiGraph([(new if e.src == old else e.src, e.dst) for e in edges])
    reach = nx.descendants(G, new) | {new} if new in G else {new}
    for nid in reach - {new}:
        out.nodes[nid] = copy.deepcopy(g.nodes[nid])
    for e in edges:
        src = new if e.src == old else e.src
        if src in reach and e.dst in reach:
            out.add_edge(e.model_copy(update={"src": src}))
    return out


# --------------------------------------------------------------------------- Solana / Hyperliquid (API)
def kamino(pos: Position, offline: bool) -> DependencyGraph:
    from core.book_builder import KAMINO_MAIN_MARKET
    g = DependencyGraph(position_id=pos.id, fork_block=0)
    root = f"position:{pos.id}"
    url = f"https://api.kamino.finance/kamino-market/{KAMINO_MAIN_MARKET}/reserves/metrics?env=mainnet-beta"
    km = _api("kamino_main_reserves", lambda: requests.get(url, timeout=60).json(), offline) or []
    prov = Provenance(source="api", url=url, detail="Kamino reserves/metrics", confidence=0.9)
    g.add_node(Node(id=root, type=NodeType.POSITION, label=pos.label, props={"size_usd": pos.size_usd, "pocket": pos.id}))
    g.add_node(Node(id="chain:solana", type=NodeType.CHAIN, label="Solana"))
    mk = f"kamino_market:{KAMINO_MAIN_MARKET.lower()}"
    g.add_node(Node(id=mk, type=NodeType.LENDING_MARKET, label="Kamino Lend main market", chain="solana",
                    props={"protocol": "kamino-lend"}, provenance=[prov]))
    usdc = disclosures.USDC_SOL
    g.add_node(Node(id=usdc, type=NodeType.ASSET, label="USDC (Solana)", chain="solana", address=usdc, provenance=[prov]))
    for e in (Edge(src=root, dst=mk, type=EdgeType.HOLDS, props={"role": "USDC supplier"}),
              Edge(src=root, dst="chain:solana", type=EdgeType.REFERENCES, props={"role": "settlement"}),
              Edge(src=mk, dst=usdc, type=EdgeType.LENDS, provenance=[prov])):
        g.add_edge(e)
    # the supplier is exposed to every collateral the market accepts: top reserves by supply
    colls = sorted((r for r in km if r.get("liquidityTokenMint", "").lower() != usdc and float(r.get("totalSupplyUsd", 0)) > 0),
                   key=lambda r: -float(r["totalSupplyUsd"]))[:10]
    for r in colls:
        cid = r["liquidityTokenMint"].lower()
        g.add_node(Node(id=cid, type=NodeType.ASSET, label=f"{r['liquidityToken']} (Solana)", chain="solana", address=cid,
                        props={"supply_usd": float(r["totalSupplyUsd"])}, provenance=[prov]))
        g.add_edge(Edge(src=mk, dst=cid, type=EdgeType.USES_COLLATERAL, provenance=[prov]))
    g.add_node(Node(id="oracle:kamino_scope", type=NodeType.ORACLE, label="Scope oracle (Kamino price aggregator)",
                    chain="solana", tags={"offchain_disclosed"},
                    provenance=[Provenance(source="disclosure", url="https://docs.kamino.finance", confidence=0.6)]))
    g.add_edge(Edge(src=mk, dst="oracle:kamino_scope", type=EdgeType.PRICES,
                    provenance=[Provenance(source="disclosure", url="https://docs.kamino.finance", confidence=0.6)]))
    return g


def hyperliquid(pos: Position, offline: bool) -> DependencyGraph:
    from core.book_builder import HLP
    url = "https://api.hyperliquid.xyz/info"
    hl = _api("hyperliquid_hlp", lambda: requests.post(url, json={"type": "vaultDetails", "vaultAddress": HLP}, timeout=60).json(),
              offline) or {}
    prov = Provenance(source="api", url=url, detail="vaultDetails", confidence=0.9)
    dprov = Provenance(source="disclosure", url=disclosures.HYPERLIQUID_DOCS, confidence=0.7)
    g = DependencyGraph(position_id=pos.id, fork_block=0)
    root = f"position:{pos.id}"
    usdc_arb = "0xaf88d065e77c8cc2239327c5edb3a432268e5831"
    nodes = [
        Node(id=root, type=NodeType.POSITION, label=pos.label, props={"size_usd": pos.size_usd, "pocket": pos.id}),
        Node(id="chain:hyperliquid", type=NodeType.CHAIN, label="Hyperliquid L1"),
        Node(id="chain:arbitrum", type=NodeType.CHAIN, label="Arbitrum"),
        Node(id=f"venue:{HLP}", type=NodeType.OFFCHAIN, label=hl.get("name") or "Hyperliquid HLP", chain="hyperliquid",
             tags={"venue", "perp"}, props={"protocol": "hyperliquid-hlp", "allow_deposits": hl.get("allowDeposits")},
             provenance=[prov]),
        Node(id="venue:hyperliquid_perps", type=NodeType.OFFCHAIN, label="Hyperliquid perp order book (HLP is the market maker / liquidator)",
             chain="hyperliquid", tags={"venue", "perp", "offchain_disclosed"}, provenance=[dprov]),
        Node(id="governance:hyperliquid_validators", type=NodeType.GOVERNANCE, label="Hyperliquid validator set (bridge signers)",
             chain="hyperliquid", tags={"offchain_disclosed"}, provenance=[dprov]),
        Node(id="bridge:hyperliquid_arbitrum", type=NodeType.CONTRACT, label="Hyperliquid bridge (Arbitrum)",
             chain="arbitrum", tags={"bridge", "offchain_disclosed"}, provenance=[dprov]),
        Node(id=usdc_arb, type=NodeType.ASSET, label="USDC (Arbitrum)", chain="arbitrum", address=usdc_arb, provenance=[dprov]),
    ]
    if hl.get("leader"):
        nodes.append(Node(id=f"leader:{hl['leader'].lower()}", type=NodeType.GOVERNANCE, label="HLP vault leader",
                          chain="hyperliquid", props={"address": hl["leader"]}, provenance=[prov]))
    for n in nodes:
        g.add_node(n)
    edges = [(root, f"venue:{HLP}", EdgeType.HOLDS), (root, "chain:hyperliquid", EdgeType.REFERENCES),
             (f"venue:{HLP}", "venue:hyperliquid_perps", EdgeType.ALLOCATES_TO), (f"venue:{HLP}", usdc_arb, EdgeType.BACKS),
             (f"venue:{HLP}", "bridge:hyperliquid_arbitrum", EdgeType.EXIT_ROUTE),
             ("bridge:hyperliquid_arbitrum", "governance:hyperliquid_validators", EdgeType.GOVERNS),
             ("bridge:hyperliquid_arbitrum", "chain:arbitrum", EdgeType.REFERENCES),
             ("venue:hyperliquid_perps", "chain:hyperliquid", EdgeType.REFERENCES)]
    if hl.get("leader"):
        edges.append((f"venue:{HLP}", f"leader:{hl['leader'].lower()}", EdgeType.GOVERNS))
    for s, d, t in edges:
        g.add_edge(Edge(src=s, dst=d, type=t, provenance=[dprov if t != EdgeType.HOLDS else prov]))
    return g


# --------------------------------------------------------------------------- driver
def discover(pos: Position, fork: Fork, offline: bool = False) -> DependencyGraph:
    meta: dict = {}
    if pos.pipeline == "discovery.hero1":
        g = hero1_split(pos)
    elif pos.pipeline == "discovery.kamino":
        g = kamino(pos, offline)
    elif pos.pipeline == "discovery.offchain_venue":
        g = hyperliquid(pos, offline)
    else:
        b, meta = (vault if pos.pipeline == "discovery.vault" else token_hold)(pos, fork, offline)
        b.resolve({CriticalPath.VALUE: 1, CriticalPath.EXIT: 0, CriticalPath.LIQUIDATION: 1}, max_nodes=250)
        g = b.g
    disclosures.apply(g)
    g.meta.update(meta, pocket=pos.id, size_usd=pos.size_usd, pipeline=pos.pipeline)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{pos.id}.json").write_text(g.to_json())
    return g


def discover_book(book: Book, offline: bool = False) -> dict[str, DependencyGraph]:
    fork = Fork(offline=offline)
    if fork.offline:
        fork.fork_block = A.FORK_BLOCK
    out = {}
    for p in book.positions:
        t0 = time.time()
        out[p.id] = discover(p, fork, offline)
        g = out[p.id]
        print(f"  {p.id:4s} {p.pipeline:26s} {len(g.nodes):4d} nodes {len(g.edges):4d} edges  {time.time() - t0:5.1f}s"
              f"  {g.meta.get('exit', '')}")
    return out


def load_pocket_graphs(book: Book) -> dict[str, DependencyGraph]:
    return {p.id: DependencyGraph.model_validate_json((OUT / f"{p.id}.json").read_text())
            for p in book.positions if (OUT / f"{p.id}.json").exists()}


if __name__ == "__main__":
    bk = load_book(ROOT / "books" / "belem_assumed_book.yaml")
    discover_book(bk, offline="--offline" in sys.argv)
