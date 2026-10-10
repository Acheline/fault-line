from core.book import load_book
from core.schemas import Headline, IncidentFamily, Shock, ShockKind


def test_example_book_loads():
    book = load_book("books/example_book.yaml")
    assert book.aum_usd > 0 and book.positions
    assert "Belem" not in book.owner or "NOT Belem" in book.owner


def test_shock_requires_family():
    s = Shock(id="usde_-5", node_id="0x4c9e", kind=ShockKind.DEPEG, magnitude=-0.05,
              family=IncidentFamily.MARKET_DISRUPTION)
    assert s.family == IncidentFamily.MARKET_DISRUPTION
    assert "net_value_exit_bps_book" in Headline.model_fields
