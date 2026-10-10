"""The shared Ethena dependency between P1/P2/P3 must be FOUND by the X-ray, not configured anywhere."""
import pytest
import yaml

from core.book import load_book
from core.fork import ROOT
from discovery import disclosures
from discovery.pockets import load_pocket_graphs
from discovery.xray import xray

USDE = disclosures.USDE
BOOK = ROOT / "books" / "belem_assumed_book.yaml"


@pytest.fixture(scope="module")
def res():
    book = load_book(BOOK)
    return xray(book, load_pocket_graphs(book))


def test_not_hardcoded():
    # the book only names each pocket's own asset; nothing ties P3 (sUSDe) to USDe or to P1/P2
    # inputs only (verification logs record on-chain reads such as sUSDe.asset() and are evidence, not inputs)
    book = yaml.safe_load(BOOK.read_text())
    inputs = str([{k: p[k] for k in ("legs", "label", "tags")} for p in book["positions"]]).lower()
    assert USDE not in inputs and "usde\"" not in inputs and "ethena labs" not in inputs
    p3 = next(p for p in load_book(BOOK).positions if p.id == "P3")
    assert [l.asset.lower() for l in p3.legs] == [disclosures.SUSDE]
    # disclosures are keyed by asset address, never by pocket id
    assert all(k.startswith("0x") or len(k) > 30 for k in disclosures.REGISTRY)


def test_xray_finds_shared_ethena(res):
    usde = next(s for s in res["shared_ancestors"] if s["id"] == USDE)
    assert {"P1", "P2", "P3"} <= set(usde["pockets"])
    # each pocket reaches USDe through executed/on-chain evidence, not through a disclosure edge
    for p in ("P1", "P2", "P3"):
        hops = usde["how"][p]
        assert hops and all("disclosure" not in h["sources"] for h in hops), (p, hops)
        assert any({"trace", "onchain_read", "storage"} & set(h["sources"]) for h in hops), (p, hops)
    bet = next(b for b in res["bets"] if "P3" in b["pockets"])
    assert {"P1", "P2", "P3"} <= set(bet["pockets"])


def test_effective_bets_below_pockets(res):
    assert res["n_pockets"] == 10 and res["effective_independent_bets"] < res["n_pockets"]
    assert res["worst_single_point_of_failure"] is not None


def test_book_xray_adds_up_and_labels_coverage():
    import json
    from core.fork import ROOT
    bx = json.loads((ROOT / "data" / "book_xray.json").read_text())
    assert abs(sum(g["usd"] for g in bx["groups"]) - bx["book_usd"]) < 1e3          # every $ of the book attributed once
    assert bx["coverage"]["n_resolved"] == sum(1 for v in bx["vaults"] if v["protocol"] == "morpho")
    assert all(not v["resolved"] for v in bx["vaults"] if v["protocol"] != "morpho")
