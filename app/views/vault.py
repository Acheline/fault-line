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
                 "collateral exit at liq. size": "no route" if not ce.get("route") else f"{ce['discount_vs_oracle']:+.1%} vs oracle"})
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
