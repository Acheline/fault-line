"""Book X-ray (small) for the Belem / RockawayX vaults in books/belem_vaults.csv.

  Morpho vaults: resolved. Ethereum on the fork (Vault V2: adapters -> markets -> collateral, oracle, allocation);
                 Base via the free Morpho GraphQL API. Each market's issuer is matched from the collateral's on-chain
                 name()/symbol() and its wrapper chain (PT -> SY -> yieldToken, ERC-4626 asset()).
  Other vaults:  TVL from the CSV only, labelled "not resolved"; issuer only where the deposit token or vault name
                 states it (e.g. token trUSD, "Huma PST", "OnRe Core Vault").
Dollar exposure = CSV TVL x the market's share of the vault read live, so everything adds up to the $293.63M book.
Effective number of independent bets = 1 / sum(w_i^2) over issuer groups (unresolved vaults without a stated issuer
count as their own group).

    python -m discovery.book_xray [--offline]   -> data/book_xray.json
"""
from __future__ import annotations

import json
import sys
import time
from collections import defaultdict

import requests

from core import addresses as A
from core.fork import ROOT, DiskCache, Fork
from core.vaults import load_vaults, total_tvl
from discovery.hero2 import root_asset

OUT = ROOT / "data" / "book_xray.json"
API = DiskCache("api")

# issuer <- keywords found in token name()/symbol() (on-chain) or, for unresolved vaults, in the CSV name/token
ISSUERS = [
    ("Re Protocol", ("re protocol", "reusd")),
    ("Tori Finance", ("trusd", "tori")),
    ("Hastra / Figure", ("hastra", "wylds")),            # not "prime": "Steakhouse Prime EURCV" is unrelated
    ("infiniFi", ("infinifi", "iusd")),
    ("Huma", ("huma", "payfi strategy")),                # PST = "PayFi Strategy Token" (Huma PayFi)
    ("OnRe", ("onre", "onyc")),
    ("Midas", ("midas", "mrox", "mmev")),
    ("Ethena", ("usde", "ethena")),
    ("f(x) Protocol", ("fxusd", "f(x)", "fxsave")),
    ("Coinbase", ("cbeth", "cbbtc", "coinbase")),
    ("Societe Generale Forge", ("eurcv", "coinvertible")),
]


def issuer_of(text: str) -> tuple[str | None, str | None]:
    t = text.lower()
    for name, keys in ISSUERS:
        for k in keys:
            if k in t:
                return name, k
    return None, None


def _morpho(q: str, key: str, offline: bool):
    hit = API.get(key)
    if hit is not None or offline:
        return (hit or {}).get("data")
    r = requests.post("https://api.morpho.org/graphql", json={"query": q}, timeout=60).json()
    return API.put(key, {"fetched_at": int(time.time()), "data": r.get("data")})["data"]


def resolve_eth_v2(fork: Fork, vault: str) -> list[dict]:
    c = fork.call1
    ta = c(vault, "totalAssets()", "uint256") or 0
    asset = c(vault, "asset()", "address")
    out, used = [], 0
    for i in range(c(vault, "adaptersLength()", "uint256") or 0):
        ad = c(vault, "adapters(uint256)", "address", ["uint256"], [i])
        n = c(ad, "marketIdsLength()", "uint256")
        if n is None:          # adapter type not resolved here (e.g. a vault adapter)
            amt = c(ad, "realAssets()", "uint256") or 0
            used += amt
            out.append({"collateral": None, "symbol": "adapter (not resolved)", "name": ad, "share": amt / ta if ta else 0,
                        "oracle": None, "roots": []})
            continue
        for j in range(n):
            mid = c(ad, "marketIds(uint256)", "bytes32", ["uint256"], [j])
            mp = fork.call(A.MORPHO_BLUE, "idToMarketParams(bytes32)", ["bytes32"], [mid], ["address"] * 4 + ["uint256"])
            amt = c(ad, "expectedSupplyAssets(bytes32)", "uint256", ["bytes32"], [mid]) or 0
            if not mp or amt == 0:
                continue
            used += amt
            coll = mp[1].lower()
            roots = root_asset(fork, coll, mp[0].lower()) if int(coll, 16) else []
            out.append({"collateral": coll, "symbol": c(coll, "symbol()", "string") if int(coll, 16) else "idle",
                        "name": c(coll, "name()", "string") if int(coll, 16) else "", "share": amt / ta if ta else 0,
                        "oracle": mp[2].lower(), "market_id": "0x" + mid.hex(), "lltv": mp[4] / 1e18,
                        "roots": [{"address": r, "symbol": c(r, "symbol()", "string"), "name": c(r, "name()", "string")}
                                  for r in roots[1:]]})
    idle = c(asset, "balanceOf(address)", "uint256", ["address"], [vault]) or 0
    if idle:
        out.append({"collateral": None, "symbol": "idle", "name": "idle cash", "share": idle / ta if ta else 0,
                    "oracle": None, "roots": []})
    return out


def resolve_api_v2(address: str, chain_id: int, offline: bool) -> list[dict]:
    q = ('{ vaultV2ByAddress(address:"%s", chainId:%d){ totalAssetsUsd idleAssetsUsd adapters(first:5){ items{ type '
         'assetsUsd ... on MorphoMarketV1Adapter { positions(first:20){ items{ market{ marketId collateralAsset{ address '
         'symbol name } oracle{ address } } state{ supplyAssetsUsd } } } } } } } }' % (address, chain_id))
    d = (_morpho(q, f"morpho_vault_{chain_id}_{address.lower()}", offline) or {}).get("vaultV2ByAddress") or {}
    tot = d.get("totalAssetsUsd") or 0
    out = []
    for ad in (d.get("adapters") or {}).get("items", []):
        for p in ((ad.get("positions") or {}).get("items") or []):
            ca = p["market"]["collateralAsset"] or {}
            out.append({"collateral": (ca.get("address") or "").lower(), "symbol": ca.get("symbol"), "name": ca.get("name"),
                        "share": (p["state"]["supplyAssetsUsd"] or 0) / tot if tot else 0,
                        "oracle": (p["market"]["oracle"] or {}).get("address"), "market_id": p["market"]["marketId"],
                        "roots": [], "source": "Morpho API"})
    if d.get("idleAssetsUsd"):
        out.append({"collateral": None, "symbol": "idle", "name": "idle cash", "share": d["idleAssetsUsd"] / tot, "roots": []})
    return out


def run(offline: bool = False) -> dict:
    fork = Fork(offline=offline)
    if fork.offline:
        fork.fork_block = A.FORK_BLOCK
    vs = load_vaults()
    book = total_tvl(vs)
    rows, groups = [], defaultdict(lambda: {"usd": 0.0, "vaults": set(), "how": set(), "tokens": set()})
    for v in vs:
        rec = {"vault": v.name, "chain": v.chain, "protocol": v.protocol, "tvl_usd": v.tvl_usd, "address": v.address}
        if v.protocol == "morpho":
            mk = resolve_eth_v2(fork, v.address) if v.chain == "ethereum" else \
                resolve_api_v2(v.address, {"base": 8453}[v.chain], offline)
            rec.update(resolved=True, markets=mk)
            for m in mk:
                text = " ".join([m.get("symbol") or "", m.get("name") or ""] + [f"{r['symbol']} {r['name']}" for r in m["roots"]])
                iss, key = issuer_of(text)
                g = iss or (m["roots"][-1]["symbol"] if m["roots"] else m.get("symbol") or "unknown")
                usd = v.tvl_usd * m["share"]
                m.update(issuer=g, usd=usd, evidence=f"on-chain name/symbol contains '{key}'" if key else "collateral itself")
                groups[g]["usd"] += usd
                groups[g]["vaults"].add(v.name)
                groups[g]["how"].add("resolved")
                groups[g]["tokens"].add(m.get("symbol") or "")
        else:
            iss, key = issuer_of(f"{v.name} {v.token}")
            g = iss or f"{v.name} ({v.protocol}, not resolved)"
            rec.update(resolved=False, issuer=g, evidence=f"vault name/token contains '{key}'" if key else None)
            groups[g]["usd"] += v.tvl_usd
            groups[g]["vaults"].add(v.name)
            groups[g]["how"].add("not resolved (name/token)" if iss else "not resolved")
            groups[g]["tokens"].add(v.token)
        rows.append(rec)
    G = sorted(({"issuer": k, "usd": x["usd"], "share": x["usd"] / book, "n_vaults": len(x["vaults"]),
                 "vaults": sorted(x["vaults"]), "how": sorted(x["how"]), "tokens": sorted(t for t in x["tokens"] if t)}
                for k, x in groups.items()), key=lambda r: -r["usd"])
    eff = 1 / sum(r["share"] ** 2 for r in G) if G else None
    resolved = sum(r["tvl_usd"] for r in rows if r.get("resolved"))
    shared = [r for r in G if r["n_vaults"] >= 2]
    named = [r for r in G if r["issuer"] in ("Tori Finance", "Huma", "OnRe", "Re Protocol")]
    top = next((r for r in G if "not resolved" not in r["issuer"]), G[0] if G else None)
    out = {"book_usd": book, "n_vaults": len(vs), "effective_bets": eff, "groups": G, "shared": shared, "checked": named,
           "coverage": {"resolved_usd": resolved, "resolved_share": resolved / book,
                        "n_resolved": sum(1 for r in rows if r.get("resolved")), "unresolved_usd": book - resolved},
           "headline": f"{len(vs)} vaults, {eff:.1f} independent bets; {top['share']:.1%} depends on {top['issuer']}"
           if top else None, "vaults": rows, "fork_block": fork.fork_block}
    OUT.write_text(json.dumps(out, indent=1, default=str))
    return out


if __name__ == "__main__":
    o = run(offline="--offline" in sys.argv)
    print(o["headline"])
    print(f"coverage: {o['coverage']['n_resolved']} Morpho vaults resolved = ${o['coverage']['resolved_usd'] / 1e6:.1f}M "
          f"({o['coverage']['resolved_share']:.1%}); ${o['coverage']['unresolved_usd'] / 1e6:.1f}M from CSV TVL only")
    print("\nunder several vaults:")
    for r in o["shared"]:
        print(f"  {r['issuer']:28s} ${r['usd'] / 1e6:6.2f}M {r['share']:6.1%}  {r['n_vaults']} vaults {r['how']} {r['tokens']}")
    print("\nchecked (trUSD/Tori, Huma, OnRe, Re Protocol):")
    for r in o["checked"]:
        print(f"  {r['issuer']:28s} ${r['usd'] / 1e6:6.2f}M {r['share']:6.1%}  {r['vaults']} {r['how']}")
    print("\ntop groups:")
    for r in o["groups"][:12]:
        print(f"  {r['issuer'][:40]:40s} ${r['usd'] / 1e6:6.2f}M {r['share']:6.1%} {r['n_vaults']}v {r['how']}")
