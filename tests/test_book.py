from core.book import load_book
from core.schemas import Headline, IncidentFamily, Shock, ShockKind


def test_example_book_loads():
    book = load_book("books/example_book.yaml")
    assert book.aum_usd > 0 and book.positions
    assert book.owner


def test_shock_requires_family():
    s = Shock(id="usde_-5", node_id="0x4c9e", kind=ShockKind.DEPEG, magnitude=-0.05,
              family=IncidentFamily.MARKET_DISRUPTION)
    assert s.family == IncidentFamily.MARKET_DISRUPTION
    assert "net_value_exit_bps_book" in Headline.model_fields


def test_belem_assumed_book_respects_caps_and_parks_excess():
    from core.book_builder import build
    b = build(offline=True)
    pos = {p["id"]: p for p in b["positions"]}
    assert len(pos) == 10 and abs(sum(p["size_usd"] for p in pos.values()) - b["mandate_usd"]) < 1
    assert all(p["size_usd"] <= 5_000_000 + 1 for k, p in pos.items() if k != "P6")
    constrained = [k for k, p in pos.items() if p["capacity_constrained"]]
    parked = sum(p["requested_usd"] - p["size_usd"] for k, p in pos.items() if k in constrained)
    assert abs(pos["P6"]["size_usd"] - (pos["P6"]["requested_usd"] + parked)) < 1
    assert all(p["verification"] for p in pos.values())                     # every pocket verified
    assert "belem_rockawayx" in pos["P5"]["tags"] and pos["P5"]["mandate"] == "curated_vault"
