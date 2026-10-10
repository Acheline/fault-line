"""Hero #1 (light) on the shared engine, from cached fork runs."""
from decision import hero1 as D1
from risk import scenarios_hero1 as S1

D = S1.load()


def test_usde_depeg_goes_through_the_metaoracle_switch():
    for r in D["usde_depeg"]:
        assert r["frozen_phase"]["liquidated"] is False                      # schedule oracle: no liquidation at first
        assert r["switch"]["steps"].get("acceptChallenge()") == "ok" and r["switch"]["is_backup"]
    assert [r["after_switch"]["liquidated"] for r in D["usde_depeg"]] == [False, False, False, True]
    assert D["usde_depeg"][0]["time_to_liquidation_s"] == 57600              # challengeTimelockDuration, read on-chain


def test_oracle_shocks_within_buffer_and_lp_shock_costs_more():
    assert not any(r["liquidated"] for r in D["oracle_shock"])               # HF 1.25 at target LTV
    ex = [r["extra_exit_cost"] for r in D["pendle_liquidity"]]
    assert ex[1] > ex[0] > 0


def test_headline_consistent():
    h = D1.headline(with_tornado=False)
    assert h["action"] in ("STAY", "REDUCE", "EXIT")
    c = h["components_full_exit_now"]
    assert abs(c["net_usd"] - (c["loss_avoided_usd"] - c["yield_forgone_usd"] - c["exit_cost_usd"])) < 1e-6
    assert D1.headline(incident=0.10, lam=0.0, with_tornado=False)["action"] != "STAY"
