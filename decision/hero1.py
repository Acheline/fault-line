"""Hero #1 headline (light): PT-sUSDe outright (P1) + Morpho loop (P2), on the same engine as hero #2.

  loss surfaces    risk/scenarios_hero1 (fork: USDe depeg through the MetaOracle switch, oracle shock, LP withdrawal)
  exit cost        PT -> sUSDe (Pendle router) -> USDC (Kyber), executed on the fork at 0.25/0.5/1/2x; tranches at
                   ASSUMED_ANSWERS §5 times {0, 15 min, 1 h, 6 h} (max 4): n tranches cost n x cost(size / n),
                   assuming liquidity refills between tranches (assumption, labelled)
  carry            P1: the PT's implied APY; P2: leverage x implied APY - (leverage - 1) x Morpho borrow APR (both read live)
"""
from __future__ import annotations

import numpy as np

from core.config import cfg
from risk import scenarios_hero1 as S1
from risk.engine import TIME_GRID_S, DecisionInputs, breakeven_scale, decide, monte_carlo, tornado

_C: dict = {}


def static() -> dict:
    if not _C:
        d = S1.load()
        D, sc = S1.build(d)
        _C.update(data=d, D=D, sc=sc)
    return _C


def exit_cost_fraction(curve: list[dict], usd: float) -> float:
    """Measured cost (fraction of oracle value) at `usd` sold, interpolated on executed points."""
    pts = sorted((c["oracle_value_usd"], c["cost"]) for c in curve if c["cost"] is not None)
    if not pts:
        return 0.0
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    if usd > xs[-1]:          # beyond the largest executed size: extrapolate on the last slope (flagged in the UI)
        k = (ys[-1] - ys[-2]) / (xs[-1] - xs[-2]) if len(xs) > 1 and xs[-1] != xs[-2] else 0.0
        return ys[-1] + k * (usd - xs[-1])
    return float(np.interp(usd, xs, ys))


def headline(scale: float = 1.0, lam: float | None = None, horizon_days: float = 30, rho: float = 0.3,
             incident: float | None = None, rate_scale: float = 1.0, severity_scale: float = 1.0,
             with_tornado: bool = True) -> dict:
    """scale: position size as a multiple of the assumed book (P1 + P2). incident: an OBSERVED USDe depeg depth."""
    s = static()
    d, D, sc = s["data"], s["D"], s["sc"]
    c = cfg()
    lam = c["risk"]["lambda"] if lam is None else lam
    book = c["mandate"]["mandate_usd"]
    sz = d["sizes"]
    lev = sz["loop"]["gross_leverage"]
    p1, p2 = sz["p1_usd"] * scale, sz["p2_equity_usd"] * scale
    size = p1 + p2
    pt_sold = p1 + p2 * lev                                      # PT to sell for a full unwind (P2 repays its debt)
    apy, br = d.get("pt_implied_apy") or 0.0, d.get("borrow_apr") or 0.0
    carry_apy = (p1 * apy + p2 * (lev * apy - (lev - 1) * br)) / size
    carry = carry_apy * horizon_days / 365.25
    tranche_t = c["exit"]["tranche_times_minutes"]
    cond = {"usde": incident} if incident is not None else None

    def mc_run(rs=rate_scale, sv=severity_scale, rh=rho):
        return monte_carlo(D, sc, horizon_days, rh, rate_scale={k: rs for k in D}, severity_scale=sv, condition=cond)

    def exit_cost(x, t):
        if x == 0:
            return 0.0, 0.0
        n = max(1, min(c["exit"]["max_tranches"], sum(1 for m in tranche_t if m * 60 <= t)))
        sold = x * pt_sold
        cost = n * exit_cost_fraction(d["exit_curve"], sold / n) * (sold / n)
        return cost, x * size

    def decision(mc, lam_=lam):
        return decide(DecisionInputs(size, book, lam_, mc.el, mc.cvar95, mc.var95, horizon_days, exit_cost,
                                     c["risk"]["pocket_var95_hard_limit"], carry_per_usd=carry))
    mc = mc_run()
    dec = decision(mc)
    contrib = {k: v["E[L]"] + lam * (v["CVaR_contrib"] - v["E[L]"]) for k, v in mc.attribution.items()}
    top = max(contrib, key=contrib.get)
    top_sc = next(x for x in sc if x.id == top)
    now_full = next(g for g in dec["grid"] if g["t_s"] == 0 and g["x"] == 1.0)

    def net_full(k):
        g = decision(mc_run(rs=rate_scale * k))["grid"]
        return next(x for x in g if x["t_s"] == 0 and x["x"] == 1.0)["net_usd"]
    kstar = breakeven_scale(net_full, hi=20.0) if with_tornado and incident is None else None
    usde_liq = next((r for r in d["usde_depeg"] if r["after_switch"]["liquidated"]), None)
    out = {"scope": "hero1", "size_usd": size, "p1_usd": p1, "p2_equity_usd": p2, "leverage": lev,
           "lambda": lam, "horizon_days": horizon_days, "incident": incident,
           "action": dec["action"], "exit_fraction": dec["exit_fraction"],
           "net_value_exit_now_usd": dec["net_value_exit_now_usd"], "net_value_exit_now_bps_book": dec["bps_of_book"],
           "bps_basis": f"assumed mandate ${book / 1e6:,.0f}M",
           "net_value_exit_now_bps_aum": dec["net_value_exit_now_usd"] / c["mandate"]["aum_usd"] * 1e4,
           "components_full_exit_now": {k: now_full[k] for k in ("exited_usd", "loss_avoided_usd", "yield_forgone_usd",
                                                                 "exit_cost_usd", "net_usd")},
           "carry": {"apy": carry_apy, "pt_implied_apy": apy, "borrow_apr": br},
           "mc": mc.summary(), "loss_usd": {"E[L]": mc.el * size, "VaR95": mc.var95 * size, "CVaR95": mc.cvar95 * size},
           "driver": {"scenario": top, "label": top_sc.label, "driver": D[top_sc.driver].label,
                      "share_of_risk_adjusted_loss": contrib[top] / sum(contrib.values()) if sum(contrib.values()) else None,
                      "time_to_impact_s": top_sc.time_to_impact_s, "notes": top_sc.notes, "confidence": top_sc.confidence},
           "time_to_liquidation_s": d["usde_depeg"][0]["time_to_liquidation_s"] if d["usde_depeg"] else None,
           "liquidated_at_usde_depeg": usde_liq["severity"] if usde_liq else None,
           "breakeven": {"event": f"a loss-making incident within {horizon_days:.0f} days",
                         "rate_multiplier": kstar,
                         "p_breakeven": mc_run(rs=rate_scale * kstar).summary()["p_any_loss"] if kstar is not None else None,
                         "p_estimate": mc.summary()["p_any_loss"]},
           "exit_cost_curve": {k: exit_cost(1.0, t)[0] for k, t in TIME_GRID_S.items()},
           "grid": dec["grid"]}
    out["reason"] = [
        f"#1 driver: {out['driver']['label']} ({(out['driver']['share_of_risk_adjusted_loss'] or 0):.0%} of risk-adjusted "
        f"loss): PT-sUSDe → SY → sUSDe → USDe; the Morpho oracle follows a schedule, so the loop is only liquidated "
        f"after the {out['time_to_liquidation_s'] / 3600:.0f} h challenge timelock (liquidated on the fork at USDe "
        f"−{(out['liquidated_at_usde_depeg'] or 0):.0%}).",
        f"Expected loss ${out['loss_usd']['E[L]']:,.0f}, CVaR95 ${out['loss_usd']['CVaR95']:,.0f} on ${size:,.0f} "
        f"({lev:.2f}x loop) vs carry {carry_apy:.2%}/yr.",
        f"Exit now costs ${now_full['exit_cost_usd']:,.0f} (executed Pendle + Kyber routes); "
        f"4 tranches over 6 h: ${out['exit_cost_curve']['6h']:,.0f}.",
    ]
    if with_tornado:
        base = out["net_value_exit_now_usd"]

        def f(name, v):
            kw = dict(scale=scale, lam=lam, horizon_days=horizon_days, rho=rho, incident=incident, rate_scale=rate_scale,
                      severity_scale=severity_scale, with_tornado=False)
            kw[name] = v
            return headline(**kw)["net_value_exit_now_usd"]
        out["tornado"] = tornado(base, f, {
            "rate_scale": (0.5, 2.0, "base-rate frequency x0.5 / x2"), "severity_scale": (0.5, 1.5, "depth x0.5 / x1.5"),
            "rho": (0.0, 0.8, "copula correlation (assumption)"), "lam": (0.0, 1.0, "risk aversion (ASSUMED_ANSWERS §3)"),
            "horizon_days": (7, 90, "decision horizon (assumption)")})
    return out
