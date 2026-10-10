"""Collapsed demo graph: small, complete (every node lands in one group), keeps the flags and critical paths."""
from pathlib import Path

import pytest

from core.fork import ROOT
from discovery.viz import FLAG_TAGS, build_html, collapse, load_graph

GRAPHS = ROOT / "data" / "graphs"


@pytest.mark.parametrize("name", ["hero1", "hero3"])
def test_collapse_is_small_and_complete(name):
    p = GRAPHS / f"{name}.json"
    if not p.exists():
        pytest.skip(f"{p} not built")
    g = load_graph(Path(p))
    c = collapse(g)
    assert len(c.nodes) <= 25
    assert all(e.src in c.nodes and e.dst in c.nodes and e.src != e.dst for e in c.edges.values())
    # flags and critical paths survive the grouping
    assert set().union(*(n.tags & FLAG_TAGS for n in g.nodes.values())) <= set().union(*(n.tags for n in c.nodes.values()))
    assert set().union(*(n.paths for n in g.nodes.values())) <= set().union(*(n.paths for n in c.nodes.values()))
    assert "fl-legend" in build_html(c, "500px", compact=True)


def test_hero1_collapse_keeps_the_brief_stack():
    p = GRAPHS / "hero1.json"
    if not p.exists():
        pytest.skip("hero1 graph not built")
    labels = {n.label.split(" · ")[0] for n in collapse(load_graph(p)).nodes.values()}
    for want in ("PT-sUSDE-26NOV2026", "SY-sUSDE", "sUSDe", "USDe", "USDC", "MetaOracleDeviationTimelock",
                 "PendleSparkLinearDiscountOracle"):
        assert want in labels, want
