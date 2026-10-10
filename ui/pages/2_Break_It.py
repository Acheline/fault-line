import json
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


# ============================================================
# PAGE SETUP
# ============================================================

st.set_page_config(
    page_title="Break It | FAULT LINE",
    page_icon="💥",
    layout="wide",
)

init_state()
apply_global_style()


# ============================================================
# REAL HERO #1 SHOCK DATA
# ============================================================

SHOCK_FILE = (
    Path.home()
    / "Desktop"
    / "fault-line"
    / "data"
    / "shocks"
    / "hero1.json"
)


@st.cache_data
def load_real_shocks():
    if not SHOCK_FILE.exists():
        return None

    with open(SHOCK_FILE, "r") as f:
        return json.load(f)


data = load_real_shocks()


if data is None:
    st.error(
        "Hero #1 shock data was not found.\n\n"
        "Expected:\n"
        "`~/Desktop/fault-line/data/shocks/hero1.json`"
    )
    st.stop()


# ============================================================
# HERO
# ============================================================

hero(
    "BREAK IT",
    "Stress a discovered critical dependency and inspect what actually happened on the Ethereum fork.",
    "FORK-MEASURED STRESS TESTING",
)

badge(
    "REAL FORK-MEASURED SHOCK DATA",
    "real",
)


# ============================================================
# POSITION SNAPSHOT
# ============================================================

fork_block = data.get("fork_block", "N/A")

sizes = data.get("sizes", {})

p1_usd = sizes.get("p1_usd", 0)
p2_equity_usd = sizes.get("p2_equity_usd", 0)

loop = sizes.get("loop", {})

gross_leverage = loop.get("gross_leverage", 0)
target_ltv = loop.get("target_ltv", 0)


section_label("POSITION SNAPSHOT")

c1, c2, c3, c4 = st.columns(4)

with c1:
    metric_card(
        "Fork Block",
        f"{fork_block:,}"
        if isinstance(fork_block, int)
        else str(fork_block),
        "Ethereum state",
    )

with c2:
    metric_card(
        "P1 — Outright PT",
        f"${p1_usd:,.0f}",
        "Unleveraged exposure",
    )

with c3:
    metric_card(
        "P2 — Morpho Equity",
        f"${p2_equity_usd:,.0f}",
        "Leveraged exposure",
    )

with c4:
    metric_card(
        "Gross Leverage",
        f"{gross_leverage:.2f}×",
        f"Target LTV {target_ltv:.1%}",
    )


# ============================================================
# EXPLANATION
# ============================================================

with st.expander("What does Break It do?"):

    st.markdown(
        """
FAULT LINE has already discovered the dependency structure.

This page asks:

**What happens if one of the important dependencies fails?**

The three Hero #1 stress families are:

- **USDe depeg** → economic value underneath sUSDe deteriorates.
- **Morpho oracle stress** → collateral value seen by Morpho is reduced.
- **Pendle liquidity withdrawal** → exit liquidity disappears.

Where possible, these scenarios were executed directly against a pinned
Ethereum fork rather than estimated only from a formula.
"""
    )


# ============================================================
# SELECT FAILURE
# ============================================================

section_label("SELECT FAILURE")

shock_type = st.radio(
    "Critical dependency to stress",
    [
        "USDe depeg",
        "Morpho oracle mispricing",
        "Pendle liquidity withdrawal",
    ],
    horizontal=True,
)


# ============================================================
# USDE DEPEG
# ============================================================

if shock_type == "USDe depeg":

    st.markdown("### USDe depeg")

    st.caption(
        "Stress the economic asset underneath sUSDe and follow the real "
        "MetaOracle challenge → timelock → switch path."
    )

    rows = data.get("usde_depeg", [])

    if not rows:
        st.error("No USDe depeg shock results found.")
        st.stop()

    severities = [
        float(r["severity"])
        for r in rows
    ]

    severity = st.select_slider(
        "USDe price drop",
        options=severities,
        value=(
            0.10
            if 0.10 in severities
            else severities[0]
        ),
        format_func=lambda x: f"−{x:.0%}",
    )

    result = next(
        r
        for r in rows
        if abs(
            float(r["severity"]) - severity
        ) < 1e-9
    )

    st.session_state.selected_shock = "USDe depeg"
    st.session_state.shock_severity = severity
    st.session_state.shock_active = True


    # ========================================================
    # MECHANISM
    # ========================================================

    section_label("WHAT THE FORK TEST DOES")

    timelock_s = result.get(
        "switch",
        {},
    ).get(
        "timelock_s",
        0,
    )

    st.markdown(
        f"""
**1. USDe is shocked by −{severity:.0%}.**

The economic value underneath the PT position deteriorates.

**2. Morpho does not immediately see the full move.**

Its primary pricing path remains active initially.

**3. The MetaOracle challenge is triggered.**

The protocol detects sufficient deviation between the pricing paths.

**4. The real timelock is respected.**

Measured waiting period:

**{timelock_s / 3600:.0f} hours**

**5. The backup pricing path is accepted.**

FAULT LINE then measures the new Health Factor and checks whether the Morpho
position becomes liquidatable.
"""
    )


    # ========================================================
    # FORK RESULT
    # ========================================================

    frozen = result.get(
        "frozen_phase",
        {},
    )

    after = result.get(
        "after_switch",
        {},
    )

    section_label("FORK RESULT")

    if after.get("liquidated", False):

        shock_banner(
            f"At a {severity:.0%} USDe depeg, the position becomes "
            "liquidatable after the oracle switch."
        )

    else:

        st.success(
            f"At a {severity:.0%} USDe depeg, the position remains "
            "above the liquidation threshold."
        )


    a, b, c, d = st.columns(4)

    with a:
        metric_card(
            "HF Before Switch",
            f"{frozen.get('hf', 0):.3f}",
            "Primary oracle still active",
        )

    with b:
        metric_card(
            "HF After Switch",
            f"{after.get('hf', 0):.3f}",
            "Backup pricing active",
        )

    with c:
        metric_card(
            "Liquidated",
            (
                "YES"
                if after.get("liquidated", False)
                else "NO"
            ),
            "Fork result",
        )

    with d:

        time_to_impact = result.get(
            "time_to_liquidation_s",
            timelock_s,
        )

        metric_card(
            "Time to Impact",
            f"{time_to_impact / 3600:.0f} h",
            "Oracle challenge / timelock",
        )


    # ========================================================
    # ECONOMIC IMPACT
    # ========================================================

    section_label("ECONOMIC IMPACT")

    p1_loss = result.get(
        "p1_loss_usd",
        0,
    )

    p2_loss = result.get(
        "p2_loss_usd",
        0,
    )

    liquidation_penalty = result.get(
        "liquidation_penalty_usd",
        0,
    )

    loss_per_usd = result.get(
        "loss_per_usd",
        0,
    )

    # IMPORTANT:
    # Economic loss = P1 loss + P2 loss.
    # Liquidation penalty is shown separately and is NOT added again here.
    economic_loss = (
        p1_loss
        + p2_loss
    )


    l1, l2, l3, l4 = st.columns(4)

    with l1:
        metric_card(
            "P1 Loss",
            f"${p1_loss:,.0f}",
            "Outright PT exposure",
        )

    with l2:
        metric_card(
            "P2 Loss",
            f"${p2_loss:,.0f}",
            "Morpho leveraged equity",
        )

    with l3:
        metric_card(
            "Economic Loss",
            f"${economic_loss:,.0f}",
            "P1 + P2 only",
        )

    with l4:
        metric_card(
            "Loss / Capital",
            f"{loss_per_usd:.1%}",
            "Engine-reported loss ratio",
        )


    # ========================================================
    # LIQUIDATION — SEPARATE ACCOUNTING
    # ========================================================

    if after.get(
        "liquidated",
        False,
    ):

        section_label("LIQUIDATION DETAILS")

        q1, q2, q3 = st.columns(3)

        with q1:
            metric_card(
                "PT Seized",
                f"{after.get('seized_pt', 0):,.0f}",
                "Collateral seized",
            )

        with q2:
            metric_card(
                "USDC Repaid",
                f"${after.get('repaid_usdc', 0):,.0f}",
                "Debt repaid",
            )

        with q3:
            metric_card(
                "Liquidation Penalty",
                f"${liquidation_penalty:,.0f}",
                "Shown separately — not added twice",
            )

        st.warning(
            "The liquidation penalty is reported separately from P1 + P2 "
            "economic loss. FAULT LINE does not add it again to the headline "
            "loss because that could double-count the liquidation impact."
        )


    # ========================================================
    # DEPENDENCY PATH
    # ========================================================

    with st.expander(
        "Which dependency path is being stressed?"
    ):

        st.code(
            """
PT-sUSDe
    ↓
SY-sUSDe
    ↓
sUSDe
    ↓
USDe   ← SHOCK
    ↓
MetaOracle
    ↓
16h challenge / timelock
    ↓
Backup oracle
    ↓
Morpho collateral price
    ↓
Health Factor
    ↓
Possible liquidation
""",
            language=None,
        )


# ============================================================
# MORPHO ORACLE STRESS
# ============================================================

elif shock_type == "Morpho oracle mispricing":

    st.markdown("### Morpho oracle stress")

    st.caption(
        "Stress the collateral price seen by Morpho and measure the "
        "Health Factor response."
    )

    rows = data.get(
        "oracle_shock",
        [],
    )

    if not rows:
        st.error(
            "No Morpho oracle shock results found."
        )
        st.stop()

    severities = [
        float(r["severity"])
        for r in rows
    ]

    severity = st.select_slider(
        "Oracle price move",
        options=severities,
        value=(
            0.05
            if 0.05 in severities
            else severities[0]
        ),
        format_func=lambda x: f"−{x:.0%}",
    )

    result = next(
        r
        for r in rows
        if abs(
            float(r["severity"])
            - severity
        ) < 1e-9
    )

    st.session_state.selected_shock = (
        "Morpho oracle mispricing"
    )

    st.session_state.shock_severity = severity
    st.session_state.shock_active = True


    # ========================================================
    # MECHANISM
    # ========================================================

    section_label("WHAT THIS TEST MEASURES")

    st.markdown(
        f"""
Morpho uses an oracle to determine the collateral value.

In this stress test, the price seen by Morpho is reduced by:

**−{severity:.0%}**

FAULT LINE then measures the new **Health Factor**.

- **HF > 1** → position remains above the liquidation threshold
- **HF < 1** → position is liquidatable
"""
    )


    # ========================================================
    # RESULT
    # ========================================================

    section_label("FORK RESULT")

    if result.get(
        "liquidated",
        False,
    ):

        shock_banner(
            f"The {severity:.0%} oracle shock makes the position liquidatable."
        )

    else:

        st.success(
            f"The position survives the {severity:.0%} oracle stress "
            "without liquidation."
        )


    o1, o2, o3 = st.columns(3)

    with o1:
        metric_card(
            "Oracle Shock",
            f"−{severity:.0%}",
            "Collateral pricing stress",
        )

    with o2:
        metric_card(
            "Health Factor",
            f"{result.get('hf', 0):.3f}",
            "Measured response",
        )

    with o3:
        metric_card(
            "Liquidated",
            (
                "YES"
                if result.get("liquidated", False)
                else "NO"
            ),
            "Fork result",
        )


    if result.get(
        "liquidated",
        False,
    ):

        l1, l2, l3 = st.columns(3)

        with l1:
            metric_card(
                "PT Seized",
                f"{result.get('seized_pt', 0):,.0f}",
                "Collateral seized",
            )

        with l2:
            metric_card(
                "USDC Repaid",
                f"${result.get('repaid_usdc', 0):,.0f}",
                "Debt repaid",
            )

        with l3:
            metric_card(
                "Liquidation Penalty",
                f"${result.get('liquidation_penalty_usd', 0):,.0f}",
                "Separate liquidation cost",
            )


    with st.expander(
        "Dependency path"
    ):

        st.code(
            """
PT collateral
    ↓
Morpho market
    ↓
Morpho pricing oracle   ← STRESS
    ↓
Collateral valuation
    ↓
Health Factor
    ↓
Possible liquidation
""",
            language=None,
        )


# ============================================================
# PENDLE LIQUIDITY STRESS
# ============================================================

else:

    st.markdown(
        "### Pendle liquidity withdrawal"
    )

    st.caption(
        "Remove liquidity providers from the Pendle AMM on the fork, "
        "then re-execute the PT exit."
    )

    rows = data.get(
        "pendle_liquidity",
        [],
    )

    if not rows:
        st.error(
            "No Pendle liquidity stress results found."
        )
        st.stop()

    severities = [
        float(r["severity"])
        for r in rows
    ]

    severity = st.select_slider(
        "LP liquidity removed",
        options=severities,
        value=(
            0.50
            if 0.50 in severities
            else severities[0]
        ),
        format_func=lambda x: f"{x:.0%}",
    )

    result = next(
        r
        for r in rows
        if abs(
            float(r["severity"])
            - severity
        ) < 1e-9
    )

    st.session_state.selected_shock = (
        "Pendle liquidity withdrawal"
    )

    st.session_state.shock_severity = severity
    st.session_state.shock_active = True


    # ========================================================
    # MECHANISM
    # ========================================================

    section_label("WHAT THIS TEST MEASURES")

    st.markdown(
        f"""
Liquidity providers make it possible to trade PT efficiently.

In this controlled fork stress, approximately:

**{severity:.0%} of LP liquidity is removed**

FAULT LINE then executes the PT exit again.

This measures something different from token value:

**the asset can still have value while becoming harder and more expensive to sell.**
"""
    )


    # ========================================================
    # RESULT
    # ========================================================

    section_label("FORK RESULT")

    q1, q2, q3 = st.columns(3)

    with q1:
        metric_card(
            "LP Removed",
            f"{result.get('lp_burned_share', 0):.0%}",
            "Pendle liquidity withdrawn",
        )

    with q2:
        metric_card(
            "LPs Impersonated",
            f"{result.get('lps_impersonated', 0)}",
            "Controlled fork setup",
        )

    with q3:
        metric_card(
            "Extra Exit Cost",
            f"{result.get('extra_exit_cost', 0):.3%}",
            "Measured at 1× exit size",
        )


    badge(
        "REAL EXIT RE-EXECUTION ON FORK",
        "real",
    )

    st.caption(
        "This is a controlled stress: LP accounts are impersonated on the "
        "fork to withdraw liquidity. It is not a claim that those LPs actually "
        "withdrew on mainnet."
    )


    # ========================================================
    # CURVE
    # ========================================================

    section_label("POST-SHOCK EXIT CURVE")

    curve = result.get(
        "curve",
        [],
    )

    table_rows = []

    for row in curve:

        table_rows.append(
            {
                "Position Size": f"{row['x']:.2f}×",
                "PT Sold": row["pt"],
                "Oracle Value ($)": row["oracle_value_usd"],
                "USDC Received": row["usdc_out"],
                "Exit Cost": row["cost"],
                "Executed": row["executed"],
            }
        )


    if table_rows:

        df = pd.DataFrame(
            table_rows
        )

        st.dataframe(
            df.style.format(
                {
                    "PT Sold": "{:,.0f}",
                    "Oracle Value ($)": "${:,.0f}",
                    "USDC Received": "${:,.0f}",
                    "Exit Cost": "{:.3%}",
                }
            ),
            hide_index=True,
            use_container_width=True,
        )


        chart_df = pd.DataFrame(
            {
                "Position Size": [
                    row["x"]
                    for row in curve
                ],
                "Exit Cost (%)": [
                    row["cost"] * 100
                    for row in curve
                ],
            }
        ).set_index(
            "Position Size"
        )

        st.line_chart(
            chart_df
        )


    with st.expander(
        "Dependency path"
    ):

        st.code(
            """
PT-sUSDe
    ↓
Pendle Market   ← LIQUIDITY REMOVED
    ↓
Pendle Router
    ↓
sUSDe
    ↓
USDC
    ↓
Actual exit proceeds
""",
            language=None,
        )


# ============================================================
# REAL VS MODEL
# ============================================================

section_label("MEASURED EVIDENCE VS MODEL")

real_col, model_col = st.columns(2)


with real_col:

    badge(
        "FORK-MEASURED",
        "real",
    )

    st.markdown(
        """
- Health Factor response
- liquidation status
- PT seized / USDC repaid
- MetaOracle challenge and switch
- 16-hour timelock
- Pendle LP withdrawal stress
- PT exit re-execution
- exit curve at multiple sizes
"""
    )


with model_col:

    badge(
        "MODEL LAYER",
        "model",
    )

    st.markdown(
        """
- future incident frequency
- future severity distribution
- decision horizon
- risk aversion λ
- Monte Carlo correlation
- future liquidity refill assumptions
"""
    )


# ============================================================
# KEY INTERPRETATION
# ============================================================

section_label("WHAT THIS PROVES")

st.info(
    "FAULT LINE does not stop at saying a dependency exists. "
    "It connects the dependency to a measurable economic consequence: "
    "Health Factor deterioration, liquidation risk or worse exit liquidity."
)


# ============================================================
# NEXT
# ============================================================

section_label("NEXT")

st.markdown(
    """
The measured shock surfaces now feed the Hero #1 risk and decision engine.

The next step asks:

**Is the loss we avoid by exiting worth more than the carry and execution cost we give up?**
"""
)

st.page_link(
    "pages/4_Risk_Analysis.py",
    label="Open Risk Analysis →",
    icon="📊",
)


st.divider()

st.caption(
    "FAULT LINE · Hero #1 Fork Stress Testing"
)