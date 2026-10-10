"""book.yaml: the portfolio input. Load Belem's reference portfolio the moment mentors share it.

    from core.book import load_book
    book = load_book("books/example_book.yaml")
"""
from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, model_validator


class Mandate(str, Enum):
    FUND = "fund"
    MANAGED_ACCOUNT = "managed_account"
    CURATED_VAULT = "curated_vault"


class LegType(str, Enum):
    HOLD = "hold"                              # token held outright (PT, LST, stable...)
    MORPHO_COLLATERAL = "morpho_collateral"    # collateral posted on a Morpho Blue market (+ optional borrow)
    MORPHO_SUPPLY = "morpho_supply"            # lender in a Morpho Blue market
    VAULT_DEPOSIT = "vault_deposit"            # ERC-4626 / MetaMorpho / Morpho Vault V2 / Kamino vault shares
    PENDLE_LP = "pendle_lp"
    OFFCHAIN_VENUE = "offchain_venue"          # capital at a perp exchange / CEX / credit facility


class Leg(BaseModel):
    type: LegType
    asset: str | None = None                   # token / vault address
    market_id: str | None = None               # Morpho market id
    amount: float | None = None                # token units (human), e.g. 1_000_000 PT
    amount_usd: float | None = None
    borrow_asset: str | None = None
    borrow_amount: float | None = None
    venue: str | None = None                   # for offchain_venue legs
    notes: str | None = None


class Position(BaseModel):
    id: str
    label: str
    chain: str = "ethereum"                    # ethereum | solana | base | arbitrum | canton | tempo ...
    mandate: Mandate = Mandate.FUND
    legs: list[Leg]
    size_usd: float | None = None
    size_source: str = "assumption"            # "assumption: <why>" | "belem_reference" | "onchain"
    pipeline: str | None = None                # discovery module, e.g. "discovery.hero1"
    tags: list[str] = Field(default_factory=list)


class Book(BaseModel):
    name: str
    owner: str                                 # whose book this is. Never present RockawayX figures as Belem's.
    base_currency: str = "USD"
    aum_usd: float                             # denominator for "bps of book"
    aum_source: str = "assumption"
    risk_aversion_lambda: float = 0.5          # lambda in E[L] + lambda*(CVaR95 - E[L])
    lambda_source: str = "assumption"
    fork_block: int | None = None
    positions: list[Position]
    meta: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _unique_ids(self):
        ids = [p.id for p in self.positions]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate position ids")
        return self

    def weight(self, pid: str) -> float | None:
        p = next(p for p in self.positions if p.id == pid)
        return p.size_usd / self.aum_usd if p.size_usd else None


def load_book(path: str | Path) -> Book:
    return Book.model_validate(yaml.safe_load(Path(path).read_text()))
