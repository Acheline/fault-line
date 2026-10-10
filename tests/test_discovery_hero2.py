"""Hero #2 discovery (Belem / RockawayX USDC Yield vault) must find every market the vault allocates to, each
market's oracle and collateral, and the vault's owner / curator / allocators / sentinels / timelocks. The expected
set is read from the vault itself (adapter.marketIds), not typed here. Runs offline from the on-disk cache."""
import pytest

from core import addresses as A
from core.fork import Fork
from core.schemas import CriticalPath, EdgeType, NodeType
from discovery import hero2

V = A.HERO2["vault"].lower()


@pytest.fixture(scope="module")
def g():
    return hero2.build(offline=True)


@pytest.fixture(scope="module")
def market_ids():
    f = Fork(offline=True)
    f.fork_block = A.FORK_BLOCK
    ids = set()
    for i in range(f.call1(V, "adaptersLength()", "uint256")):
        ad = f.call1(V, "adapters(uint256)", "address", ["uint256"], [i])
        for j in range(f.call1(ad, "marketIdsLength()", "uint256")):
            ids.add("0x" + f.call1(ad, "marketIds(uint256)", "bytes32", ["uint256"], [j]).hex())
    return ids


def test_every_market_with_oracle_and_collateral(g, market_ids):
    assert market_ids
    for mid in market_ids:
        mn = f"morpho_market:{mid}"
        assert g.nodes[mn].type == NodeType.LENDING_MARKET
        out = {(e.type, e.dst) for e in g.edges.values() if e.src == mn}
        orc = [d for t, d in out if t == EdgeType.PRICES]
        coll = [d for t, d in out if t == EdgeType.USES_COLLATERAL]
        assert orc and g.nodes[orc[0]].type == NodeType.ORACLE, mid
        assert coll and g.nodes[coll[0]].type == NodeType.ASSET, mid
        assert CriticalPath.LIQUIDATION in g.nodes[mn].paths
    assert {m["market_id"] for m in g.meta["q1"]["markets"]} == market_ids
    assert abs(sum(m["allocation_pct"] for m in g.meta["q1"]["markets"]) - 1) < 0.01


def test_roles_and_timelocks(g):
    r = g.meta["q1"]["roles"]
    gov = {e.dst for e in g.edges.values() if e.src == V and e.type == EdgeType.GOVERNS}
    for a in [r["owner"], r["curator"], *r["allocators"], *r["sentinels"]]:
        assert a in gov
    assert r["allocators"] and r["sentinels"]
    assert "safe" in g.nodes[r["owner"]].tags
    assert r["timelocks"]["addAdapter"]["timelock_s"] is not None


def test_three_questions_measured(g):
    q2, q3 = g.meta["q2"], g.meta["q3"]
    assert all(rec["shocks"] for rec in q2 if rec["n_borrowers_read"])
    # bad debt is monotone in the size of the oracle drop
    for rec in q2:
        bd = [s["bad_debt_vault_usd"] for s in rec["shocks"]]
        assert bd == sorted(bd), rec["market"]
    run = q3["run"]["ranks"]
    assert run and run[0]["recovered_pct"] >= run[-1]["recovered_pct"]     # first out recovers the most
    assert q3["withdrawable_now"]["liquidity_market"]


def test_label(g):
    assert g.meta["label"] == "Belem / RockawayX vaults"
