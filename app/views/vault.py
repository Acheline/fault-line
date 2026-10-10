"""Belem vault (hero #2): the RockawayX USDC Yield vault, one of the challenge setter's own curated vaults.
Headline + three questions, every number from the fork-measured cache. Detail lives in the "Show details" expanders."""
import json

import plotly.graph_objects as go
import streamlit as st

from app import ui
from app.state import VAULT_DEFAULT_LAMBDA, overrides
from core.config import cfg
from core.fork import ROOT
from decision import hero2 as D2

SRC, HL = ROOT / "data" / "graphs" / "hero2.json", ROOT / "data" / "shocks" / "hero2.json"
if not (SRC.exists() and HL.exists()):
    st.warning("No vault data yet. Run `python -m discovery.hero2` then `python -m risk.scenarios_hero2` "
               "(add `--offline` to replay from cache).")
    st.stop()
m = json.loads(SRC.read_text())["meta"]
shocks = json.loads(HL.read_text())
r = m["q1"]["roles"]
tot = r["total_assets_usd"]
ui.setup("🏦 Belem vault", f"{r['name']} · {ui.usd(tot)} · one of the challenge setter's own curated vaults · "
         f"fork block {m['fork_block']}")

ov = overrides()
ov_key = tuple(sorted(ov.items()))
c = cfg(ov)
MTIME = HL.stat().st_mtime


@st.cache_data(show_spinner="Running 10,000 Monte Carlo paths on the fork-measured losses…")
def headline(size, rank, lam, horizon, rho, gov, incident, ovk, mtime):
    return D2.headline(size_usd=size, rank=rank, lam=lam, horizon_days=horizon, rho=rho, governance=gov,
                       incident=incident, overrides=dict(ovk))


@st.cache_data(show_spinner=False)
def implied_lambda(size, horizon, rho, gov, ovk, mtime):
    return D2.implied_lambda(size_usd=size, horizon_days=horizon, rho=rho, governance=gov, overrides=dict(ovk))


@st.cache_data(show_spinner=False)
def early_warning(lam, ovk, mtime):
    return D2.early_warning(lam, 6, "trusd", overrides=dict(ovk))


@st.cache_data(show_spinner="Solving the maximum STAY size…")
def max_stay(horizon, rho, ovk, mtime):
    return {l: D2.max_stay_size(l, horizon_days=horizon, rho=rho, overrides=dict(ovk))["max_size_usd"]
            for l in (0.0, 0.25, 0.5)}


@st.cache_data(show_spinner=False)
def class_ranges(ovk, mtime):
    return D2.class_ranges(overrides=dict(ovk))


# ---------------------------------------------------------------------------------------------------- controls
with st.sidebar:
    st.markdown("**Your position**")
    default = min(c["sizing"]["ticket_usd"], c["sizing"]["max_share_curated_vault_tvl"] * tot)
    sizes = sorted({x * 100_000 for x in range(1, 101)} | {default})     # exact default = the Overview card's number
    size = st.select_slider("Deposit size", sizes, default, format_func=ui.usd,
                            help="default: $5M ticket capped at 15% of vault TVL (Assumptions §4)")
    with st.expander("Advanced"):
        horizon = st.select_slider("Horizon (days)", [7, 14, 30, 60, 90], 30, help="assumption: monthly risk review")
        rho = st.slider("Correlation between risks ρ", 0.0, 0.8, 0.3, 0.1, help="assumption (Gaussian copula)")
        gov = st.toggle("Governance shock: curator raises the exit penalty to 2% (no timelock)", False,
                        help="measured on the fork by impersonating the curator")

c1, c2, c3 = st.columns([1.4, 1, 1])
with c1:
    sit = st.segmented_control("Situation", ["Calm", "trUSD −5%", "trUSD −20%"], default="Calm", key="vault_sit") \
        or "Calm"
incident = {"Calm": None, "trUSD −5%": 0.05, "trUSD −20%": 0.20}[sit]
rank = c2.slider("Your place in the queue", 1, 11, 1,
                 help="1 = you exit first. At n, the n−1 largest real depositors (Transfer logs) exit before you.")
lam = c3.slider("Risk appetite λ", 0.0, 1.0, VAULT_DEFAULT_LAMBDA, 0.05,
                help="weight on the worst case: 0 = expected loss only, 1 = the worst-case average (CVaR95) counts "
                     "fully. The Assumptions page default is 0.5.")

h = headline(float(size), int(rank), lam, float(horizon), rho, gov, incident, ov_key, MTIME)
race = h["exit_race"]["by_time"]
drv = h["driver"]

# ---------------------------------------------------------------------------------------------------- headline
if h["action"] == "QUEUE EXIT NOW":
    why = (f"The {rank - 1} depositors ahead of you ({ui.usd(h['ahead_usd'])}) take all the cash that can leave now: "
           f"join the exit queue immediately; {ui.pct(race['24h']['recovered_pct'])} is back within 24 h"
           + (f", expected loss while locked {ui.usd(h['queue']['expected_loss_while_locked_usd'])}."
              if h.get("queue") else "."))
elif incident:
    why = (f"trUSD is −{incident:.0%} but its oracles stay at $1: the loss lands on whoever is still in the vault. "
           f"At rank {rank} you can get {ui.pct(race['0m']['recovered_pct'])} out now.")
else:
    cf0 = h["components_full_exit_now"]
    why = (f"Calm day: expected loss {ui.usd(h['loss_usd']['E[L]'])} over {horizon} days vs "
           f"{ui.usd(cf0['yield_forgone_usd'])} of yield given up + {ui.usd(cf0['exit_cost_usd'])} exit penalty. "
           f"#1 risk: {drv['label'].split('(')[0].strip()}.")
extra = ""
if h["book_budget"]["hit"]:
    extra += (f"<div class='sub'>Book budget hit: worst-case average {ui.usd(h['book_budget']['cvar95_usd'])} > "
              f"{ui.usd(h['book_budget']['limit_usd'])} limit for one incident.</div>")
if not incident:
    il = implied_lambda(float(size), float(horizon), rho, gov, ov_key, MTIME)
    if il["lambda"] is not None:
        extra += (f"<div class='sub'>Running this vault at this size implies λ ≈ {il['lambda']:.2f}: "
                  f"above it, the answer flips to exit.</div>")
ew = early_warning(lam, ov_key, MTIME)["act_before_depth"]
if ew is not None:
    extra += (f"<div class='why' style='margin-top:8px'>⚠️ <b>Act when trUSD &lt; ${1 - ew:.4f}</b>: "
              + ("the 5 largest depositors leave first, then the instant cash is gone (watch trigger, rank 6+).</div>"
                 if ew > 0 else "the 5 largest depositors already leave on a calm day at this λ.</div>"))
ui.headline_card(h, why, extra=extra)

# ---------------------------------------------------------------------------------------------------- findings
basis = m["oracle_quality"].get("per_market", {})
mk = m["q1"]["markets"]
stuck = [x for x in mk if basis.get(x["collateral_symbol"], {}).get("price_basis") == "issuer_reported"]
stuck_share = sum(x["allocation_pct"] for x in stuck)
fz = {round(x["severity"], 2): x for x in shocks["measured"]["trusd_frozen"]}
tr = {round(x["severity"], 2): x for x in shocks["measured"]["trusd_tracking"]}
f50 = fz.get(0.5)
ranks = m["q3"]["run"]["ranks"]
n_full = sum(1 for x in ranks if (x["recovered_pct"] or 0) >= 0.9)
partial = next((x for x in ranks if 0 < (x["recovered_pct"] or 0) < 0.9), None)
lines = [f"<b>{ui.pct(stuck_share)} priced by issuer-reported feeds</b> "
         f"({', '.join(sorted({x['collateral_symbol'] for x in stuck}))}): the oracle stays at $1 while trUSD falls."]
if f50:
    lines.append(f"<b>Silent bad debt</b>: at trUSD −50%, {ui.pct(f50['loss_per_share'])} of every share is lost; "
                 f"the share price shows {ui.pct(max(0.0, f50['recognized_loss_per_share'] or 0))}.")
lines.append(f"<b>Exit order decides who gets paid</b>: top {n_full} depositors get {ui.pct(ranks[0]['recovered_pct'])}"
             + (f", #{partial['rank']} gets {ui.pct(partial['recovered_pct'])}" if partial else "")
             + ", the rest 0% until borrowers repay.")
ui.findings(lines)

# ---------------------------------------------------------------------------------------------------- 3 questions
t1, t2, t3 = st.tabs(["Q1 · Where does the money go?", "Q2 · Can borrowers repay?", "Q3 · Can depositors withdraw?"])
with t1:
    by_root: dict[str, dict] = {}
    for x in mk:
        b = by_root.setdefault(x["root_symbol"], {"share": 0.0, "stuck": False, "markets": []})
        b["share"] += x["allocation_pct"]
        b["markets"].append(x["collateral_symbol"])
        b["stuck"] |= x in stuck
    rows = sorted(by_root.items(), key=lambda kv: kv[1]["share"])
    fig = go.Figure()
    for flag, name, color in ((True, "oracle stuck at par (issuer-reported)", ui.ALERT),
                              (False, "market or exchange-rate priced", ui.ACCENT)):
        sel = [(k, v) for k, v in rows if v["stuck"] == flag]
        fig.add_bar(y=[k for k, _ in sel], x=[v["share"] for _, v in sel], orientation="h", name=name,
                    marker_color=color, text=[f"{ui.pct(v['share'])}  ·  {', '.join(v['markets'])}" for _, v in sel],
                    textposition="outside", cliponaxis=False,
                    hovertemplate="%{y}: %{x:.1%}<extra></extra>")
    fig.update_xaxes(tickformat=".0%", range=[0, max(v["share"] for _, v in rows) * 1.55])
    fig.update_yaxes(categoryorder="array", categoryarray=[k for k, _ in rows])
    ui.chart(ui.clean(fig, f"{ui.pct(stuck_share)} of the vault is priced by oracles that stay at par", 290,
                      showlegend=True, barmode="overlay"))
    feeds = sorted({f for x in stuck for f in basis.get(x["collateral_symbol"], {}).get("executed_leaf_feeds", [])})
    ui.takeaway(f"Grouped by the root asset read on-chain through each wrapper. The red markets are priced by "
                f"{', '.join(feeds) or 'issuer-reported feeds'}: if trUSD falls, these markets see nothing and no "
                "liquidation fires.")
with t2:
    xs = sorted(fz)
    fig = go.Figure()
    fig.add_scatter(x=xs, y=[tr[s]["loss_per_share"] for s in xs], name="oracle moves (liquidations run)",
                    mode="lines+markers", line={"color": ui.ACCENT, "width": 3})
    fig.add_scatter(x=xs, y=[fz[s]["loss_per_share"] for s in xs], name="oracle stuck at par: real loss",
                    mode="lines+markers", line={"color": ui.ALERT, "width": 3, "dash": "dot"})
    fig.add_scatter(x=xs, y=[max(0.0, fz[s]["recognized_loss_per_share"] or 0) for s in xs],
                    name="loss the share price shows (oracle at par)", mode="lines+markers",
                    line={"color": ui.MUTED, "width": 2, "dash": "dash"})
    fig.update_xaxes(tickformat=".0%", title="trUSD fall")
    fig.update_yaxes(tickformat=".0%", title="loss per vault share")
    ttl = (f"At trUSD −50%, {ui.pct(f50['loss_per_share'])} of each share is lost; the share price shows "
           f"{ui.pct(max(0.0, f50['recognized_loss_per_share'] or 0))}") if f50 else "Bad debt per share vs trUSD fall"
    ui.chart(ui.clean(fig, ttl, 360, showlegend=True, hovermode="x unified"))
    cap = sum(v for k, v in shocks["capacities_usd"].items() if "trUSD" in k or "strUSD" in k)
    ui.takeaway(f"Measured on the fork: oracle pinned, every underwater borrower liquidated. The two loss lines nearly "
                f"coincide because liquidators can absorb only {ui.usd(cap)} of trUSD-family collateral at liquidation "
                f"size. Down to −{max((s for s in xs if fz[s]['loss_per_share'] == 0), default=0):.0%} borrowers stay "
                "over-collateralized: no loss.")
with t3:
    a, b = st.columns(2)
    with a:
        fig = go.Figure(go.Bar(
            x=[f"#{x['rank']}" for x in ranks], y=[x["recovered_pct"] or 0 for x in ranks],
            marker_color=[ui.INK if x["rank"] == rank else ui.ACCENT for x in ranks],
            text=[ui.pct(x["recovered_pct"] or 0) for x in ranks], textposition="outside", cliponaxis=False,
            customdata=[ui.usd(x["owned_usd"]) for x in ranks],
            hovertemplate="rank %{x}: owns %{customdata}, recovers %{y:.1%}<extra></extra>"))
        fig.update_yaxes(tickformat=".0%", range=[0, 1.15], title="recovered now")
        fig.update_xaxes(title="depositor rank (largest real holders, exit in size order)")
        ui.chart(ui.clean(fig, f"Only the first {n_full} depositors get out", 340))
    with b:
        ts = list(race)
        vals = [race[t]["recovered_pct"] for t in ts]
        fig = go.Figure(go.Bar(x=ts, y=vals, marker_color=ui.ACCENT, text=[ui.pct(v) for v in vals],
                               textposition="outside", cliponaxis=False))
        fig.update_yaxes(tickformat=".0%", range=[0, 1.15], title="share of your deposit out")
        fig.update_xaxes(title="time after the shock")
        r_eff = rank if h["run"] else 1
        ttl = (f"At rank {r_eff}: 100% out right away" if min(vals) >= 0.999 else
               f"At rank {r_eff}: {ui.pct(vals[0])} now, {ui.pct(vals[-1])} after 24 h")
        ui.chart(ui.clean(fig, ttl, 340))
    ui.takeaway("The run is executed on the fork with the real top depositors: each redemption drains the cash the "
                "next one can reach. After that, cash comes back at the pace measured in 29 past 100%-utilization "
                "episodes on Morpho." + ("" if h["run"] else " Calm day: nobody is running, so your place in the "
                                         "queue does not matter yet."))

# ---------------------------------------------------------------------------------------------------- details
st.markdown("#### Show details")
with st.expander("The numbers behind the headline"):
    be = h["breakeven"]
    k = st.columns(5)
    k[0].metric("Expected loss", ui.usd(h["loss_usd"]["E[L]"]), help=f"over {horizon} days, if you stay")
    k[1].metric("Worst-case average (CVaR95)", ui.usd(h["loss_usd"]["CVaR95"]), help="mean of the worst 5% of paths")
    k[2].metric("Breakeven belief", ui.pct(be["p_breakeven"]) if be["p_breakeven"] is not None else "n/a",
                f"our estimate {ui.pct(be['p_estimate'])}" if be["p_estimate"] is not None else None,
                delta_color="off", help=f"P({be['event']}) above which exiting now pays")
    k[3].metric("#1 driver", f"{(drv['share_of_risk_adjusted_loss'] or 0):.0%}", drv["label"].split("(")[0][:40],
                delta_color="off", help=drv["label"])
    k[4].metric("Time-to-impact", "immediate, silent" if not drv["time_to_impact_s"] else
                f"{drv['time_to_impact_s'] / 60:.0f} min", f"confidence: {drv['confidence']}"[:40], delta_color="off")
    cf = h["components_full_exit_now"]
    st.markdown(f"Full exit now = risk-adjusted loss avoided **{ui.usd(cf['loss_avoided_usd'])}** − yield given up "
                f"**{ui.usd(cf['yield_forgone_usd'])}** (vault APY {ui.pct(h['carry']['vault_apy'])}, "
                f"{h['carry']['source']}) − exit cost **{ui.usd(cf['exit_cost_usd'])}** = "
                f"**{ui.usd(cf['net_usd'], signed=True)}**. Secondary: {h['net_value_exit_now_bps_aum']:+.2f} bps of "
                f"Belem's ~{ui.usd(h['aum_usd'])} AUM.")
    for line in h["reason"]:
        st.markdown(f"- {line}")
    if h.get("queue"):
        q = h["queue"]
        st.warning(f"Queue: locked ~{(q['locked_hours'] or 0):.0f} h; expected loss while locked "
                   f"{ui.usd(q['expected_loss_while_locked_usd'])} ({q['assumption']}).")
    if h["hard_budget_hit"]:
        st.error("Hard budget hit: pocket VaR95 above the 20% limit (Assumptions §3).")
    wn = m["q3"]["withdrawable_now"]
    instant = wn["idle_usd"] + wn["instant_from_liquidity_market_usd"]
    v = st.columns(4)
    v[0].metric("Total assets", ui.usd(tot))
    v[1].metric("Instantly withdrawable", ui.usd(instant), f"{ui.pct(instant / tot)} of vault", delta_color="off")
    v[2].metric("Reachable with forceDeallocate", ui.usd(wn["total_reachable_usd"]),
                f"penalty {ui.pct(wn['force_deallocate_penalty'])}", delta_color="off")
    dc = m["q3"]["depositor_concentration"]
    v[3].metric("Top depositor", ui.pct(dc["top1_share"]), f"top 5: {ui.pct(dc['top5_share'])}", delta_color="off")
    if st.toggle("Compute the largest deposit that still reads STAY (≈10 s)", False):
        ms = max_stay(float(horizon), rho, ov_key, MTIME)
        st.markdown("Max deposit for STAY: " + " · ".join(
            f"λ={l}: {'never' if s is None else ui.usd(s)}" for l, s in ms.items()))

with st.expander("Per-market tables (Q1 · Q2 · Q3)"):
    st.markdown("**Q1 · allocation per market**")
    ui.table([{"market": x["collateral_symbol"], "allocation": x["allocation_usd"], "share": x["allocation_pct"],
               "cap": x["caps"]["market"]["absolute_usd"], "LLTV": x["lltv"], "utilization": x["utilization"],
               "free liquidity": x["free_liquidity_usd"], "vault share of market": x["vault_share_of_market"],
               "root asset": x["root_symbol"], "price basis": basis.get(x["collateral_symbol"], {}).get("price_basis"),
               "oracle feeds": ", ".join(basis.get(x["collateral_symbol"], {}).get("executed_leaf_feeds", [])),
               "oracle confidence": basis.get(x["collateral_symbol"], {}).get("confidence", ""),
               "liquidity market": "✔" if x["is_liquidity_market"] else ""} for x in mk],
             money=("allocation", "cap", "free liquidity"),
             pcts=("share", "LLTV", "utilization", "vault share of market"))
    ex = m["q1"]["exposure"]
    st.markdown("**Exposure groupings** (correlated assets grouped by the wrapper chain read on-chain, not by label). "
                "Curator's published caps: single protocol 25%, single oracle 40%, correlated assets 40%, "
                "single chain 60%.")
    cols = st.columns(4)
    for col, key, title in zip(cols, ("root_asset", "price_basis", "protocol", "collateral"),
                               ("by root asset", "by oracle price basis", "by protocol", "by collateral")):
        with col:
            st.markdown(f"*{title}*")
            ui.table([{"group": g, "share": s} for g, s in sorted(ex.get(key, {}).items(), key=lambda kv: -kv[1])],
                     pcts=("share",))
    st.markdown("**Q2 · borrowers and collateral exit**")
    q2rows, q2shocks = [], []
    for q in m["q2"]:
        hb, ce = q["hf_buckets"], q["collateral_exit"]
        q2rows.append({"market": q["market"], "borrowers read": q["n_borrowers_read"],
                       "debt covered": q["debt_covered_usd"] / q["market_borrow_usd"] if q["market_borrow_usd"] else None,
                       "debt with HF<1.05": hb["<1.00 (liquidatable)"]["debt_share"] + hb["1.00-1.05"]["debt_share"],
                       "debt with HF<1.10": sum(hb[k]["debt_share"] for k in ("<1.00 (liquidatable)", "1.00-1.05",
                                                                             "1.05-1.10")),
                       "collateral exit at liq. size": "no route" if ce.get("usdc_out") is None
                       else f"{ce['discount_vs_oracle'] * 100:+.1f}% vs oracle",
                       "liquidation capacity": ce.get("liquidation_capacity_usd"),
                       "exit confidence": ce.get("confidence", "")})
        for s in q["shocks"]:
            q2shocks.append({"market": q["market"], "oracle move": f"{s['move'] * 100:+.0f}%",
                             "vault bad debt": s["bad_debt_vault_usd"], "loss per share": s["loss_per_share"],
                             "liquidated": s["n_liquidated"], "frozen-oracle shortfall": s["frozen_oracle_shortfall_usd"]})
    ui.table(q2rows, money=("liquidation capacity",), pcts=("debt covered", "debt with HF<1.05", "debt with HF<1.10"))
    if q2shocks:
        st.markdown("Oracle pinned on the fork, every underwater borrower liquidated → bad debt socialized to the vault")
        ui.table(q2shocks, money=("vault bad debt", "frozen-oracle shortfall"), pcts=("loss per share",))
        st.caption("Liquidations assume a liquidator exists at the shocked oracle price. Where the collateral has no "
                   "aggregator route, or a large discount at liquidation size, real recovery is lower.")
    run = m["q3"].get("run", {})
    if run.get("ranks"):
        st.markdown("**Q3 · the bank run executed on the fork**")
        ui.table([{k: x[k] for k in ("rank", "address", "owned_usd", "recovered_usd", "recovered_pct")}
                  for x in run["ranks"]], money=("owned_usd", "recovered_usd"), pcts=("recovered_pct",))
        st.markdown("Markets after the run")
        st.dataframe(run["after_run"], hide_index=True, width="stretch")
        st.caption(run["note"])

with st.expander("Roles and timelocks (read from the vault)"):
    st.markdown(f"owner `{r['owner']}` · curator `{r['curator']}`  \nallocators: "
                + ", ".join(f"`{a}`" for a in r["allocators"]) + "  \nsentinels: "
                + ", ".join(f"`{a}`" for a in r["sentinels"]))
    ui.table([{"function": k, "timelock (h)": (v["timelock_s"] or 0) / 3600, "abdicated": v["abdicated"]}
              for k, v in r["timelocks"].items()])

with st.expander("What moves the decision: base rates, tornado, attribution"):
    if not incident:
        st.markdown("**Base-rate classes** (90% interval on the event rate, and whether the calm-day answer changes)")
        ui.table([{"class": x["class"], "event": x["event"],
                   "rate": f"{x['rate'] * 100:.1f}%/yr ({x['events']} in {x['exposure_years']:.1f} yrs)",
                   "range (90%)": f"{x['low'] * 100:.1f}% – {x['high'] * 100:.1f}%", "decision": x["decision"]}
                  for x in class_ranges(ov_key, MTIME)])
    if h.get("tornado"):
        tor = sorted(h["tornado"], key=lambda t: abs(t["metric_high"] - t["metric_low"]))
        fig = go.Figure()
        fig.add_bar(y=[t["assumption"] for t in tor], x=[t["metric_low"] - t["base"] for t in tor], orientation="h",
                    name="low end", marker_color=ui.NEUTRAL, text=[str(t["low"]) for t in tor])
        fig.add_bar(y=[t["assumption"] for t in tor], x=[t["metric_high"] - t["base"] for t in tor], orientation="h",
                    name="high end", marker_color=ui.ACCENT, text=[str(t["high"]) for t in tor])
        fig.update_xaxes(title="change in net value of exiting now ($)", tickprefix="$")
        top = tor[-1]
        ui.chart(ui.clean(fig, f"{top['assumption']} moves the answer most", 320, showlegend=True, barmode="overlay"))
        ui.table([{"assumption": t["assumption"], "range": f"{t['low']} → {t['high']}", "source": t["source"]}
                  for t in reversed(tor)])
    st.markdown("**Attribution of risk-adjusted loss**")
    att = sorted(h["mc"]["attribution"].values(), key=lambda v: -v["CVaR_contrib"])
    ui.table([{"scenario": v["label"], "expected loss": v["E[L]"] * h["size_usd"],
               "worst-case contribution": v["CVaR_contrib"] * h["size_usd"], "confidence": v["confidence"],
               "time-to-impact": "immediate" if not v["time_to_impact_s"] else f"{v['time_to_impact_s'] / 60:.0f} min"}
              for v in att], money=("expected loss", "worst-case contribution"))

if m.get("pt_layers"):
    with st.expander("PT-reUSD through the brief's 5 layers (the brief's PT example, inside Belem's own vault)"):
        lay = m["pt_layers"].get("PT-reUSD-10DEC2026") or next(iter(m["pt_layers"].values()))
        ui.table([{"layer": k, "n": len(v), "nodes": ", ".join(v[:6]) + (" …" if len(v) > 6 else "")}
                  for k, v in lay.items()])

with st.expander("All findings"):
    for f in m["findings"]:
        st.markdown(f"- **{f['q']}** `{f['kind']}`: {f['why']}")
