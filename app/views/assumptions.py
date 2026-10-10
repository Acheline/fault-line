"""Assumptions page: every assumed value, its source, and a slider. Overrides live in st.session_state and are
read by every other page through app.state.overrides()."""
from collections import defaultdict

import pandas as pd
import streamlit as st

from app.state import overrides, placeholder_badge
from core.config import SOURCE, assumptions

st.title("🎚️ Assumptions")
st.caption(f"Source of every value below: **{SOURCE}**. Move a slider to see its effect on the other pages; "
           "nothing here is measured, so each one gets replaced as soon as Belem answers (QUESTIONS.md).")

ov = overrides()
if st.button("Reset all to ASSUMED_ANSWERS.md"):
    ov.clear()
    st.rerun()

by_section = defaultdict(list)
for a in assumptions(ov):
    by_section[a.section].append(a)

for section, items in by_section.items():
    with st.expander(section, expanded=section.startswith(("1.", "3.", "5."))):
        if section.startswith("7."):
            st.markdown(placeholder_badge() + " fallback priors: used **only** if the base-rate fetch fails "
                        "(see Base rates). Replace with computed values before the demo.", unsafe_allow_html=True)
        for a in items:
            label = f"`{a.key}`" + ("  · placeholder_prior" if a.placeholder_prior else "")
            if a.numeric and a.slider:
                lo, hi, step = a.slider
                is_int = isinstance(a.default, int)
                v = st.slider(label, min_value=int(lo) if is_int else float(lo),
                              max_value=int(hi) if is_int else float(hi),
                              value=int(a.value) if is_int else float(a.value),
                              step=int(step) if is_int else float(step), key=f"sl_{a.key}",
                              help=f"default {a.default} · {a.source}")
                if v != a.default:
                    ov[a.key] = v
                else:
                    ov.pop(a.key, None)
            elif isinstance(a.default, bool):
                v = st.toggle(label, value=bool(a.value), key=f"tg_{a.key}", help=a.source)
                if v != a.default:
                    ov[a.key] = v
                else:
                    ov.pop(a.key, None)
            else:
                st.markdown(f"{label}: `{a.value}`")

st.subheader("Changed from ASSUMED_ANSWERS.md")
if ov:
    st.dataframe(pd.DataFrame([{"key": k, "value": v, "default": next(a.default for a in assumptions() if a.key == k)}
                               for k, v in ov.items()]), hide_index=True, width="stretch")
else:
    st.write("Nothing: all values are the assumed defaults.")
