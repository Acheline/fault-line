"""Assumptions & data: every assumed value (with a slider) and every base rate computed from data.
Overrides live in st.session_state and are passed into every headline() call through app.state.overrides()."""
import time
from collections import defaultdict

import pandas as pd
import streamlit as st

from app import ui
from app.state import overrides, placeholder_badge
from core.config import PLACEHOLDER, SOURCE, assumptions
from risk.base_rates import load

# the keys the headline computations read (decision/hero{1,2,3}.py); the others configure watch mode and the
# offline fork pipeline, whose cached results these sliders do not re-run
DRIVES_HEADLINES = {"mandate.aum_usd", "mandate.mandate_usd", "risk.lambda", "risk.pocket_var95_hard_limit",
                    "risk.book_cvar95_single_incident_bps", "sizing.ticket_usd", "sizing.max_share_curated_vault_tvl",
                    "exit.tranche_times_minutes", "exit.max_tranches"}

ui.setup("🎚️ Assumptions & data", "What we assumed (pending Belem's answers) and what we computed from data.")
ov = overrides()
br = load()
n_fb = sum(v["status"] == PLACEHOLDER for v in br["values"].values())
allv = assumptions(ov)
st.markdown(f"<div style='font-size:20px;margin:4px 0 8px 0'><b>{len(allv)}</b> assumptions, <b>"
            f"{sum(a.key in DRIVES_HEADLINES for a in allv)}</b> of them drive the headlines · <b>{len(br['values'])}"
            f"</b> base rates computed from data, <b>{n_fb}</b> on a fallback prior</div>", unsafe_allow_html=True)
ui.findings([
    "Sliders marked <b>● drives the headlines</b> change the numbers on every page right away (bps basis, budgets, "
    "default deposit, exit tranches; λ sets the Dependencies default; the Belem vault page keeps its own λ, default 0).",
    "The other values configure watch mode and the offline fork pipeline: changing them here does not re-run the "
    "cached fork measurements.",
    f"Source of every assumed value: <b>{SOURCE}</b>. Each one is replaced as soon as Belem answers (QUESTIONS.md)."])



def _wkey(a) -> str:
    return f"tg_{a.key}" if isinstance(a.default, bool) else f"sl_{a.key}"


def _cast(a, v):
    return bool(v) if isinstance(a.default, bool) else int(v) if isinstance(a.default, int) else float(v)


def _reset() -> None:
    """Button callback (runs before the widgets are drawn): every widget's state back to its default."""
    ov.clear()
    for a in assumptions():
        if (a.numeric and a.slider) or isinstance(a.default, bool):
            st.session_state[_wkey(a)] = _cast(a, a.default)


# the widgets are driven by session state only (no value= argument): seeded once from the current value, so leaving
# and coming back to this page keeps the overrides, and the reset above really moves the sliders back
for a in allv:
    if (a.numeric and a.slider) or isinstance(a.default, bool):
        st.session_state.setdefault(_wkey(a), _cast(a, a.value))

st.button("Reset all to ASSUMED_ANSWERS.md", on_click=_reset)

st.markdown("### Assumptions")
by_section = defaultdict(list)
for a in allv:
    by_section[a.section].append(a)
for section, items in by_section.items():
    n_used = sum(a.key in DRIVES_HEADLINES for a in items)
    with st.expander(f"{section}" + (f"  ·  ● {n_used} drive the headlines" if n_used else "  ·  reference only")):
        if section.startswith("7."):
            st.markdown(placeholder_badge() + " fallback priors: used **only** if the base-rate fetch fails "
                        "(see Base rates below).", unsafe_allow_html=True)
        for a in items:
            label = (f"`{a.key}`" + ("  ● drives the headlines" if a.key in DRIVES_HEADLINES else "")
                     + ("  · placeholder_prior" if a.placeholder_prior else ""))
            if a.numeric and a.slider:
                lo, hi, step = a.slider
                is_int = isinstance(a.default, int)
                v = st.slider(label, min_value=int(lo) if is_int else float(lo),
                              max_value=int(hi) if is_int else float(hi),
                              step=int(step) if is_int else float(step), key=_wkey(a),
                              help=f"default {a.default} · {a.source}")
                if v != a.default:
                    ov[a.key] = v
                else:
                    ov.pop(a.key, None)
            elif isinstance(a.default, bool):
                v = st.toggle(label, key=_wkey(a), help=a.source)
                if v != a.default:
                    ov[a.key] = v
                else:
                    ov.pop(a.key, None)
            else:
                st.markdown(f"{label}: `{a.value}`")

with st.expander("Changed from ASSUMED_ANSWERS.md", expanded=bool(ov)):
    if ov:
        st.dataframe(pd.DataFrame([{"key": k, "value": v, "default": next(a.default for a in assumptions() if a.key == k)}
                                   for k, v in ov.items()]), hide_index=True, width="stretch")
    else:
        st.write("Nothing: all values are the assumed defaults.")

# ------------------------------------------------------------------------------------------------- base rates
st.markdown("### Base rates (computed from data)")
st.caption("DefiLlama hacks, protocol TVL history, daily stablecoin prices and on-chain oracle update history. "
           f"Generated {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime(br['generated_at']))}; rebuild with "
           "`python -m risk.base_rates`. A red badge means the fetch failed and the fallback prior is in use.")
with st.expander("Every probability the Monte Carlo uses", expanded=False):
    if n_fb:
        st.markdown(placeholder_badge(f"{n_fb} value(s) on placeholder_prior"), unsafe_allow_html=True)
    else:
        st.success("All base rates computed from data (no placeholder priors in use).")
    df = pd.DataFrame([{"base rate": k, "value": f"{v['value']:.4f}" if isinstance(v["value"], float) else "see detail",
                        "status": v["status"], "source": v["source"]} for k, v in br["values"].items()])
    st.dataframe(df.style.map(lambda s: "background-color:#c92a2a;color:white" if s == PLACEHOLDER else "",
                              subset=["status"]), hide_index=True, width="stretch")
    for k, v in br["values"].items():
        if v["status"] == PLACEHOLDER:
            st.markdown(f"{placeholder_badge()} **{k}** = {v['value']} ({v['source']}) · error: `{v.get('error', '')}`",
                        unsafe_allow_html=True)
    st.markdown("**Method parameters**")
    st.dataframe(pd.DataFrame([{"parameter": k, **v} for k, v in br.get("method_params", {}).items()]),
                 hide_index=True, width="stretch")

ex = br["detail"].get("exploit")
if ex:
    with st.expander("Material exploits per protocol-year"):
        st.caption(ex["method"])
        k = st.columns(3)
        k[0].metric("Hacks matched (window)", ex["n_hacks_matched"])
        k[1].metric("Material (≥1% of TVL)", ex["n_material"])
        k[2].metric("Protocols with imputed listing date", ex.get("n_listed_imputed", 0))
        b = pd.DataFrame([{"bucket": k, **v} for k, v in ex["buckets"].items()])
        b[["category", "age", "tvl"]] = b["bucket"].str.split("|", expand=True)
        st.dataframe(b.pivot_table(index=["category", "age"], columns="tvl", values="p_annual").round(4), width="stretch")
        st.markdown("**Loss given exploit by size** (median net loss / TVL before)")
        st.dataframe(pd.DataFrame(ex["lgd_by_tvl_bucket"]).T, width="stretch")

dp = br["detail"].get("depeg")
if dp:
    with st.expander("Stablecoin depegs (daily prices)"):
        st.caption(dp["method"])
        rows = []
        for cls, v in dp["classes"].items():
            for t, x in v.get("thresholds", {}).items():   # NAV-token class has episodes only
                rows.append({"class": cls, "below": t, "coin_years": v["coin_years"], "episodes": x["episodes"],
                             "episodes >24h": x["episodes_over_24h"], "p/yr": x["p_annual"],
                             "p/yr >24h": x["p_annual_over_24h"], "median days": x["median_duration_days"],
                             "median trough": x["median_trough"]})
        st.dataframe(pd.DataFrame(rows).round(4), hide_index=True, width="stretch")
        st.markdown("**Per coin**")
        st.dataframe(pd.DataFrame([{"class": c, "coin": k, **x} for c, v in dp["classes"].items()
                                   for k, x in (v.get("coins") or {}).items()]).round(4), hide_index=True, width="stretch")

os_ = br["detail"].get("oracle_stale")
if os_:
    with st.expander("Oracle staleness (full on-chain update history)"):
        st.dataframe(pd.DataFrame(os_).T, width="stretch")
