"""Vault view: hero #2 (Belem / RockawayX vaults) answered as three questions, every number from the fork."""
import json

import pandas as pd
import streamlit as st

from core.fork import ROOT

SRC = ROOT / "data" / "graphs" / "hero2.json"
st.title("🏦 Vault view · Belem / RockawayX vaults")
if not SRC.exists():
    st.warning("No vault graph yet. Run `python -m discovery.hero2` (add `--offline` to replay from cache).")
    st.stop()
m = json.loads(SRC.read_text())["meta"]
r = m["q1"]["roles"]
wn = m["q3"]["withdrawable_now"]
tot = r["total_assets_usd"]
instant = wn["idle_usd"] + wn["instant_from_liquidity_market_usd"]

st.caption(f"**{r['name']}** ({r['symbol']}) · [{m['vault']}](https://etherscan.io/address/{m['vault']}) · "
           f"fork block **{m['fork_block']}** · one of the challenge setter's own curated vaults")

# ---------------------------------------------------------------- HEADLINE
HL = ROOT / "data" / "shocks" / "hero2.json"
if HL.exists():
    from decision import hero2 as D2

    @st.cache_data(show_spinner="Running Monte Carlo on the fork-measured scenarios…")
    def _headline(size, rank, lam, horizon, rho, gov, incident, mtime):
        return D2.headline(size_usd=size, rank=rank, lam=lam, horizon_days=horizon, rho=rho, governance=gov,
                           incident=incident)

    with st.sidebar:
        st.markdown("**Your position**")
        size = st.slider("Deposit size ($)", 100_000, 10_000_000,
                         int(min(5e6, 0.15 * r["total_assets_usd"])), 50_000,
                         help="default: ASSUMED_ANSWERS §4 ticket, capped at 15% of vault TVL (P5)")
        rank = st.number_input("Your rank in the exit queue", 1, 11, 1,
                               help="1 = you exit first; n = the n-1 largest real depositors exit before you")
        lam = st.slider("Risk aversion λ", 0.0, 1.0, 0.5, 0.05, help="ASSUMED_ANSWERS §3")
        horizon = st.select_slider("Horizon (days)", [7, 14, 30, 60, 90], 30, help="assumption")
        rho = st.slider("Correlation between drivers ρ", 0.0, 0.8, 0.3, 0.1, help="assumption (Gaussian copula)")
        gov = st.toggle("Governance shock: curator sets penalty to 2% (no timelock)", False)
        st.markdown("**Situation**")
        sit = st.radio("trUSD now", ["calm (no incident)", "observed depeg"], index=0,
                       help="observed: the trUSD event is certain, its final depth is drawn from episodes that went "
                            "at least this deep, other depositors run, the frozen-oracle loss lands on those who stay")
        incident = st.slider("Observed trUSD depth", 0.01, 0.5, 0.05, 0.01) if sit != "calm (no incident)" else None
    h = _headline(float(size), int(rank), lam, float(horizon), rho, gov, incident, HL.stat().st_mtime)
    color = {"STAY": "#2b8a3e", "REDUCE": "#e67700", "EXIT": "#c92a2a"}[h["action"]]
    act = h["action"] + (f" {h['exit_fraction']:.0%}" if h["action"] == "REDUCE" else "")
    st.markdown(
        f"<div style='display:flex;gap:28px;align-items:baseline;flex-wrap:wrap'>"
        f"<div><div style='font-size:13px;opacity:.7'>Net value of exiting now</div>"
        f"<div style='font-size:44px;font-weight:700'>{h['net_value_exit_now_bps_book']:+.1f} bps</div>"
        f"<div style='font-size:13px;opacity:.7'>of the {h['bps_basis']} (main) · "
        f"{h['net_value_exit_now_bps_aum']:+.2f} bps of Belem's ~${h['aum_usd'] / 1e6:,.0f}M AUM (secondary)</div>"
        f"<div style='font-size:20px'>${h['net_value_exit_now_usd']:+,.0f}</div></div>"
        f"<div style='font-size:40px;font-weight:800;color:{color}'>{act}</div></div>", unsafe_allow_html=True)
    cf = h["components_full_exit_now"]
    st.caption(f"Full exit now = risk-adjusted loss avoided ${cf['loss_avoided_usd']:,.0f} − yield forgone "
               f"${cf['yield_forgone_usd']:,.0f} (vault APY {h['carry']['vault_apy']:.2%}, {h['carry']['source']}) − "
               f"exit cost ${cf['exit_cost_usd']:,.0f} = ${cf['net_usd']:+,.0f}. Sanity: E[L] annualized "
               f"{h['sanity']['E[L]_annualized']:.2%} vs vault APY {h['sanity']['vault_apy']:.2%}.")
    if h["locked_now"]:
        q = h["queue_plan"]
        st.warning(f"Locked: the depositors ahead of you (${h['ahead_usd']:,.0f}) exhaust the reachable liquidity. "
                   f"Queue a full exit: {q['recoverable_24h_pct']:.0%} recoverable by 24 h.")
    if h["hard_budget_hit"]:
        st.error("Hard budget hit: pocket VaR95 above the 20% limit (ASSUMED_ANSWERS §3).")
    be, dr = h["breakeven"], h["driver"]
    k = st.columns(4)
    k[0].metric("Expected loss (stay)", f"${h['loss_usd']['E[L]']:,.0f}", f"CVaR95 ${h['loss_usd']['CVaR95']:,.0f}",
                delta_color="off")
    k[1].metric("Breakeven belief", f"{be['p_breakeven']:.1%}" if be["p_breakeven"] is not None else "n/a",
                f"our estimate {be['p_estimate']:.1%}" if be["p_estimate"] is not None else None, delta_color="off",
                help=f"P({be['event']}) above which exiting now pays")
    k[2].metric("#1 driver", dr["driver"] or "-", f"{(dr['share_of_risk_adjusted_loss'] or 0):.0%} of risk-adj. loss",
                delta_color="off")
    k[3].metric("Time-to-impact", "0 (silent)" if not dr["time_to_impact_s"] else f"{dr['time_to_impact_s'] / 60:.0f} min",
                f"confidence: {dr['confidence']}", delta_color="off")
    for line in h["reason"]:
        st.markdown(f"- {line}")

    a1, a2 = st.columns(2)
    with a1:
        st.markdown("**Attribution of risk-adjusted loss** (scenario, confidence, family)")
        att = pd.DataFrame([{"scenario": v["label"], "E[L] $": v["E[L]"] * h["size_usd"],
                             "tail $": v["CVaR_contrib"] * h["size_usd"], "confidence": v["confidence"],
                             "time-to-impact": "0" if not v["time_to_impact_s"] else f"{v['time_to_impact_s'] / 60:.0f} min"}
                            for v in h["mc"]["attribution"].values()]).sort_values("tail $", ascending=False)
        st.dataframe(att, hide_index=True, width="stretch",
                     column_config={c: st.column_config.NumberColumn(format="dollar") for c in ("E[L] $", "tail $")})
    with a2:
        st.markdown(f"**Exit race at rank {h['rank']}** (${h['ahead_usd']:,.0f} of claims ahead of you)")
        race = pd.DataFrame([{"t": t, "recovered %": v["recovered_pct"], "penalty $": v["penalty_usd"]}
                             for t, v in h["exit_race"]["by_time"].items()])
        st.bar_chart(race.set_index("t")["recovered %"])
        tte = h["exit_race"]["time_to_full_exit_s"]
        st.caption(f"Time to full exit: {'now' if tte == 0 else '%.1f h' % (tte / 3600) if tte is not None else 'not within a year'} · refill speed "
                   "from 29 measured 100%-utilization episodes (Morpho history) · penalty "
                   f"{h['penalty']:.2%}{' (governance shock)' if gov else ''}")
    if h.get("tornado"):
        st.markdown("**What moves the decision** (net value of exiting now, $)")
        tor = pd.DataFrame([{"assumption": t["assumption"], "low": t["metric_low"] - t["base"],
                             "high": t["metric_high"] - t["base"], "range": f"{t['low']} → {t['high']}",
                             "source": t["source"]} for t in h["tornado"]])
        st.bar_chart(tor.set_index("assumption")[["low", "high"]], horizontal=True, stack=False)
        st.dataframe(tor[["assumption", "range", "source"]], hide_index=True, width="stretch")
    st.divider()
c = st.columns(4)
c[0].metric("Total assets", f"${tot / 1e6:,.2f}M")
c[1].metric("Instantly withdrawable", f"${instant / 1e6:,.2f}M", f"{instant / tot:.1%} of vault", delta_color="off")
c[2].metric("Reachable with forceDeallocate", f"${wn['total_reachable_usd'] / 1e6:,.2f}M",
            f"penalty {wn['force_deallocate_penalty']:.2%}", delta_color="off")
c[3].metric("Top depositor", f"{m['q3']['depositor_concentration']['top1_share']:.1%}",
            f"top 5: {m['q3']['depositor_concentration']['top5_share']:.1%}", delta_color="off")

# ---------------------------------------------------------------- Q1
st.header("Q1 · Where does the money go?")
basis = m["oracle_quality"].get("per_market", {})
st.dataframe(pd.DataFrame([{
    "market": x["collateral_symbol"], "allocation $": x["allocation_usd"], "share": x["allocation_pct"],
    "cap $": x["caps"]["market"]["absolute_usd"], "LLTV": x["lltv"], "utilization": x["utilization"],
    "free liquidity $": x["free_liquidity_usd"], "vault share of market": x["vault_share_of_market"],
    "root asset": x["root_symbol"], "price basis": basis.get(x["collateral_symbol"], {}).get("price_basis"),
    "oracle feeds": ", ".join(basis.get(x["collateral_symbol"], {}).get("executed_leaf_feeds", [])),
    "oracle confidence": basis.get(x["collateral_symbol"], {}).get("confidence", ""),
    "liquidity market": "✔" if x["is_liquidity_market"] else ""} for x in m["q1"]["markets"]]),
    hide_index=True, width="stretch",
    column_config={k: st.column_config.NumberColumn(format="percent" if k in ("share", "LLTV", "utilization",
                   "vault share of market") else "dollar") for k in ("allocation $", "share", "cap $", "LLTV",
                   "utilization", "free liquidity $", "vault share of market")})
ex = m["q1"]["exposure"]
cols = st.columns(4)
for col, key, title in zip(cols, ("root_asset", "price_basis", "protocol", "collateral"),
                           ("By root asset (on-chain wrapper chain)", "By oracle price basis", "By protocol",
                            "By collateral")):
    col.markdown(f"**{title}**")
    col.bar_chart(pd.Series(ex.get(key, {}), name="share of vault"), horizontal=True)
st.caption("Curator's published caps (RockawayX risk framework): single protocol 25%, single oracle 40%, correlated "
           "assets 40%, single chain 60%. Compare with the measured shares above; correlated assets are grouped by "
           "the wrapper chain read on-chain, not by label.")
with st.expander("Roles and timelocks (read from the vault)"):
    st.markdown(f"owner `{r['owner']}` · curator `{r['curator']}`  \nallocators: "
                + ", ".join(f"`{a}`" for a in r["allocators"]) + "  \nsentinels: "
                + ", ".join(f"`{a}`" for a in r["sentinels"]))
    st.dataframe(pd.DataFrame([{"function": k, "timelock h": (v["timelock_s"] or 0) / 3600, "abdicated": v["abdicated"]}
                               for k, v in r["timelocks"].items()]), hide_index=True, width="stretch")

# ---------------------------------------------------------------- Q2
st.header("Q2 · Can borrowers repay?")
rows, shocks = [], []
for q in m["q2"]:
    hb = q["hf_buckets"]
    ce = q["collateral_exit"]
    rows.append({"market": q["market"], "borrowers read": q["n_borrowers_read"],
                 "debt covered": q["debt_covered_usd"] / q["market_borrow_usd"] if q["market_borrow_usd"] else None,
                 "debt HF<1.05": hb["<1.00 (liquidatable)"]["debt_share"] + hb["1.00-1.05"]["debt_share"],
                 "debt HF<1.10": sum(hb[k]["debt_share"] for k in ("<1.00 (liquidatable)", "1.00-1.05", "1.05-1.10")),
                 "collateral exit at liq. size": "no route" if ce.get("usdc_out") is None else f"{ce['discount_vs_oracle']:+.1%} vs oracle",
                 "liquidation capacity $": ce.get("liquidation_capacity_usd"),
                 "exit confidence": ce.get("confidence", "")})
    for s in q["shocks"]:
        shocks.append({"market": q["market"], "oracle move": f"{s['move']:+.0%}", "vault bad debt $": s["bad_debt_vault_usd"],
                       "loss per share": s["loss_per_share"], "liquidated": s["n_liquidated"],
                       "frozen-oracle shortfall $": s["frozen_oracle_shortfall_usd"]})
st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch",
             column_config={k: st.column_config.NumberColumn(format="percent") for k in ("debt covered", "debt HF<1.05", "debt HF<1.10")})
sd = pd.DataFrame(shocks)
if not sd.empty:
    st.markdown("**Oracle pinned on the fork, every underwater borrower liquidated → bad debt socialized to the vault**")
    st.bar_chart(sd.pivot(index="oracle move", columns="market", values="vault bad debt $"), stack=True)
    st.dataframe(sd, hide_index=True, width="stretch")
    st.caption("Liquidations assume a liquidator exists at the shocked oracle price. Where the collateral has no "
               "aggregator route, or a large discount at liquidation size, real recovery is lower. Frozen-oracle "
               "shortfall: the loss that stays hidden if the price feed does not move while the value falls.")

# ---------------------------------------------------------------- Q3
st.header("Q3 · Can depositors withdraw?")
run = m["q3"].get("run", {})
if run.get("ranks"):
    rk = pd.DataFrame(run["ranks"])
    st.markdown("**Bank run executed on the fork: depositors exit in size order, each one drains liquidity for the next**")
    st.bar_chart(rk.set_index(rk["rank"].astype(str) + " · " + rk["address"].str[:8])["recovered_pct"])
    st.dataframe(rk[["rank", "address", "owned_usd", "recovered_usd", "recovered_pct"]], hide_index=True, width="stretch",
                 column_config={"owned_usd": st.column_config.NumberColumn(format="dollar"),
                                "recovered_usd": st.column_config.NumberColumn(format="dollar"),
                                "recovered_pct": st.column_config.NumberColumn(format="percent")})
    st.markdown("**Markets after the run**")
    st.dataframe(pd.DataFrame(run["after_run"]), hide_index=True, width="stretch")
    st.caption(run["note"])

st.header("Findings")
for f in m["findings"]:
    st.markdown(f"- **{f['q']}** `{f['kind']}`: {f['why']}")
