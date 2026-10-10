import sys
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
    page_title="Exit Race | FAULT LINE",
    page_icon="🏃",
    layout="wide",
)

init_state()
apply_global_style()


# =========================================================
# CONNECT TO HERO #1 ENGINE
# =========================================================

ENGINE_ROOT = Path.home() / "Desktop" / "fault-line"

if str(ENGINE_ROOT) not in sys.path:
    sys.path.insert(0, str(ENGINE_ROOT))

try:
    from decision import hero1 as hero1_decision
except Exception as e:
    st.error(
        "Could not load the Hero #1 decision engine from "
        "`~/Desktop/fault-line`."
    )
    st.exception(e)
    st.stop()


# =========================================================
# HERO
# =========================================================

hero(
    "EXIT RACE",
    "How expensive is it to unwind this position — and does waiting help?",
    "EXECUTION-AWARE EXIT ANALYSIS",
)

badge("FORK-EXECUTED EXIT ROUTE", "real")


# =========================================================
# EXPLANATION
# =========================================================

with st.expander("What is Exit Race?"):
    st.markdown(
        """
Knowing that a position is risky is not enough.

We also need to know:

**Can we actually get out — and how much will it cost?**

FAULT LINE executes the real unwind route on an Ethereum fork:

**PT-sUSDe → sUSDe → USDC**

using:

- **Pendle** for the PT exit
- **KyberSwap** for the conversion to USDC

The engine tests several position sizes to measure how execution cost changes
as the amount being sold gets larger.

It then compares:

- exit now,
- exit over 15 minutes,
- exit over 1 hour,
- exit over 6 hours.
"""
    )


# =========================================================
# INPUTS
# =========================================================

section_label("POSITION")

c1, c2, c3 = st.columns(3)

with c1:
    scale = st.slider(
        "Position size × Hero #1 base book",
        min_value=0.25,
        max_value=4.0,
        value=1.0,
        step=0.25,
    )

with c2:
    risk_aversion = st.slider(
        "Risk aversion λ",
        min_value=0.0,
        max_value=1.0,
        value=0.5,
        step=0.05,
    )

with c3:
    horizon = st.select_slider(
        "Decision horizon",
        options=[7, 14, 30, 60, 90],
        value=30,
        format_func=lambda x: f"{x} days",
    )


# =========================================================
# RUN DECISION ENGINE
# =========================================================

@st.cache_data(show_spinner="Calculating exit economics…")
def run_engine(scale, risk_aversion, horizon):
    result = hero1_decision.headline(
        scale=scale,
        lam=risk_aversion,
        horizon_days=float(horizon),
    )

    static_data = hero1_decision.static()["data"]

    return result, static_data


try:
    result, shock_data = run_engine(
        scale,
        risk_aversion,
        horizon,
    )
except Exception as e:
    st.error("The Hero #1 exit engine failed to run.")
    st.exception(e)
    st.stop()


# =========================================================
# POSITION SUMMARY
# =========================================================

section_label("UNWIND")

size_usd = result.get("size_usd", 0)
leverage = result.get("leverage", 0)
unwind_pt_usd = shock_data.get("unwind_pt_usd", 0) * scale

p1, p2, p3 = st.columns(3)

with p1:
    metric_card(
        "Position Equity",
        f"${size_usd:,.0f}",
        f"{scale:.2f}× Hero #1",
    )

with p2:
    metric_card(
        "Gross Leverage",
        f"{leverage:.2f}×",
        "P2 Morpho loop",
    )

with p3:
    metric_card(
        "PT Exposure to Unwind",
        f"${unwind_pt_usd:,.0f}",
        "Approximate oracle value of PT sold",
    )


# =========================================================
# REAL EXECUTED CURVE
# =========================================================

section_label("FORK-EXECUTED EXIT CURVE")

st.markdown(
    """
FAULT LINE actually executes the unwind at several sizes on the Ethereum fork.

This shows how execution changes as the trade becomes larger.
"""
)

base_curve = shock_data.get("exit_curve", [])

curve_rows = []

for row in base_curve:
    curve_rows.append(
        {
            "Size": f"{row.get('x', 0):.2f}×",
            "Oracle Value ($)": row.get("oracle_value_usd", 0),
            "USDC Received": row.get("usdc_out", 0),
            "Exit Cost": row.get("cost", 0),
            "Executed": row.get("executed", False),
        }
    )

if curve_rows:
    curve_df = pd.DataFrame(curve_rows)

    st.dataframe(
        curve_df.style.format(
            {
                "Oracle Value ($)": "${:,.0f}",
                "USDC Received": "${:,.0f}",
                "Exit Cost": "{:.4%}",
            }
        ),
        hide_index=True,
        use_container_width=True,
    )

    chart_data = pd.DataFrame(
        {
            "Position Size ×": [
                float(row.get("x", 0))
                for row in base_curve
            ],
            "Exit Cost (%)": [
                float(row.get("cost", 0)) * 100
                for row in base_curve
            ],
        }
    ).set_index("Position Size ×")

    st.line_chart(chart_data)

else:
    st.warning("No executed exit curve found.")


# =========================================================
# NEGATIVE EXIT COST EXPLANATION
# =========================================================

with st.expander("Why can the exit cost be negative?"):
    st.markdown(
        """
A negative exit cost is not necessarily an error.

The engine compares:

**actual USDC received from the trade**

with:

**the oracle reference value**

Example:

- oracle value = $100
- actual execution = $100.05

Then the measured exit cost is slightly negative.

That means the market execution was marginally better than the oracle reference.
"""
    )


# =========================================================
# EXIT NOW
# =========================================================

section_label("EXIT NOW")

components = result.get("components_full_exit_now", {})

exited_usd = components.get("exited_usd", 0)
exit_cost_now = components.get("exit_cost_usd", 0)
loss_avoided = components.get("loss_avoided_usd", 0)
yield_forgone = components.get("yield_forgone_usd", 0)
net_value = components.get("net_usd", 0)

e1, e2, e3, e4 = st.columns(4)

with e1:
    metric_card(
        "Exposure Exited",
        f"${exited_usd:,.0f}",
        "Full unwind",
    )

with e2:
    metric_card(
        "Execution Cost",
        f"${exit_cost_now:,.0f}",
        "Fork-based exit curve",
    )

with e3:
    metric_card(
        "Loss Avoided",
        f"${loss_avoided:,.0f}",
        "Risk removed by leaving",
    )

with e4:
    metric_card(
        "Net Value of Exit",
        f"${net_value:+,.0f}",
        "Loss avoided − carry lost − exit cost",
    )


# =========================================================
# EXIT RACE
# =========================================================

section_label("EXIT NOW VS WAIT")

exit_cost_curve = result.get("exit_cost_curve", {})

if exit_cost_curve:
    order = ["now", "15m", "1h", "6h"]

    labels = {
        "now": "Immediately",
        "15m": "Within 15 min",
        "1h": "Within 1 hour",
        "6h": "Within 6 hours",
    }

    race_rows = []

    for key in order:
        if key in exit_cost_curve:
            race_rows.append(
                {
                    "Exit Strategy": labels[key],
                    "Execution Cost ($)": exit_cost_curve[key],
                }
            )

    race_df = pd.DataFrame(race_rows)

    st.dataframe(
        race_df.style.format(
            {
                "Execution Cost ($)": "${:,.2f}",
            }
        ),
        hide_index=True,
        use_container_width=True,
    )

    race_chart = race_df.set_index("Exit Strategy")
    st.bar_chart(race_chart)

else:
    st.warning("No exit timing curve found.")


# =========================================================
# TRANCHE MODEL
# =========================================================

section_label("WHY CAN WAITING REDUCE EXIT COST?")

st.markdown(
    """
Instead of selling everything in one large trade, the engine can split the exit
into smaller pieces.

**Example:**

- tranche 1: now
- tranche 2: after 15 min
- tranche 3: after 1 h
- tranche 4: by 6 h

Smaller trades can create less market impact than one large trade.
"""
)

st.warning(
    "The individual exit-price measurements are fork-executed. "
    "However, the multi-tranche calculation assumes liquidity refills "
    "between tranches. That refill is a model assumption."
)


# =========================================================
# DECISION
# =========================================================

section_label("RACE RESULT")

action = result.get("action", "N/A")
exit_fraction = result.get("exit_fraction", 0)

d1, d2, d3 = st.columns(3)

with d1:
    metric_card(
        "Decision",
        str(action),
        "STAY / REDUCE / EXIT",
    )

with d2:
    metric_card(
        "Recommended Exit",
        f"{exit_fraction:.0%}",
        "Fraction of the position",
    )

with d3:
    metric_card(
        "Net Value Exit Now",
        f"${result.get('net_value_exit_now_usd', 0):+,.0f}",
        "Risk-adjusted economic value",
    )


# =========================================================
# WHY
# =========================================================

with st.expander("Why did FAULT LINE choose this?"):
    reasons = result.get("reason", [])

    if reasons:
        for reason in reasons:
            st.markdown(f"- {reason}")
    else:
        st.write("No explanation returned by the engine.")


# =========================================================
# ROUTE
# =========================================================

section_label("EXECUTION ROUTE")

st.code(
    """
PT-sUSDe
   |
   v
Pendle Router
   |
   v
sUSDe
   |
   v
KyberSwap
   |
   v
USDC
""",
    language=None,
)

r1, r2, r3 = st.columns(3)

with r1:
    metric_card(
        "Step 1",
        "Pendle",
        "PT → sUSDe",
    )

with r2:
    metric_card(
        "Step 2",
        "KyberSwap",
        "sUSDe → USDC",
    )

with r3:
    metric_card(
        "Output",
        "USDC",
        "Final liquid asset",
    )


# =========================================================
# TRANSPARENCY
# =========================================================

section_label("WHAT IS REAL VS MODELED")

real_col, assumed_col = st.columns(2)

with real_col:
    st.markdown("### ✅ Executed / measured")

    st.markdown(
        """
- PT → sUSDe route
- sUSDe → USDC route
- Pendle execution
- KyberSwap execution
- 0.25× exit
- 0.50× exit
- 1.00× exit
- 2.00× exit
- resulting USDC received
- execution cost at those sizes
"""
    )

with assumed_col:
    st.markdown("### ⚠️ Modeled / assumed")

    st.markdown(
        """
- liquidity refill between tranches
- future execution conditions
- 15 min / 1 h / 6 h tranche strategy
- interpolation between measured sizes
- extrapolation beyond largest measured size
"""
    )


# =========================================================
# EXTRAPOLATION WARNING
# =========================================================

if scale > 2:
    st.warning(
        "This position size can require execution beyond the largest directly "
        "measured fork point. The engine then extrapolates using the slope "
        "of the last measured exit-curve segment."
    )


# =========================================================
# BOTTOM LINE
# =========================================================

section_label("BOTTOM LINE")

if action == "EXIT":
    st.error(
        "The engine currently finds that removing the risk is worth more than "
        "the execution cost and carry sacrificed by exiting."
    )

elif action == "REDUCE":
    st.warning(
        f"The engine recommends reducing approximately {exit_fraction:.0%} "
        "of the position."
    )

else:
    st.success(
        "The engine currently finds that the economics favor keeping the "
        "position rather than paying to exit now."
    )


# =========================================================
# NEXT
# =========================================================

section_label("NEXT")

st.info(
    "The Evidence page shows where the dependency and execution evidence came from."
)

st.page_link(
    "pages/6_Evidence.py",
    label="Open Evidence →",
    icon="🔎",
)