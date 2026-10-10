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
    shock_banner,
)


# =========================================================
# PAGE SETUP
# =========================================================

st.set_page_config(
    page_title="Risk Analysis | FAULT LINE",
    page_icon="📊",
    layout="wide",
)

init_state()
apply_global_style()


# =========================================================
# CONNECT TO COLLEAGUE'S ENGINE
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
    "RISK ANALYSIS",
    "Turn fork-measured failure impacts into an economic decision.",
    "DECISION ENGINE",
)

badge("FORK-MEASURED SHOCKS + RISK MODEL", "real")


# =========================================================
# EXPLANATION
# =========================================================

with st.expander("What is this page doing?"):
    st.markdown(
        """
This page starts from the shock results measured by the Hero #1 engine.

It then asks:

1. **How much could we lose if we stay?**
2. **How bad are the extreme outcomes?**
3. **How much does it cost to exit?**
4. **How much yield do we give up by exiting?**
5. **Is STAY, REDUCE, or EXIT economically preferable?**

The fork provides the shock and exit measurements.

The decision layer then combines those measurements with assumptions such as:

- decision horizon,
- risk aversion,
- event frequency,
- Monte Carlo correlation.
"""
    )


# =========================================================
# USER DECISION INPUTS
# =========================================================

section_label("DECISION INPUTS")

c1, c2, c3 = st.columns(3)

with c1:
    scale = st.slider(
        "Position size × base Hero #1 book",
        min_value=0.25,
        max_value=4.0,
        value=1.0,
        step=0.25,
        help="1× corresponds to the base Hero #1 P1 + P2 position used by the engine.",
    )

with c2:
    risk_aversion = st.slider(
        "Risk aversion λ",
        min_value=0.0,
        max_value=1.0,
        value=0.5,
        step=0.05,
        help="Higher values give more weight to severe tail losses.",
    )

with c3:
    horizon = st.select_slider(
        "Decision horizon",
        options=[7, 14, 30, 60, 90],
        value=30,
        format_func=lambda x: f"{x} days",
    )


# =========================================================
# OPTIONAL OBSERVED INCIDENT
# =========================================================

section_label("CURRENT INCIDENT")

incident_options = {
    "No observed USDe incident": None,
    "USDe −2%": 0.02,
    "USDe −5%": 0.05,
    "USDe −10%": 0.10,
    "USDe −25%": 0.25,
}

incident_label = st.selectbox(
    "Condition the decision on an observed USDe depeg",
    list(incident_options.keys()),
)

incident = incident_options[incident_label]

if incident is None:
    st.caption(
        "No current incident selected: the engine uses its estimated scenario frequencies."
    )
else:
    st.warning(
        f"Observed-incident mode: conditioning the analysis on a {incident:.0%} USDe depeg."
    )


# =========================================================
# RUN HERO #1 DECISION ENGINE
# =========================================================

@st.cache_data(show_spinner="Running Hero #1 risk engine…")
def run_decision(scale, risk_aversion, horizon, incident):
    return hero1_decision.headline(
        scale=scale,
        lam=risk_aversion,
        horizon_days=float(horizon),
        incident=incident,
    )


try:
    result = run_decision(
        scale,
        risk_aversion,
        horizon,
        incident,
    )
except Exception as e:
    st.error("The Hero #1 decision engine failed to run.")
    st.exception(e)
    st.stop()


# =========================================================
# MAIN DECISION
# =========================================================

action = result.get("action", "N/A")
exit_fraction = result.get("exit_fraction", 0)

section_label("FAULT LINE DECISION")

if action == "EXIT":
    shock_banner("EXIT — the economics currently favor leaving the position.")

elif action == "REDUCE":
    shock_banner(
        f"REDUCE — recommended reduction: approximately {exit_fraction:.0%}."
    )

else:
    st.success(
        "STAY — the current modeled benefit of exiting does not justify the cost."
    )


# =========================================================
# POSITION SNAPSHOT
# =========================================================

size_usd = result.get("size_usd", 0)
p1_usd = result.get("p1_usd", 0)
p2_usd = result.get("p2_equity_usd", 0)
leverage = result.get("leverage", 0)

section_label("POSITION")

p1, p2, p3, p4 = st.columns(4)

with p1:
    metric_card(
        "Total Equity",
        f"${size_usd:,.0f}",
        f"{scale:.2f}× Hero #1 base position",
    )

with p2:
    metric_card(
        "P1 Outright PT",
        f"${p1_usd:,.0f}",
        "Unleveraged PT exposure",
    )

with p3:
    metric_card(
        "P2 Morpho Equity",
        f"${p2_usd:,.0f}",
        "Leveraged PT position",
    )

with p4:
    metric_card(
        "Gross Leverage",
        f"{leverage:.2f}×",
        "Morpho loop exposure",
    )


# =========================================================
# LOSS METRICS
# =========================================================

loss = result.get("loss_usd", {})

expected_loss = loss.get("E[L]", 0)
var95 = loss.get("VaR95", 0)
cvar95 = loss.get("CVaR95", 0)

section_label("RISK")

r1, r2, r3 = st.columns(3)

with r1:
    metric_card(
        "Expected Loss",
        f"${expected_loss:,.0f}",
        f"Expected loss over {horizon} days",
    )

with r2:
    metric_card(
        "VaR 95%",
        f"${var95:,.0f}",
        "95% modeled loss threshold",
    )

with r3:
    metric_card(
        "CVaR 95%",
        f"${cvar95:,.0f}",
        "Average loss in the worst 5%",
    )

badge("MONTE CARLO / DECISION MODEL", "model")


# =========================================================
# WHAT DOES EXITING NOW DO?
# =========================================================

section_label("ECONOMICS OF EXITING NOW")

components = result.get("components_full_exit_now", {})

loss_avoided = components.get("loss_avoided_usd", 0)
yield_forgone = components.get("yield_forgone_usd", 0)
exit_cost = components.get("exit_cost_usd", 0)
net_exit = components.get("net_usd", 0)

e1, e2, e3, e4 = st.columns(4)

with e1:
    metric_card(
        "Loss Avoided",
        f"${loss_avoided:,.0f}",
        "Risk removed by fully exiting",
    )

with e2:
    metric_card(
        "Yield Forgone",
        f"${yield_forgone:,.0f}",
        "Expected carry lost by leaving",
    )

with e3:
    metric_card(
        "Exit Cost",
        f"${exit_cost:,.0f}",
        "Measured / interpolated from fork exit curve",
    )

with e4:
    metric_card(
        "Net Value of Exit",
        f"${net_exit:+,.0f}",
        "Loss avoided − yield forgone − exit cost",
    )


# =========================================================
# CARRY / YIELD
# =========================================================

carry = result.get("carry", {})

section_label("WHY STAYING CAN STILL HAVE VALUE")

y1, y2, y3 = st.columns(3)

with y1:
    metric_card(
        "Net Carry APY",
        f"{carry.get('apy', 0):.2%}",
        "Estimated annualized return of the combined position",
    )

with y2:
    metric_card(
        "PT Implied APY",
        f"{carry.get('pt_implied_apy', 0):.2%}",
        "Yield embedded in the PT position",
    )

with y3:
    metric_card(
        "Morpho Borrow APR",
        f"{carry.get('borrow_apr', 0):.2%}",
        "Cost of borrowing in the leveraged loop",
    )

with st.expander("Why does yield matter for the decision?"):
    st.markdown(
        """
Exiting removes risk, but it also means giving up future yield.

So the decision is not simply:

**risk of staying vs exit cost**

It is closer to:

**loss avoided by exiting  
− cost of exiting  
− yield we give up**

If that value is strongly positive, exiting becomes more attractive.
"""
    )


# =========================================================
# MAIN RISK DRIVER
# =========================================================

driver = result.get("driver", {})

section_label("NUMBER 1 RISK DRIVER")

driver_label = driver.get("label", driver.get("scenario", "N/A"))
driver_name = driver.get("driver", "N/A")
driver_share = driver.get("share_of_risk_adjusted_loss")
time_to_impact = driver.get("time_to_impact_s")
confidence = driver.get("confidence", "N/A")

d1, d2, d3, d4 = st.columns(4)

with d1:
    metric_card(
        "Scenario",
        str(driver_label),
        "Largest contributor to risk",
    )

with d2:
    if driver_share is not None:
        share_text = f"{driver_share:.0%}"
    else:
        share_text = "N/A"

    metric_card(
        "Risk Share",
        share_text,
        "Share of risk-adjusted loss",
    )

with d3:
    if time_to_impact is not None:
        if time_to_impact >= 3600:
            impact_text = f"{time_to_impact / 3600:.1f} h"
        else:
            impact_text = f"{time_to_impact / 60:.0f} min"
    else:
        impact_text = "N/A"

    metric_card(
        "Time to Impact",
        impact_text,
        "How quickly the driver can matter",
    )

with d4:
    metric_card(
        "Confidence",
        str(confidence),
        "Evidence / model confidence",
    )

with st.expander("Risk-driver details"):
    st.write("Driver:", driver_name)

    notes = driver.get("notes")

    if notes:
        if isinstance(notes, list):
            for note in notes:
                st.markdown(f"- {note}")
        else:
            st.write(notes)


# =========================================================
# USDE LIQUIDATION THRESHOLD
# =========================================================

section_label("LIQUIDATION SIGNAL")

liq_depeg = result.get("liquidated_at_usde_depeg")
time_to_liq = result.get("time_to_liquidation_s")

l1, l2 = st.columns(2)

with l1:
    if liq_depeg is not None:
        metric_card(
            "Observed Liquidation Shock",
            f"USDe −{liq_depeg:.0%}",
            "First tested depeg that liquidated the loop on the fork",
        )
    else:
        metric_card(
            "Observed Liquidation Shock",
            "Not reached",
            "No tested USDe shock liquidated the position",
        )

with l2:
    if time_to_liq is not None:
        metric_card(
            "Oracle Delay",
            f"{time_to_liq / 3600:.0f} h",
            "Challenge / switch delay before impact",
        )


# =========================================================
# BREAKEVEN
# =========================================================

section_label("BREAKEVEN")

breakeven = result.get("breakeven", {})

p_estimate = breakeven.get("p_estimate")
p_breakeven = breakeven.get("p_breakeven")
rate_multiplier = breakeven.get("rate_multiplier")

b1, b2, b3 = st.columns(3)

with b1:
    metric_card(
        "Estimated Incident Probability",
        f"{p_estimate:.1%}" if p_estimate is not None else "N/A",
        f"Within the {horizon}-day horizon",
    )

with b2:
    metric_card(
        "Breakeven Probability",
        f"{p_breakeven:.1%}" if p_breakeven is not None else "N/A",
        "Where exiting becomes economically neutral",
    )

with b3:
    metric_card(
        "Frequency Multiplier",
        f"{rate_multiplier:.2f}×" if rate_multiplier is not None else "N/A",
        "How much incident frequency must change to reach breakeven",
    )

with st.expander("What is breakeven probability?"):
    st.markdown(
        """
It answers:

**How likely would a loss-making incident need to be before exiting becomes economically worthwhile?**

If your belief about risk is above that level, exiting becomes more attractive.

If it is below that level, staying can still be economically rational.
"""
    )


# =========================================================
# EXIT OVER TIME
# =========================================================

section_label("EXIT TIMING")

exit_curve = result.get("exit_cost_curve", {})

if exit_curve:

    exit_df = pd.DataFrame(
        {
            "Time": list(exit_curve.keys()),
            "Exit Cost ($)": list(exit_curve.values()),
        }
    )

    st.dataframe(
        exit_df.style.format(
            {
                "Exit Cost ($)": "${:,.0f}",
            }
        ),
        hide_index=True,
        use_container_width=True,
    )

    chart_df = exit_df.set_index("Time")

    st.line_chart(chart_df)


with st.expander("Important assumption behind the timed exit curve"):
    st.markdown(
        """
The underlying PT exit prices are based on **fork-executed exit curves**.

However, spreading the exit into several tranches over time assumes that liquidity can refill between those tranches.

That refill assumption is still a model assumption and should not be presented as a directly measured future fact.
"""
    )


# =========================================================
# ENGINE REASONS
# =========================================================

section_label("WHY DID THE ENGINE CHOOSE THIS?")

reasons = result.get("reason", [])

for reason in reasons:
    st.markdown(f"- {reason}")


# =========================================================
# TRANSPARENCY
# =========================================================

section_label("REAL VS MODELED")

real_col, model_col = st.columns(2)

with real_col:
    st.markdown("### ✅ Fork-measured / data-derived")

    st.markdown(
        """
- Hero #1 dependency structure
- USDe depeg shock outcomes
- oracle shock outcomes
- Pendle liquidity withdrawals
- liquidation behavior
- PT → sUSDe → USDC exit routes
- exit curve at several trade sizes
- protocol rates used by the engine
"""
    )

with model_col:
    st.markdown("### ⚠️ Decision assumptions")

    st.markdown(
        """
- decision horizon
- risk aversion λ
- Monte Carlo correlation
- future incident frequencies
- some severity distribution assumptions
- liquidity refill between future exit tranches
"""
    )


# =========================================================
# NEXT
# =========================================================

section_label("NEXT")

st.info(
    "The next step is to connect the Exit Race page to the fork-measured "
    "exit curves and the new decision engine instead of the old UI multipliers."
)

st.page_link(
    "pages/5_Exit_Race.py",
    label="Open Exit Race →",
    icon="🏃",
)