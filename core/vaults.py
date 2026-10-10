"""Vault registry: books/belem_vaults.csv, the full Belem / RockawayX curated-vault list (exported from the team's
dashboard https://dune.com/rockawayxvault/rockawayx-dashboard; no Dune API is used). TVL figures are the
dashboard's snapshot: resolvers re-read allocations live (on-chain / protocol APIs) and say which they could resolve.

    from core.vaults import load_vaults
    vs = load_vaults()          # list[Vault], largest first
"""
from __future__ import annotations

import csv
from pathlib import Path

from pydantic import BaseModel

from core.fork import ROOT

REGISTRY = ROOT / "books" / "belem_vaults.csv"
DASHBOARD = "https://dune.com/rockawayxvault/rockawayx-dashboard"
EVM_CHAINS = {"ethereum": 1, "base": 8453, "bsc": 56}


class Vault(BaseModel):
    name: str
    address: str
    token: str
    chain: str
    protocol: str
    category: str
    tvl_usd: float                  # dashboard snapshot (source: registry), not a live read
    apy: float | None = None

    @property
    def key(self) -> str:
        return f"{self.chain}:{self.address.lower() if self.address.startswith('0x') else self.address}"


def load_vaults(path: Path = REGISTRY) -> list[Vault]:
    with open(path, newline="") as fh:
        rows = list(csv.DictReader(fh))
    out = [Vault(name=r["vault_name"], address=r["vault_address"], token=r["token_name"], chain=r["chain"],
                 protocol=r["protocol"], category=r["category"], tvl_usd=float(r["tvl_usd"]),
                 apy=float(r["apy"]) if r.get("apy") else None) for r in rows]
    return sorted(out, key=lambda v: -v.tvl_usd)


def total_tvl(vs: list[Vault] | None = None) -> float:
    return sum(v.tvl_usd for v in (vs or load_vaults()))


if __name__ == "__main__":
    vs = load_vaults()
    print(f"{len(vs)} vaults, ${total_tvl(vs) / 1e6:,.2f}M")
    for v in vs:
        print(f"  {v.chain:9s} {v.protocol:12s} ${v.tvl_usd / 1e6:7.2f}M  {v.name}")
