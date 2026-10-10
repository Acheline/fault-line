import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd
import streamlit as st

from ui_state import init_state
from ui_style import (
    apply_global_style,
    hero,
    metric_card,
    section_label,
    badge,
)


# =========================================================
# PAGE SETUP
# =========================================================

st.set_page_config(
    page_title="Assumptions | FAULT LINE",
    page_icon="🎚️",
    layout="wide",
)

init_state()
apply_global_style()


# =========================================================
# CONNECT TO ENGINE
# =========================================================

ENGINE_ROOT = Path.home() / "Desktop" / "fault-line"

if str(ENGINE_ROOT) not in sys.path:
    sys.path.insert(0, str(ENGINE_ROOT))


try:
    from core.config import SOURCE, assumptions
except Exception as e:
    st.error("Could not load assumptions from the FAULT LINE engine.")
    st.exception(e)
    st.stop()


# =========================================================
# SHARED OVERRIDES
# =========================================================

if "overrides" not in st.session_state:
    st.session_state["overrides"] = {}

overrides = st.session_state["overrides"]


# =========================================================
# HERO
# =========================================================

hero(
    "ASSUMPTIONS",
    "See every value that is assumed rather than measured, where it came from, and which ones are still fallback priors.",
    "MODEL TRANSPARENCY",
)

badge("ASSUMPTIONS ARE EXPLICIT", "model")


# =========================================================
# HEADLINE
# =========================================================

section_label("WHY THIS PAGE EXISTS")

st.markdown(
    """
FAULT LINE separates **measured evidence** from **model assumptions**.

That matters because the decision engine should never make a modeled number
look like an observed fact.

This page exposes the assumptions used by the engine and their sources.
"""
)

st.caption(f"Primary assumptions source: {SOURCE}")


# =========================================================
# RESET
# =========================================================

if st.button("Reset all assumptions to defaults"):
    overrides.clear()

    for key in list(st.session_state.keys()):
        if str(key).startswith("assumption_slider_"):
            del st.session_state[key]

        if str(key).startswith("assumption_toggle_"):
            del st.session_state[key]

    st.rerun()


# =========================================================
# LOAD ASSUMPTIONS
# =========================================================

try:
    all_assumptions = list(assumptions(overrides))
except Exception as e:
    st.error("Could not parse assumptions.")
    st.exception(e)
    st.stop()


# =========================================================
# SUMMARY
# =========================================================

n_total = len(all_assumptions)
n_changed = len(overrides)

placeholder_items = [
    a
    for a in all_assumptions
    if getattr(a, "placeholder_prior", False)
]

numeric_items = [
    a
    for a in all_assumptions
    if getattr(a, "numeric", False)
]


s1, s2, s3, s4 = st.columns(4)

with s1:
    metric_card(
        "Assumptions",
        str(n_total),
        "Values exposed by the model",
    )

with s2:
    metric_card(
        "Changed",
        str(n_changed),
        "Modified from defaults",
    )

with s3:
    metric_card(
        "Fallback Priors",
        str(len(placeholder_items)),
        "Used only when better data is unavailable",
    )

with s4:
    metric_card(
        "Numeric Inputs",
        str(len(numeric_items)),
        "Potential slider-controlled values",
    )


# =========================================================
# GROUP BY SECTION
# =========================================================

by_section = defaultdict(list)

for item in all_assumptions:
    section = getattr(item, "section", "Other")
    by_section[section].append(item)


# =========================================================
# DISPLAY
# =========================================================

section_label("MODEL INPUTS")

for section_name, items in by_section.items():

    expanded = str(section_name).startswith(("1.", "3.", "5."))

    with st.expander(section_name, expanded=expanded):

        if str(section_name).startswith("7."):
            st.error(
                "Fallback priors: these values are used only if the "
                "data-derived base-rate calculation is unavailable."
            )

        for item in items:

            key = getattr(item, "key", "")
            value = getattr(item, "value", None)
            default = getattr(item, "default", None)
            source = getattr(item, "source", "")
            numeric = getattr(item, "numeric", False)
            slider = getattr(item, "slider", None)
            placeholder = getattr(
                item,
                "placeholder_prior",
                False,
            )

            st.markdown("---")

            top1, top2 = st.columns([3, 1])

            with top1:
                st.markdown(f"### `{key}`")

                if placeholder:
                    st.markdown("🔴 **FALLBACK PRIOR**")

                if source:
                    st.caption(f"Source: {source}")

            with top2:
                if key in overrides:
                    badge("OVERRIDDEN", "model")
                else:
                    badge("DEFAULT", "real")


            # =============================================
            # NUMERIC WITH SLIDER
            # =============================================

            if numeric and slider:

                lo, hi, step = slider
                is_int = isinstance(default, int) and not isinstance(
                    default,
                    bool,
                )

                widget_key = (
                    "assumption_slider_"
                    + key.replace(".", "_")
                    .replace(" ", "_")
                    .replace("/", "_")
                )

                current_value = overrides.get(key, value)

                if is_int:
                    new_value = st.slider(
                        "Value",
                        min_value=int(lo),
                        max_value=int(hi),
                        value=int(current_value),
                        step=int(step),
                        key=widget_key,
                    )
                else:
                    new_value = st.slider(
                        "Value",
                        min_value=float(lo),
                        max_value=float(hi),
                        value=float(current_value),
                        step=float(step),
                        key=widget_key,
                    )

                if new_value != default:
                    overrides[key] = new_value
                else:
                    overrides.pop(key, None)

                c1, c2 = st.columns(2)

                with c1:
                    st.caption(f"Default: {default}")

                with c2:
                    st.caption(f"Current: {new_value}")


            # =============================================
            # BOOLEAN
            # =============================================

            elif isinstance(default, bool):

                widget_key = (
                    "assumption_toggle_"
                    + key.replace(".", "_")
                    .replace(" ", "_")
                    .replace("/", "_")
                )

                current_value = overrides.get(key, value)

                new_value = st.toggle(
                    "Value",
                    value=bool(current_value),
                    key=widget_key,
                )

                if new_value != default:
                    overrides[key] = new_value
                else:
                    overrides.pop(key, None)

                c1, c2 = st.columns(2)

                with c1:
                    st.caption(f"Default: {default}")

                with c2:
                    st.caption(f"Current: {new_value}")


            # =============================================
            # NON-NUMERIC
            # =============================================

            else:

                c1, c2 = st.columns(2)

                with c1:
                    st.markdown("**Current value**")
                    st.code(str(value))

                with c2:
                    st.markdown("**Default value**")
                    st.code(str(default))


# =========================================================
# CHANGED VALUES
# =========================================================

section_label("CHANGED FROM DEFAULTS")

if overrides:

    defaults = {
        a.key: a.default
        for a in assumptions({})
    }

    changed_rows = []

    for key, value in overrides.items():

        changed_rows.append(
            {
                "Assumption": key,
                "Current": value,
                "Default": defaults.get(key),
            }
        )

    st.dataframe(
        pd.DataFrame(changed_rows),
        hide_index=True,
        use_container_width=True,
    )

else:
    st.success(
        "No assumptions have been changed. "
        "The model is using the defaults."
    )


# =========================================================
# PLACEHOLDER PRIORS
# =========================================================

section_label("FALLBACK PRIORS")

if placeholder_items:

    prior_rows = []

    for item in placeholder_items:
        prior_rows.append(
            {
                "Key": getattr(item, "key", ""),
                "Value": getattr(item, "value", None),
                "Source": getattr(item, "source", ""),
            }
        )

    st.dataframe(
        pd.DataFrame(prior_rows),
        hide_index=True,
        use_container_width=True,
    )

    st.error(
        "These are fallback guesses, not measured observations. "
        "They should only be used when the computed base-rate source fails."
    )

else:
    st.success("No fallback priors are active.")


# =========================================================
# TRANSPARENCY
# =========================================================

section_label("HOW TO READ THIS PAGE")

left, right = st.columns(2)

with left:
    st.markdown("### ✅ Stronger evidence")

    st.markdown(
        """
- fork execution
- on-chain reads
- traces
- storage inspection
- live API measurements
- computed historical base rates
"""
    )

with right:
    st.markdown("### ⚠️ Model layer")

    st.markdown(
        """
- risk aversion λ
- future incident frequency
- future severity distribution
- correlation assumptions
- mandate constraints
- fallback priors
"""
    )


# =========================================================
# BOTTOM LINE
# =========================================================

section_label("BOTTOM LINE")

st.info(
    "FAULT LINE does not hide assumptions inside the model. "
    "They are listed, sourced and editable so judges can distinguish "
    "measured evidence from modeled judgment."
)