"""Hero #2 headline: net value of exiting the Belem / RockawayX USDC Yield vault now, for a depositor of size S at
rank q in the exit queue. Everything is recomputed from cached fork measurements, so the UI sliders are live.

    from decision.hero2 import headline
    h = headline(size_usd=2.78e6, rank=1)

    python -m decision.hero2 [--offline]   -> measures the governance run on the fork, writes data/headline/hero2.json
"""
from __future__ import annotations

import json
import sys

from core import addresses as A
from core.config import cfg
from core.fork import ROOT, Fork
from core.vaults import load_vaults
from risk import exit_race as ER
from risk import scenarios_hero2 as S2
from risk.engine import TIME_GRID_S, DecisionInputs, breakeven_scale, decide, monte_carlo, tornado

OUT = ROOT / "data" / "headline" / "hero2_measured.json"
HEADLINE = ROOT / "data" / "headline" / "hero2.json"
DEFAULT_HORIZON_DAYS = 30        # assumption: decision horizon = re-check cadence of a monthly risk review


def _static() -> dict:
    meta, lr = ER.load_inputs()
    st = json.loads(OUT.read_text()) if OUT.exists() else {}
    D, sc = S2.build()
    reg = next((v for v in load_vaults() if v.address.lower() == meta["vault"]), None)
    return {"meta": meta, "lr": lr, "D": D, "sc": sc, "measured": st, "vault_apy": reg.apy if reg else None}


_CACHE: dict = {}


def static() -> dict:
    if not _CACHE:
        _CACHE.update(_static())
    return _CACHE


def headline(size_usd: float | None = None, rank: int = 1, lam: float | None = None,
             horizon_days: float = DEFAULT_HORIZON_DAYS, rho: float = 0.3, governance: bool = False,
             rate_scale: float = 1.0, severity_scale: float = 1.0, refill_scale: float = 1.0,
             vault_claim_share: float | None = None, book_usd: float | None = None, with_tornado: bool = True) -> dict:
    s = static()
    c = cfg()
    meta, D, sc = s["meta"], s["D"], s["sc"]
    lam = c["risk"]["lambda"] if lam is None else lam
    book_usd = book_usd or c["mandate"]["aum_usd"]
    r = meta["q1"]["roles"]
    tot = r["total_assets_usd"]
    size = size_usd or min(c["sizing"]["ticket_usd"], c["sizing"]["max_share_curated_vault_tvl"] * tot)
    pen0 = max(r["force_deallocate_penalty"].values() or [0])
    pen = 0.02 if governance else pen0
    deps = meta["q3"]["top_depositors"]
    mk = ER.markets_from(meta, s["lr"], vault_claim_share)
    idle = meta["q1"].get("idle_usd", 0.0)
    carry = max(0.0, (s["vault_apy"] or 0) - (s["measured"].get("aave_usdc_apy") or 0)) * horizon_days / 365.25
    ahead = sum(d["assets_usd"] for d in deps[:max(0, rank - 1)])

    def run_mc(scale_driver=None, k=1.0, rs=rate_scale, sv=severity_scale, rh=rho):
        sc_rate = {d: rs for d in D}
        if scale_driver:
            sc_rate[scale_driver] = rs * k
        return monte_carlo(D, sc, horizon_days, rh, rate_scale=sc_rate, severity_scale=sv)

    def exit_cost_fn(p=pen, rf=refill_scale):
        def f(x, t):
            if x == 0:
                return 0.0, 0.0
            rec = ER.recovered(x * size, ahead, mk, t, p, idle, rf)
            out = rec["from_instant"] + rec["from_forced"]
            return rec["penalty_usd"] + carry * out, out
        return f

    def decision(mc, lam_=lam, p=pen, rf=refill_scale):
        return decide(DecisionInputs(size, book_usd, lam_, mc.el, mc.cvar95, mc.var95, horizon_days, exit_cost_fn(p, rf),
                                     c["risk"]["pocket_var95_hard_limit"]))

    mc = run_mc()
    dec = decision(mc)
    # #1 driver: largest risk-adjusted contribution
    contrib = {k: v["E[L]"] + lam * (v["CVaR_contrib"] - v["E[L]"]) for k, v in mc.attribution.items()}
    top = max(contrib, key=contrib.get) if contrib else None
    top_sc = next((x for x in sc if x.id == top), None)
    drv = D[top_sc.driver] if top_sc else None

    def net_full_now(k):      # every driver's frequency scaled by k: "how likely must a loss event be?"
        grid = decision(run_mc(rs=rate_scale * k))["grid"]
        return next(g for g in grid if g["t_s"] == 0 and g["x"] == 1.0)["net_usd"]
    kstar = breakeven_scale(net_full_now, hi=20.0) if with_tornado else None
    p_est = mc.summary()["p_any_loss"]
    p_be = run_mc(rs=rate_scale * kstar).summary()["p_any_loss"] if kstar is not None else None
    race = ER.race_table(size, rank, deps, mk, pen, idle, refill_scale)
    out = {
        "scope": "hero2", "vault": meta["vault"], "label": meta["label"], "fork_block": meta["fork_block"],
        "size_usd": size, "rank": rank, "ahead_usd": ahead, "lambda": lam, "horizon_days": horizon_days, "rho": rho,
        "governance_penalty": governance, "penalty": pen, "book_usd": book_usd,
        "action": dec["action"], "exit_fraction": dec["exit_fraction"],
        "net_value_exit_now_usd": dec["net_value_exit_now_usd"], "net_value_exit_now_bps_book": dec["bps_of_book"],
        "hard_budget_hit": dec["hard_budget_hit"], "decision": {k: v for k, v in dec.items() if k != "grid"},
        "grid": dec["grid"], "mc": mc.summary(),
        "loss_usd": {"E[L]": mc.el * size, "VaR95": mc.var95 * size, "CVaR95": mc.cvar95 * size},
        "driver": {"scenario": top, "label": top_sc.label if top_sc else None, "driver": drv.label if drv else None,
                   "share_of_risk_adjusted_loss": contrib[top] / sum(contrib.values()) if contrib and sum(contrib.values()) else None,
                   "time_to_impact_s": top_sc.time_to_impact_s if top_sc else None,
                   "confidence": top_sc.confidence if top_sc else None, "source": drv.source if drv else None},
        "breakeven": {"event": f"a loss-making incident on any dependency within {horizon_days:.0f} days",
                      "p_breakeven": p_be, "p_estimate": p_est, "rate_multiplier": kstar},
        "exit_race": race, "carry_cost_per_usd": carry,
    }
    out["reason"] = reasons(out, meta)
    if with_tornado:
        base = out["net_value_exit_now_usd"]

        def f(name, v):
            kw = dict(size_usd=size, rank=rank, lam=lam, horizon_days=horizon_days, rho=rho, governance=governance,
                      rate_scale=rate_scale, severity_scale=severity_scale, refill_scale=refill_scale,
                      vault_claim_share=vault_claim_share, book_usd=book_usd, with_tornado=False)
            kw[name] = v
            return headline(**kw)["net_value_exit_now_usd"]
        out["tornado"] = tornado(base, f, {
            "rate_scale": (0.5, 2.0, "base-rate frequency x0.5 / x2 (yield_synthetic: 10 episodes in 12 coin-years)"),
            "severity_scale": (0.5, 1.5, "episode depth x0.5 / x1.5"),
            "rho": (0.0, 0.8, "copula correlation between drivers (assumption)"),
            "lam": (0.0, 1.0, "risk aversion lambda (ASSUMED_ANSWERS §3)"),
            "horizon_days": (7, 90, "decision horizon (assumption)"),
            "refill_scale": (0.25, 2.0, "liquidity refill speed vs measured history"),
        })
    return out


def reasons(h: dict, meta: dict) -> list[str]:
    d, race = h["driver"], h["exit_race"]
    now = race["by_time"]["0m"]
    tte = race["time_to_full_exit_s"]
    return [
        f"#1 driver: {d['label']} ({(d['share_of_risk_adjusted_loss'] or 0):.0%} of risk-adjusted loss): "
        f"vault → {d['label'].split('(')[0].strip()} → bad debt socialized to depositors; time-to-impact "
        f"{'0 (silent: the share price does not move)' if not d['time_to_impact_s'] else f'{d['time_to_impact_s'] / 60:.0f} min'}.",
        f"Expected loss ${h['loss_usd']['E[L]']:,.0f}, CVaR95 ${h['loss_usd']['CVaR95']:,.0f} on ${h['size_usd']:,.0f} over "
        f"{h['horizon_days']:.0f} days (λ={h['lambda']}).",
        f"Exit now at rank {h['rank']}: {now['recovered_pct']:.0%} reachable (penalty ${now['penalty_usd']:,.0f}); "
        + ("full exit possible now" if tte == 0 else f"full exit in {tte / 3600:.1f} h" if tte is not None
           else "full exit not reachable within a year at measured refill")
        + (" — curator raised the penalty to 2% (no timelock)" if h["governance_penalty"] else "") + ".",
    ]


def measure(offline: bool = False) -> dict:
    """Fork measurements the headline needs beyond hero2.json: governance penalty run, Aave USDC APY."""
    fork = Fork(offline=offline)
    if fork.offline:
        fork.fork_block = A.FORK_BLOCK
    meta, _ = ER.load_inputs()
    gov = ER.governance_penalty_run(fork, meta, 0.02)
    out = {"fork_block": fork.fork_block, "governance_run": gov, "aave_usdc_apy": ER.aave_usdc_apy(fork)}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=1, default=str))
    return out


if __name__ == "__main__":
    m = measure(offline="--offline" in sys.argv)
    print("governance run (penalty 2%):", [(x["rank"], round(x["recovered_pct"] or 0, 4)) for x in m["governance_run"]["run"]["ranks"]])
    print("aave usdc apy", m["aave_usdc_apy"])
    _CACHE.clear()
    h = headline()
    HEADLINE.write_text(json.dumps(h, indent=1, default=str))
    print(json.dumps({k: h[k] for k in ("action", "exit_fraction", "net_value_exit_now_usd", "net_value_exit_now_bps_book",
                                        "loss_usd", "driver", "breakeven", "reason")}, indent=1, default=str))
