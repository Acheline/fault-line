"""Hero #1 discovery must find: Pendle market, SY, sUSDe/USDe, the Morpho market's oracle + its underlying
feeds, and the proxy admins. Runs from the on-disk cache (offline) so it works without an RPC."""
import pytest

from core import addresses as A
from core.schemas import CriticalPath, EdgeType, NodeType
from discovery import hero1

H = A.HERO1


@pytest.fixture(scope="module")
def g():
    return hero1.build(offline=True)


def test_pendle_stack(g):
    for a in (H["pendle_market"], H["sy"], H["pt"], H["susde"], H["usde"]):
        assert a.lower() in g.nodes, a
    assert g.nodes[H["pendle_market"].lower()].type == NodeType.LIQUIDITY_VENUE
    assert {CriticalPath.EXIT, CriticalPath.VALUE} <= g.nodes[H["pendle_market"].lower()].paths


def test_morpho_oracle_and_feeds(g):
    orc = H["morpho_oracle"].lower()
    assert g.nodes[orc].type == NodeType.ORACLE
    feeds = {n.props.get("contract_name") for n in g.nodes.values() if n.type == NodeType.ORACLE}
    assert {"MorphoChainlinkOracleV2", "PendleSparkLinearDiscountOracle"} <= feeds
    assert H["usde_usd_feed"].lower() in g.nodes          # via backupOracle()
    assert any(f["kind"] == "fixed_schedule_oracle" for f in g.meta["findings"])
    assert any(f["kind"] == "oracle_switch_timelock" for f in g.meta["findings"])


def test_proxy_admins_found(g):
    proxies = [n for n in g.nodes.values() if "proxy" in n.tags and n.props.get("proxy_admin")]
    assert proxies
    for p in proxies:
        assert any(e.src == p.id and e.type == EdgeType.GOVERNS for e in g.edges.values()), p.label


def test_paths_executed(g):
    assert g.meta["exit"]["usdc_out"] and g.meta["exit"]["usdc_out"] > 0.9 * H["exit_size_pt"] / 1e18
    assert g.meta["liquidation"]["seized_pt"] > 0 and not g.meta["liquidation"]["error"]


def test_deeper_than_brief(g):
    assert len(g.meta["depth"]["asset_stack"]) - 1 > 5


def test_mapped_onto_brief_layers(g):
    from discovery.report import BRIEF_LAYERS
    layers = g.meta["brief_layers"]
    for layer in BRIEF_LAYERS:
        assert layers[layer], f"nothing mapped to {layer}"
    assert all("brief_layer" in n.props for n in g.nodes.values() if n.type != NodeType.POSITION)
    beyond = [k for k in layers if k.startswith("+") and layers[k]]
    assert len(beyond) >= 3                  # extra layers found beyond the brief's picture


def test_oracle_feed_quality(g):
    oq = g.meta["oracle_quality"]
    pp = oq["position_price_path"]
    assert pp["n_market_derived_sources"] == 0 and "flag" in pp      # scenario (d): no/single market feed
    usde = next(o for o in oq["oracles"] if o["id"] == H["usde_usd_feed"].lower())
    assert usde["kind"] == "market_derived" and usde["n_updates_30d"] > 0 and usde["heartbeat_s_observed"]
    assert all("who_can_change" in o for o in oq["oracles"])


def test_tvl_concentration(g):
    conc = {r["protocol"]: r for r in g.meta["tvl_concentration"]}
    assert {"morpho-blue", "pendle-v2", "ethena-usde"} <= set(conc)
    assert all(0 <= r["share_of_chain"] < 1 for r in conc.values())
