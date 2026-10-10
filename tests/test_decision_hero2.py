"""Hero #2 decision layer, from cached fork measurements (offline)."""
import json

from core.fork import ROOT
from decision import hero2 as D2

SH = json.loads((ROOT / "data" / "shocks" / "hero2.json").read_text())


def test_trusd_frozen_oracle_is_silent_bad_debt():
    row = next(r for r in SH["measured"]["trusd_frozen"] if abs(r["severity"] - 0.5) < 1e-9)
    assert row["loss_per_share"] > 0.01                         # real economic loss for depositors
    assert abs(row["recognized_loss_per_share"] or 0) < 1e-4    # but the vault share price does not move
    assert all(l["n_liquidated"] == 0 for l in row["legs"])     # nobody can be liquidated at a frozen oracle


def test_surfaces_monotone_in_severity():
    for sid, rows in SH["measured"].items():
        losses = [r["loss_per_share"] for r in sorted(rows, key=lambda r: r["severity"])]
        assert all(b >= a - 1e-6 for a, b in zip(losses, losses[1:])), sid


def test_headline_consistent():
    h = D2.headline(with_tornado=False)
    assert h["action"] in ("STAY", "REDUCE", "EXIT")
    assert h["loss_usd"]["CVaR95"] >= h["loss_usd"]["VaR95"] >= 0
    assert abs(h["net_value_exit_now_bps_book"] - h["net_value_exit_now_usd"] / h["book_usd"] * 1e4) < 1e-6
    by = h["exit_race"]["by_time"]
    assert by["0m"]["recovered_pct"] <= by["1h"]["recovered_pct"] <= by["24h"]["recovered_pct"]


def test_queue_rank_and_governance_penalty():
    first = D2.headline(rank=1, with_tornado=False)["exit_race"]["by_time"]["0m"]
    late = D2.headline(rank=5, with_tornado=False)["exit_race"]["by_time"]["0m"]
    assert first["recovered_pct"] >= late["recovered_pct"]
    gov = D2.headline(rank=1, governance=True, with_tornado=False)["exit_race"]["by_time"]["0m"]
    assert gov["penalty_usd"] >= first["penalty_usd"]
