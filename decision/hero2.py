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
    apy = (st.get("vault_apy_realized") or {}).get("30d")
    return {"meta": meta, "lr": lr, "D": D, "sc": sc, "measured": st,
            "vault_apy": apy if apy is not None else (reg.apy if reg else 0.0),
            "vault_apy_source": "realized share-price growth over 30 days on-chain (net of fees)" if apy is not None
            else "registry snapshot (dashboard)"}


_CACHE: dict = {}


def static() -> dict:
    if not _CACHE:
        _CACHE.update(_static())
    return _CACHE


def headline(size_usd: float | None = None, rank: int = 1, lam: float | None = None,
             horizon_days: float = DEFAULT_HORIZON_DAYS, rho: float = 0.3, governance: bool = False,
             rate_scale: float = 1.0, severity_scale: float = 1.0, refill_scale: float = 1.0,
             vault_claim_share: float | None = None, book_usd: float | None = None, with_tornado: bool = True,
             incident: float | None = None, incident_driver: str = "trusd", book_budget: bool = True) -> dict:
    """incident: an OBSERVED trUSD depeg of this depth (e.g. 0.05). Then the trUSD event is certain (final depth drawn
    from episodes at least that deep), the other depositors run (your rank matters) and, because the oracles stay at
    par, the silent loss concentrates on the holders who did not get out. incident=None: calm day, nobody running."""
    s = static()
    c = cfg()
    meta, D, sc = s["meta"], s["D"], s["sc"]
    lam = c["risk"]["lambda"] if lam is None else lam
    book_usd = book_usd or c["mandate"]["mandate_usd"]          # main bps figure: the $50M assumed mandate
    aum_usd = c["mandate"]["aum_usd"]                             # secondary: Belem's ~$400M AUM
    r = meta["q1"]["roles"]
    tot = r["total_assets_usd"]
    size = size_usd or min(c["sizing"]["ticket_usd"], c["sizing"]["max_share_curated_vault_tvl"] * tot)
    pen0 = max(r["force_deallocate_penalty"].values() or [0])
    pen = 0.02 if governance else pen0
    deps = meta["q3"]["top_depositors"]
    mk = ER.markets_from(meta, s["lr"], vault_claim_share)
    idle = meta["q1"].get("idle_usd", 0.0)
    carry = (s["vault_apy"] or 0.0) * horizon_days / 365.25      # yield earned by staying (forgone if you exit)
    run = incident is not None
    ahead = sum(d["assets_usd"] for d in deps[:max(0, rank - 1)]) if run else 0.0
    cond = {incident_driver: incident} if run else None
    conc = 1.0
    if run:   # others exit at par before the frozen-oracle loss is recognized: it lands on those who stay
        inst, forced = ER.reachable(mk, 0, idle, refill_scale)
        others = min(inst + forced, tot - size)
        conc = tot / max(1.0, tot - others)
    if incident_driver != "trusd":
        conc = 1.0              # only the frozen-oracle trUSD loss is silent; other losses are priced in when they hit
    lscale = {"trusd_frozen": conc}

    def run_mc(scale_driver=None, k=1.0, rs=rate_scale, sv=severity_scale, rh=rho):
        sc_rate = {d: rs for d in D}
        if scale_driver:
            sc_rate[scale_driver] = rs * k
        return monte_carlo(D, sc, horizon_days, rh, rate_scale=sc_rate, severity_scale=sv, condition=cond,
                           loss_scale=lscale)

    def exit_cost_fn(p=pen, rf=refill_scale):
        def f(x, t):
            if x == 0:
                return 0.0, 0.0
            rec = ER.recovered(x * size, ahead, mk, t, p, idle, rf)
            return rec["penalty_usd"], rec["from_instant"] + rec["from_forced"]
        return f

    def decision(mc, lam_=lam, p=pen, rf=refill_scale):
        return decide(DecisionInputs(size, book_usd, lam_, mc.el, mc.cvar95, mc.var95, horizon_days, exit_cost_fn(p, rf),
                                     c["risk"]["pocket_var95_hard_limit"], carry_per_usd=carry))

    mc = run_mc()
    dec = decision(mc)
    # ASSUMED_ANSWERS §3 book budget: single-incident CVaR95 above N bps of the book -> exit enough to get under it
    lim = c["risk"]["book_cvar95_single_incident_bps"] / 1e4 * book_usd
    book_hit = book_budget and mc.cvar95 * size > lim
    if book_hit and not dec["locked"]:
        need = 1 - lim / (mc.cvar95 * size)
        x = next(f for f in (0.25, 0.5, 0.75, 1.0) if f >= need)
        g = next(g for g in dec["grid"] if g["t_s"] == 0 and g["x"] == x)
        if g["exited_usd"] > 0 and (dec["action"] == "STAY" or dec["exit_fraction"] < x):
            dec.update(action="EXIT" if x == 1.0 else "REDUCE", exit_fraction=x, now=g,
                       net_value_exit_now_usd=g["net_usd"], bps_of_book=g["net_usd"] / book_usd * 1e4)
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
    race = ER.race_table(size, rank if run else 1, deps, mk, pen, idle, refill_scale)
    now_full = next(g for g in dec["grid"] if g["t_s"] == 0 and g["x"] == 1.0)
    out = {
        "scope": "hero2", "vault": meta["vault"], "label": meta["label"], "fork_block": meta["fork_block"],
        "size_usd": size, "rank": rank, "ahead_usd": ahead, "lambda": lam, "horizon_days": horizon_days, "rho": rho,
        "governance_penalty": governance, "penalty": pen, "book_usd": book_usd,
        "action": dec["action"], "exit_fraction": dec["exit_fraction"],
        "incident": incident, "run": run, "loss_concentration": conc, "locked_now": dec["locked"],
        "queue_plan": None if not dec["locked"] else {
            "best_t": dec["best"]["t"], "best_x": dec["best"]["x"], "best_net_usd": dec["best"]["net_usd"],
            "recoverable_24h_pct": race["by_time"]["24h"]["recovered_pct"]},
        "net_value_exit_now_usd": dec["net_value_exit_now_usd"], "net_value_exit_now_bps_book": dec["bps_of_book"],
        "bps_basis": f"assumed mandate ${book_usd / 1e6:,.0f}M", "aum_usd": aum_usd,
        "net_value_exit_now_bps_aum": dec["net_value_exit_now_usd"] / aum_usd * 1e4,
        "components_full_exit_now": {k: now_full[k] for k in ("exited_usd", "loss_avoided_usd", "yield_forgone_usd",
                                                              "exit_cost_usd", "net_usd")},
        "carry": {"vault_apy": s["vault_apy"], "source": s["vault_apy_source"], "per_usd_over_horizon": carry},
        "sanity": {"E[L]_annualized": mc.el * 365.25 / horizon_days, "vault_apy": s["vault_apy"],
                   "E[L]_exceeds_yield": mc.el * 365.25 / horizon_days > (s["vault_apy"] or 0)},
        "hard_budget_hit": dec["hard_budget_hit"], "decision": {k: v for k, v in dec.items() if k != "grid"},
        "grid": dec["grid"], "mc": mc.summary(),
        "loss_usd": {"E[L]": mc.el * size, "VaR95": mc.var95 * size, "CVaR95": mc.cvar95 * size},
        "driver": {"scenario": top, "label": top_sc.label if top_sc else None, "driver": drv.label if drv else None,
                   "share_of_risk_adjusted_loss": contrib[top] / sum(contrib.values()) if contrib and sum(contrib.values()) else None,
                   "time_to_impact_s": top_sc.time_to_impact_s if top_sc else None,
                   "confidence": top_sc.confidence if top_sc else None, "source": drv.source if drv else None},
        "breakeven": {"event": f"a loss-making incident on any dependency within {horizon_days:.0f} days",
                      "p_breakeven": p_be, "p_estimate": p_est, "rate_multiplier": kstar},
        "exit_race": race,
    }
    out["book_budget"] = {"limit_usd": lim, "cvar95_usd": mc.cvar95 * size, "hit": book_hit,
                          "rule": f"single-incident CVaR95 <= {c['risk']['book_cvar95_single_incident_bps']} bps of the "
                                  f"{out['bps_basis']} (ASSUMED_ANSWERS §3)"}
    if dec["locked"]:     # nothing can leave now: queue the full exit and say what staying locked costs
        steps = [i * 3600 for i in range(0, int(horizon_days * 24) + 1, 1)]
        locked_avg = sum(ER.recovered(size, ahead, mk, t, pen, idle, refill_scale)["locked_usd"] for t in steps) / len(steps)
        out["action"] = "QUEUE EXIT NOW"
        out["queue"] = {"locked_hours": (race["time_to_full_exit_s"] or 0) / 3600 if race["time_to_full_exit_s"] is not None else None,
                        "expected_loss_while_locked_usd": mc.el * locked_avg,
                        "assumption": "the loss is recognized at a uniformly random time within the horizon; you bear "
                                      "it on whatever is still locked at that time"}
    out["reason"] = reasons(out, meta)
    if with_tornado:
        base = out["net_value_exit_now_usd"]

        def f(name, v):
            kw = dict(size_usd=size, rank=rank, lam=lam, horizon_days=horizon_days, rho=rho, governance=governance,
                      rate_scale=rate_scale, severity_scale=severity_scale, refill_scale=refill_scale,
                      vault_claim_share=vault_claim_share, book_usd=book_usd, with_tornado=False, incident=incident)
            kw[name] = v
            return headline(**kw)["net_value_exit_now_usd"]
        out["tornado"] = tornado(base, f, {
            "rate_scale": (0.5, 2.0, "base-rate frequency x0.5 / x2 (yield_synthetic class, see Base rates)"),
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
    out = {"fork_block": fork.fork_block, "governance_run": gov, "aave_usdc_apy": ER.aave_usdc_apy(fork),
           "vault_apy_realized": ER.realized_apy(fork, meta["vault"])}
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


# ----------------------------------------------------------------------------------- calm-day diagnostics
def _net_full_now(**kw) -> float:
    h = headline(with_tornado=False, **kw)
    return h["components_full_exit_now"]["net_usd"]


def implied_lambda(**kw) -> dict:
    """The lambda at which a full exit now is worth exactly 0: running the vault at this size implies lambda below it."""
    lo, hi = 0.0, 1.0
    f0, f1 = _net_full_now(lam=lo, **kw), _net_full_now(lam=hi, **kw)
    if f0 >= 0:
        return {"lambda": 0.0, "note": "even a risk-neutral holder exits: E[L] alone exceeds yield + exit cost"}
    if f1 <= 0:
        return {"lambda": None, "note": "staying holds for every lambda in [0, 1]"}
    for _ in range(40):
        mid = (lo + hi) / 2
        lo, hi = (lo, mid) if _net_full_now(lam=mid, **kw) > 0 else (mid, hi)
    return {"lambda": hi, "note": "staying implies a risk aversion below this"}


def max_stay_size(lam: float, sizes=None, **kw) -> dict:
    """Largest deposit for which the recommendation is STAY (decision rule + the book CVaR budget)."""
    sizes = sizes or [s * 1e5 for s in range(1, 121)]           # $0.1M .. $12M
    stay = [s for s in sizes if headline(size_usd=s, lam=lam, with_tornado=False, **kw)["action"] == "STAY"]
    return {"lambda": lam, "max_size_usd": max(stay) if stay else None, "min_size_usd": min(stay) if stay else None,
            "n_stay": len(stay), "grid": f"${sizes[0] / 1e6:.1f}M..${sizes[-1] / 1e6:.0f}M step $0.1M"}


def early_warning(lam: float, rank: int = 6, driver: str = "trusd", depths=None) -> dict:
    """Watch-mode trigger: the shallowest observed move at which any depositor AHEAD of you (real top holders) has a
    positive net value of exiting with this decision rule: they run, and after that you cannot exit fully."""
    s = static()
    deps = s["meta"]["q3"]["top_depositors"][: max(0, rank - 1)]
    depths = depths or [x / 400 for x in range(1, 201)]          # 0.25% steps to 50%
    out = []
    for d in deps:
        kw = dict(size_usd=d["assets_usd"], rank=1, lam=lam, with_tornado=False, book_budget=False)  # their book: unknown
        trig = next((x for x in depths if headline(incident=x, incident_driver=driver, **kw)["action"] != "STAY"), None)
        calm = headline(**kw)["action"]
        out.append({"address": d["address"], "size_usd": d["assets_usd"], "calm_action": calm, "trigger_depth": trig})
    trig = [0.0 if o["calm_action"] != "STAY" else o["trigger_depth"] for o in out]
    trig = [t for t in trig if t is not None]
    return {"lambda": lam, "rank": rank, "driver": driver, "ahead": out,
            "act_before_depth": min(trig) if trig else None}
