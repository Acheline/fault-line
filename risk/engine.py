"""Generic impact + decision engine (Module 2 Monte Carlo, Module 3 decision rule). Position-agnostic: a position
provides scenarios (a driver + a response surface measured on the fork) and an exit-cost function; the engine
returns E[L], VaR95, CVaR95, attribution, a tornado and the headline.

  Driver     a source of risk with a probability of occurring within the horizon and a severity distribution, both
             from computed base rates (risk/base_rates.py): e.g. "trUSD depeg", "Morpho Blue exploit".
  Surface    loss per $ of position as a function of the driver's severity, interpolated from fork runs
             (monotone piecewise-linear through the measured points).
  Scenario   driver x surface (several scenarios can share a driver: one trUSD draw hits strUSD and PT-strUSD).

Correlation: driver occurrences are coupled through a one-factor Gaussian copula with correlation rho (assumption).
Severity is drawn independently per driver from its empirical distribution. Deterministic seed.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable

import numpy as np
from scipy.stats import norm

SEED = 7
N_PATHS = 10_000
TIME_GRID_S = {"0m": 0, "15m": 900, "1h": 3600, "6h": 21600, "24h": 86400}


@dataclass
class Driver:
    id: str
    label: str
    annual_rate: float                      # events per year (computed base rate)
    severities: list[float]                 # empirical severities in [0, 1] (e.g. 1 - depeg trough)
    family: str                             # security_incident | market_disruption | technical_failure
    kpi: str                                # security_incidents | counterparty_defaults | liquidations
    source: str = ""
    badge: str | None = None                # "placeholder_prior" / "proxy" when not computed from its own data

    def p_within(self, horizon_days: float) -> float:
        return 1 - math.exp(-self.annual_rate * horizon_days / 365.25)


@dataclass
class Surface:
    """loss(severity) per $ of position, from measured points [(severity, loss)]. Monotone, loss(0)=0."""
    points: list[tuple[float, float]]
    measured_on: str = "fork"

    def __post_init__(self):
        pts = sorted({(0.0, 0.0), *[(float(s), float(l)) for s, l in self.points]})
        xs, ys = [p[0] for p in pts], np.maximum.accumulate([p[1] for p in pts])   # isotonic (non-decreasing)
        self.xs, self.ys = np.array(xs), np.array(ys)

    def __call__(self, s):
        return np.interp(np.clip(s, 0, 1), self.xs, self.ys, right=self.ys[-1])


@dataclass
class Scenario:
    id: str
    label: str
    driver: str
    surface: Surface
    time_to_impact_s: float
    confidence: str = "high"                # high | medium | low (shown in the UI)
    group: str = ""                         # attribution bucket, e.g. the market
    notes: str = ""


@dataclass
class MCResult:
    losses: np.ndarray                      # per path, loss per $ of position
    by_scenario: dict[str, np.ndarray]
    horizon_days: float
    rho: float
    el: float = 0.0
    var95: float = 0.0
    cvar95: float = 0.0
    attribution: dict[str, dict] = field(default_factory=dict)

    def summary(self) -> dict:
        return {"E[L]": self.el, "VaR95": self.var95, "CVaR95": self.cvar95, "horizon_days": self.horizon_days,
                "rho": self.rho, "p_any_loss": float((self.losses > 0).mean()), "attribution": self.attribution}


def monte_carlo(drivers: dict[str, Driver], scenarios: list[Scenario], horizon_days: float, rho: float = 0.3,
                n: int = N_PATHS, seed: int = SEED, rate_scale: dict[str, float] | None = None,
                severity_scale: float = 1.0, condition: dict[str, float] | None = None,
                loss_scale: dict[str, float] | None = None) -> MCResult:
    """condition {driver: s}: the event is OBSERVED at depth s; it occurs with probability 1 and its final depth is
    drawn from the empirical episodes that went at least that deep. loss_scale {scenario: k}: multiplies a scenario's
    loss (e.g. silent bad debt concentrated on the holders who did not exit at par)."""
    rng = np.random.default_rng(seed)
    ids = sorted({s.driver for s in scenarios})
    z = rng.standard_normal(n)
    occurs, sev = {}, {}
    for d in ids:
        dr = drivers[d]
        p = 1 - math.exp(-dr.annual_rate * (rate_scale or {}).get(d, 1.0) * horizon_days / 365.25)
        e = math.sqrt(rho) * z + math.sqrt(1 - rho) * rng.standard_normal(n)
        occurs[d] = norm.cdf(e) < p
        s = np.array(dr.severities or [0.0])
        if condition and d in condition:
            occurs[d] = np.ones(n, dtype=bool)
            s = s[s >= condition[d]] if (s >= condition[d]).any() else np.array([condition[d]])
        sev[d] = np.clip(rng.choice(s, size=n) * severity_scale, 0, 1)
    by = {}
    for sc in scenarios:
        by[sc.id] = np.where(occurs[sc.driver], sc.surface(sev[sc.driver]), 0.0) * (loss_scale or {}).get(sc.id, 1.0)
    tot = np.clip(sum(by.values()) if by else np.zeros(n), 0, 1)
    r = MCResult(losses=tot, by_scenario=by, horizon_days=horizon_days, rho=rho)
    r.el = float(tot.mean())
    r.var95 = float(np.quantile(tot, 0.95))
    # CVaR95 = mean of the worst 5% of paths (by rank, so ties at VaR = 0 do not pull in the whole distribution)
    k = max(1, int(math.ceil(0.05 * n)))
    tail = np.zeros(n, dtype=bool)
    tail[np.argsort(tot, kind="stable")[-k:]] = True
    r.cvar95 = float(tot[tail].mean())
    for sc in scenarios:
        v = by[sc.id]
        r.attribution[sc.id] = {"label": sc.label, "group": sc.group, "driver": sc.driver,
                                "E[L]": float(v.mean()), "share_of_EL": float(v.mean() / r.el) if r.el else 0.0,
                                "CVaR_contrib": float(v[tail].mean()) if tail.any() else 0.0,
                                "time_to_impact_s": sc.time_to_impact_s, "confidence": sc.confidence}
    return r


# ---------------------------------------------------------------------------------------------- decision rule
@dataclass
class DecisionInputs:
    size_usd: float                         # position size S
    book_usd: float                         # denominator for bps of book
    lam: float                              # risk aversion: E[L] + lam * (CVaR95 - E[L])
    el: float                               # per $ over the horizon
    cvar95: float
    var95: float
    horizon_days: float
    exit_cost: Callable[[float, float], tuple[float, float]]   # (fraction x, t seconds) -> ($ cost, $ exitable)
    pocket_var_limit: float = 0.20          # ASSUMED_ANSWERS §3 hard budget
    fractions: tuple = (0.0, 0.25, 0.5, 0.75, 1.0)
    carry_per_usd: float = 0.0              # yield earned by staying over the horizon, per $ (forgone if you exit)


def risk_adjusted(el: float, cvar: float, lam: float) -> float:
    return el + lam * (cvar - el)


def decide(d: DecisionInputs) -> dict:
    """EXIT x% at t* maximizing  ([E[L] + lam (CVaR - E[L])] - carry) * exited$ * (remaining horizon) - C_exit(x, t).
    Net value of exiting = risk-adjusted expected loss avoided - yield forgone - exit cost."""
    ra = risk_adjusted(d.el, d.cvar95, d.lam)
    grid = []
    for t_label, t in TIME_GRID_S.items():
        remaining = max(0.0, 1 - t / (d.horizon_days * 86400))      # Poisson arrivals: loss avoided after t only
        for x in d.fractions:
            cost, exitable = d.exit_cost(x, t)
            avoided = ra * exitable * remaining
            forgone = d.carry_per_usd * exitable * remaining
            grid.append({"t": t_label, "t_s": t, "x": x, "exited_usd": exitable, "loss_avoided_usd": avoided,
                         "yield_forgone_usd": forgone, "exit_cost_usd": cost, "net_usd": avoided - forgone - cost})
    best = max(grid, key=lambda g: (round(g["net_usd"], 6), -g["t_s"]))
    now = max((g for g in grid if g["t_s"] == 0), key=lambda g: g["net_usd"])
    hard = d.var95 > d.pocket_var_limit
    full_now = next(g for g in grid if g["t_s"] == 0 and g["x"] == 1.0)
    locked = full_now["exited_usd"] <= 0          # nothing can leave now (liquidity ahead of you exhausted)
    x = now["x"]
    if hard and x < 0.5 and not locked:
        alt = next(g for g in grid if g["t_s"] == 0 and g["x"] == 0.5)
        now, x = alt, 0.5
    action = "STAY" if x == 0 or now["net_usd"] <= 0 or locked else ("EXIT" if x == 1.0 else "REDUCE")
    if hard and action == "STAY" and not locked:
        action = "REDUCE"
    return {"action": action, "exit_fraction": x if action != "STAY" else 0.0, "now": now, "best": best,
            "locked": locked,
            "grid": grid, "risk_adjusted_loss_per_usd": ra, "hard_budget_hit": hard,
            "net_value_exit_now_usd": now["net_usd"] if action != "STAY" else
            max((g for g in grid if g["t_s"] == 0 and g["x"] == 1.0), key=lambda g: g["net_usd"])["net_usd"],
            "bps_of_book": (now["net_usd"] if action != "STAY" else
                            next(g for g in grid if g["t_s"] == 0 and g["x"] == 1.0)["net_usd"]) / d.book_usd * 1e4}


def breakeven_scale(fn_net: Callable[[float], float], lo: float = 0.0, hi: float = 50.0, iters: int = 40) -> float | None:
    """Smallest multiplier k on a driver's probability at which net value of exiting now crosses 0 (bisection)."""
    if fn_net(hi) <= 0:
        return None
    if fn_net(lo) > 0:
        return lo
    for _ in range(iters):
        mid = (lo + hi) / 2
        lo, hi = (lo, mid) if fn_net(mid) > 0 else (mid, hi)
    return hi


def tornado(base: float, fn: Callable[[str, float], float], ranges: dict[str, tuple[float, float, str]],
            top: int = 5) -> list[dict]:
    """ranges: {name: (low, high, source)}; fn(name, value) -> metric with that one assumption moved."""
    rows = []
    for k, (lo, hi, src) in ranges.items():
        a, b = fn(k, lo), fn(k, hi)
        rows.append({"assumption": k, "low": lo, "high": hi, "metric_low": a, "metric_high": b,
                     "swing": abs(b - a), "source": src})
    return [dict(r, base=base) for r in sorted(rows, key=lambda r: -r["swing"])[:top]]
