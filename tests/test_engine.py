"""Generic engine: surfaces, Monte Carlo determinism and the brief's own decision case."""
import numpy as np

from risk.engine import DecisionInputs, Driver, Scenario, Surface, breakeven_scale, decide, monte_carlo


def test_surface_monotone_and_anchored():
    s = Surface([(0.1, 0.02), (0.5, 0.01), (0.9, 0.3)])      # a noisy non-monotone point is lifted
    assert s(0.0) == 0.0
    assert s(0.5) >= s(0.1)
    assert np.isclose(s(1.0), 0.3)


def test_mc_deterministic_and_attribution_sums():
    D = {"a": Driver("a", "A", 1.0, [0.5], "market_disruption", "counterparty_defaults"),
         "b": Driver("b", "B", 0.5, [0.2, 0.9], "security_incident", "security_incidents")}
    sc = [Scenario("x", "X", "a", Surface([(0.5, 0.1)]), 0), Scenario("y", "Y", "b", Surface([(1.0, 1.0)]), 0)]
    r1, r2 = monte_carlo(D, sc, 30, 0.3), monte_carlo(D, sc, 30, 0.3)
    assert r1.el == r2.el and r1.cvar95 >= r1.var95 >= 0
    assert abs(sum(v["E[L]"] for v in r1.attribution.values()) - r1.el) < 1e-9   # no capping at 1 here


def test_brief_10_pockets_11pct_slippage():
    """Brief: 10 pockets x 10%, one affected, exit costs 11%. Risk-neutral (lambda=0): exit iff P x LGD > 11%."""
    book, pocket = 100e6, 10e6

    def net(p_lgd):
        d = DecisionInputs(pocket, book, 0.0, p_lgd, p_lgd, p_lgd, 30, lambda x, t: (0.11 * x * pocket, x * pocket),
                           pocket_var_limit=9.9)
        return next(g for g in decide(d)["grid"] if g["t_s"] == 0 and g["x"] == 1.0)["net_usd"]
    assert net(0.10) < 0 < net(0.12)
    k = breakeven_scale(lambda k: net(0.01 * k), hi=100)
    assert abs(k * 0.01 - 0.11) < 1e-3                 # breakeven belief: P x LGD = 11%


def test_cvar_is_worst_5pct_even_when_var_is_zero():
    D = {"a": Driver("a", "A", 0.3, [1.0], "market_disruption", "counterparty_defaults")}
    r = monte_carlo(D, [Scenario("x", "X", "a", Surface([(1.0, 0.5)]), 0)], 30, 0.0)
    assert r.var95 == 0.0 and r.cvar95 > r.el * 5          # ~2.4% of paths lose 50%: tail mean >> mean
