"""Base rates page: every probability the Monte Carlo uses, computed from data; red badge if it fell back."""
import time

import pandas as pd
import streamlit as st

from app.state import placeholder_badge
from core.config import PLACEHOLDER
from risk.base_rates import load

st.title("📊 Base rates")
st.caption("Computed from DefiLlama hacks, protocol TVL history, daily stablecoin prices and on-chain oracle update "
           "history. Rebuild with `python -m risk.base_rates`. A red badge means the fetch failed and the "
           "ASSUMED_ANSWERS.md fallback prior is in use.")
br = load()
st.caption(f"generated {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime(br['generated_at']))}")

n_fb = sum(v["status"] == PLACEHOLDER for v in br["values"].values())
if n_fb:
    st.markdown(placeholder_badge(f"{n_fb} value(s) on placeholder_prior") + " replace before the demo",
                unsafe_allow_html=True)
else:
    st.success("All base rates computed from data (no placeholder priors in use).")

rows = []
for k, v in br["values"].items():
    val = v["value"]
    rows.append({"base rate": k, "value": f"{val:.4f}" if isinstance(val, float) else "see detail",
                 "status": v["status"], "source": v["source"]})
df = pd.DataFrame(rows)
st.dataframe(df.style.map(lambda s: "background-color:#c92a2a;color:white" if s == PLACEHOLDER else "",
                          subset=["status"]), hide_index=True, width="stretch")
for k, v in br["values"].items():
    if v["status"] == PLACEHOLDER:
        st.markdown(f"{placeholder_badge()} **{k}** = {v['value']} ({v['source']}) · error: `{v.get('error', '')}`",
                    unsafe_allow_html=True)

st.subheader("Method parameters")
st.dataframe(pd.DataFrame([{"parameter": k, **v} for k, v in br.get("method_params", {}).items()]),
             hide_index=True, width="stretch")

ex = br["detail"].get("exploit")
if ex:
    st.subheader("Material exploits per protocol-year")
    st.caption(ex["method"])
    c = st.columns(3)
    c[0].metric("Hacks matched (window)", ex["n_hacks_matched"])
    c[1].metric("Material (≥1% of TVL)", ex["n_material"])
    c[2].metric("Protocols with imputed listing date", ex.get("n_listed_imputed", 0))
    b = pd.DataFrame([{"bucket": k, **v} for k, v in ex["buckets"].items()])
    b[["category", "age", "tvl"]] = b["bucket"].str.split("|", expand=True)
    st.dataframe(b.pivot_table(index=["category", "age"], columns="tvl", values="p_annual").round(4), width="stretch")
    st.markdown("**Loss given exploit by size** (median net loss / TVL before)")
    st.dataframe(pd.DataFrame(ex["lgd_by_tvl_bucket"]).T, width="stretch")

dp = br["detail"].get("depeg")
if dp:
    st.subheader("Stablecoin depegs (daily prices)")
    st.caption(dp["method"])
    rows = []
    for cls, v in dp["classes"].items():
        for t, x in v["thresholds"].items():
            rows.append({"class": cls, "below": t, "coin_years": v["coin_years"], "episodes": x["episodes"],
                         "episodes >24h": x["episodes_over_24h"], "p/yr": x["p_annual"], "p/yr >24h": x["p_annual_over_24h"],
                         "median days": x["median_duration_days"], "median trough": x["median_trough"]})
    st.dataframe(pd.DataFrame(rows).round(4), hide_index=True, width="stretch")
    with st.expander("Per coin"):
        st.dataframe(pd.DataFrame([{"class": c, "coin": k, **x} for c, v in dp["classes"].items()
                                   for k, x in v["coins"].items()]).round(4), hide_index=True, width="stretch")

os_ = br["detail"].get("oracle_stale")
if os_:
    st.subheader("Oracle staleness (full on-chain update history)")
    st.dataframe(pd.DataFrame(os_).T, width="stretch")
