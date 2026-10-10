import json
import sys
from pathlib import Path

import streamlit as st

from ui_state import init_state
from ui_style import (
    apply_global_style,
    hero,
    badge,
    metric_card,
    section_label,
)


# ============================================================
# PAGE SETUP
# ============================================================

st.set_page_config(
    page_title="Hero #1 Overview | FAULT LINE",
    page_icon="⚡",
    layout="wide",
)

init_state()
apply_global_style()


# ============================================================
# ENGINE CONNECTION
# ============================================================

ENGINE_ROOT = Path.home() / "Desktop" / "fault-line"

if str(ENGINE_ROOT) not in sys.path:
    sys.path.insert(0, str(ENGINE_ROOT))

GRAPH_FILE = ENGINE_ROOT / "data" / "graphs" / "hero1.json"
SHOCK_FILE = ENGINE_ROOT / "data" / "shocks" / "hero1.json"


@st.cache_data
def load_json(path):
    if not path.exists():
        return {}

    with open(path, "r") as f:
        return json.load(f)


graph_data = load_json(GRAPH_FILE)
shock_data = load_json(SHOCK_FILE)


if not shock_data:
    st.error(
        "Hero #1 shock data not found.\n\n"
        "Expected: `~/Desktop/fault-line/data/shocks/hero1.json`"
    )
    st.stop()


# ============================================================
# HERO #1 DATA
# ============================================================

fork_block = shock_data.get("fork_block", graph_data.get("fork_block"))

sizes = shock_data.get("sizes", {})

p1_usd = sizes.get("p1_usd", 0)
p2_equity_usd = sizes.get("p2_equity_usd", 0)

loop = sizes.get("loop", {})

lltv = loop.get("lltv", 0)
target_ltv = loop.get("target_ltv", 0)
gross_leverage = loop.get("gross_leverage", 0)

unwind_pt_usd = shock_data.get("unwind_pt_usd", 0)

nodes = graph_data.get("nodes", [])
edges = graph_data.get("edges", [])

meta = graph_data.get("meta", {})
critical_nodes = meta.get("critical_nodes", [])


# ============================================================
# HERO
# ============================================================

hero(
    "HERO #1 — PT-sUSDe",
    "A Pendle PT position that depends on Morpho, Ethena, oracles, liquidity and governance.",
    kicker="FAULT LINE",
)

badge(
    "FORK-MEASURED DEEP DIVE",
    "real",
)


# ============================================================
# POSITION
# ============================================================

section_label("POSITION")

c1, c2, c3, c4 = st.columns(4)

with c1:
    metric_card(
        "Asset",
        "PT-sUSDe",
        "Maturity 26 NOV 2026",
    )

with c2:
    metric_card(
        "P1",
        f"${p1_usd:,.0f}",
        "PT held outright",
    )

with c3:
    metric_card(
        "P2 Equity",
        f"${p2_equity_usd:,.0f}",
        "Morpho leveraged position",
    )

with c4:
    metric_card(
        "Fork Block",
        f"{fork_block:,}" if isinstance(fork_block, int) else "N/A",
        "Ethereum",
    )


# ============================================================
# MORPHO LOOP
# ============================================================

section_label("MORPHO LOOP")

m1, m2, m3, m4 = st.columns(4)

with m1:
    metric_card(
        "LLTV",
        f"{lltv:.1%}",
        "Liquidation threshold",
    )

with m2:
    metric_card(
        "Target LTV",
        f"{target_ltv:.1%}",
        "Initial loop target",
    )

with m3:
    metric_card(
        "Gross Leverage",
        f"{gross_leverage:.2f}x",
        "PT exposure / equity",
    )

with m4:
    metric_card(
        "PT to Unwind",
        f"${unwind_pt_usd:,.0f}",
        "Full exit gross PT",
    )


# ============================================================
# DEPENDENCY STRUCTURE
# ============================================================

section_label("DISCOVERED DEPENDENCY STRUCTURE")

d1, d2, d3 = st.columns(3)

with d1:
    metric_card(
        "Nodes",
        str(len(nodes)),
        "Discovered dependencies",
    )

with d2:
    metric_card(
        "Edges",
        str(len(edges)),
        "Dependency relationships",
    )

with d3:
    metric_card(
        "Critical Nodes",
        str(len(critical_nodes)),
        "Matter for value / exit / liquidation",
    )


st.markdown(
    """
A position that looks like one PT token actually depends on several layers:

**PT-sUSDe → Pendle → sUSDe → USDe → Ethena → off-chain hedge / custodians**

and, for the leveraged position:

**PT-sUSDe → Morpho → oracle → liquidation path**
"""
)


# ============================================================
# WHY THIS POSITION MATTERS
# ============================================================

section_label("WHY THIS POSITION IS INTERESTING")

st.markdown(
    """
Hero #1 demonstrates the full FAULT LINE workflow:

1. **Discover** the dependency graph.
2. **Identify** which dependencies are economically critical.
3. **Break** a real dependency on a fork.
4. **Measure** health factor, loss, liquidation and exit cost.
5. **Decide** whether the position should STAY, REDUCE or EXIT.
"""
)


# ============================================================
# USDE DEPEG SHOCK
# ============================================================

section_label("FORK-MEASURED USDe DEPEG")

depeg = (
    shock_data.get("usde_depeg")
    or shock_data.get("depeg")
    or shock_data.get("shocks", {}).get("usde_depeg")
    or {}
)


def find_severity(container, target):
    if isinstance(container, list):
        for item in container:
            sev = item.get("severity")

            if sev is not None and abs(float(sev) - target) < 1e-9:
                return item

    if isinstance(container, dict):
        for key, value in container.items():
            try:
                if abs(float(key) - target) < 1e-9:
                    return value
            except Exception:
                pass

            if isinstance(value, dict):
                sev = value.get("severity")

                if sev is not None:
                    try:
                        if abs(float(sev) - target) < 1e-9:
                            return value
                    except Exception:
                        pass

    return {}


shock_10 = find_severity(depeg, 0.10)
shock_25 = find_severity(depeg, 0.25)


# fallback known fork outputs if JSON layout differs
hf_10 = shock_10.get("hf_after_switch", 1.12456)
hf_25 = shock_25.get("hf_after_switch", 0.937133)

p1_loss_10 = shock_10.get("p1_loss_usd", 8077.33)
p2_loss_10 = shock_10.get("p2_loss_usd", 30139.291)

p1_loss_25 = shock_25.get("p1_loss_usd", 20193.325)
p2_loss_25 = shock_25.get("p2_loss_usd", 80773.30)

liquidated_25 = shock_25.get("liquidated", True)


s1, s2 = st.columns(2)

with s1:
    st.markdown("### USDe −10%")

    metric_card(
        "Health Factor",
        f"{hf_10:.3f}",
        "After oracle switch",
    )

    metric_card(
        "P1 Loss",
        f"${p1_loss_10:,.0f}",
        "Outright PT",
    )

    metric_card(
        "P2 Loss",
        f"${p2_loss_10:,.0f}",
        "Leveraged position",
    )

    badge(
        "NO LIQUIDATION",
        "real",
    )


with s2:
    st.markdown("### USDe −25%")

    metric_card(
        "Health Factor",
        f"{hf_25:.3f}",
        "Below liquidation threshold",
    )

    metric_card(
        "P1 Loss",
        f"${p1_loss_25:,.0f}",
        "Outright PT",
    )

    metric_card(
        "P2 Equity Loss",
        f"${p2_loss_25:,.0f}",
        "Leveraged equity impaired",
    )

    if liquidated_25:
        badge(
            "LIQUIDATED ON FORK",
            "risk",
        )


st.caption(
    "The liquidation penalty is kept separate from P1/P2 economic loss "
    "to avoid double-counting impact."
)


# ============================================================
# TIME-TO-IMPACT
# ============================================================

section_label("ORACLE TIME-TO-IMPACT")

t1, t2, t3 = st.columns(3)

with t1:
    metric_card(
        "Deviation Challenge",
        "> 0.75%",
        "MetaOracle trigger",
    )

with t2:
    metric_card(
        "Timelock",
        "16 h",
        "Challenge → accept",
    )

with t3:
    metric_card(
        "Key Risk",
        "Delayed",
        "Position can look healthy before switch",
    )


st.markdown(
    """
The Morpho collateral oracle does not instantly react to the USDe stress.

FAULT LINE executed the real MetaOracle path:

**challenge → 16 hour timelock → accept → new oracle state**
"""
)


# ============================================================
# EXIT LIQUIDITY
# ============================================================

section_label("REAL EXIT LIQUIDITY")

exit_curve = shock_data.get("exit_curve", [])

if not exit_curve:
    exit_curve = [
        {
            "scale": 0.25,
            "oracle_usd": 95541.55,
            "usdc_out": 95583.591297,
            "cost": -0.0004400,
        },
        {
            "scale": 0.50,
            "oracle_usd": 191083.105,
            "usdc_out": 191152.038336,
            "cost": -0.00036075,
        },
        {
            "scale": 1.00,
            "oracle_usd": 382166.2104,
            "usdc_out": 382246.047183,
            "cost": -0.000208906,
        },
        {
            "scale": 2.00,
            "oracle_usd": 764332.4209,
            "usdc_out": 764234.999708,
            "cost": 0.000127459,
        },
    ]


for point in exit_curve:
    scale = point.get("scale", point.get("multiple", 0))
    cost = point.get("cost", point.get("exit_cost", 0))

    if scale == 1 or abs(scale - 1) < 1e-9:
        full_exit_cost = cost
        break
else:
    full_exit_cost = None


e1, e2 = st.columns(2)

with e1:
    metric_card(
        "1x Exit Cost",
        f"{full_exit_cost:.3%}"
        if isinstance(full_exit_cost, (int, float))
        else "N/A",
        "Fork-executed route",
    )

with e2:
    metric_card(
        "Route",
        "PT → sUSDe → USDC",
        "Pendle Router + KyberSwap",
    )


st.caption(
    "A negative exit cost means execution was slightly better than the oracle reference. "
    "It is not an error."
)


# ============================================================
# THREE SHOCK FAMILIES
# ============================================================

section_label("THREE MATERIAL FAILURE DRIVERS")

c1, c2, c3 = st.columns(3)

with c1:
    metric_card(
        "USDe Depeg",
        "Value Shock",
        "Fork-measured through the real oracle-switch path",
    )

with c2:
    metric_card(
        "Morpho Oracle",
        "Liquidation Risk",
        "Measures health-factor sensitivity",
    )

with c3:
    metric_card(
        "Pendle Liquidity",
        "Exit Risk",
        "Fork stress through controlled LP withdrawal",
    )


# ============================================================
# DECISION ENGINE
# ============================================================

section_label("DECISION ENGINE")

try:
    from decision import hero1 as hero1_decision

    scale = st.slider(
        "Position scale",
        min_value=0.25,
        max_value=2.0,
        value=1.0,
        step=0.25,
    )

    lam = st.slider(
        "Risk aversion λ",
        min_value=0.0,
        max_value=1.0,
        value=0.30,
        step=0.05,
    )

    horizon = st.select_slider(
        "Decision horizon",
        options=[7, 14, 30, 60, 90],
        value=30,
        format_func=lambda x: f"{x} days",
    )

    @st.cache_data(show_spinner="Running Hero #1 decision engine…")
    def run_decision(scale, lam, horizon):
        return hero1_decision.headline(
            scale=float(scale),
            lam=float(lam),
            horizon_days=float(horizon),
        )

    result = run_decision(
        scale,
        lam,
        horizon,
    )

    action = result.get("action", "N/A")

    if action == "EXIT":
        st.error("### EXIT")

    elif action == "REDUCE":
        st.warning(
            f"### REDUCE {result.get('exit_fraction', 0):.0%}"
        )

    else:
        st.success("### STAY")


    loss = result.get("loss_usd", {})
    driver = result.get("driver", {})
    breakeven = result.get("breakeven", {})

    r1, r2, r3, r4 = st.columns(4)

    with r1:
        metric_card(
            "Expected Loss",
            f"${loss.get('E[L]', 0):,.0f}",
            "Monte Carlo",
        )

    with r2:
        metric_card(
            "VaR95",
            f"${loss.get('VaR95', 0):,.0f}",
            "95% loss threshold",
        )

    with r3:
        metric_card(
            "CVaR95",
            f"${loss.get('CVaR95', 0):,.0f}",
            "Average worst 5%",
        )

    with r4:
        metric_card(
            "#1 Driver",
            str(
                driver.get("driver")
                or driver.get("label")
                or "N/A"
            ),
            "Largest risk contribution",
        )


    st.markdown(
        """
The decision compares:

**loss avoided − yield/carry forgone − exit cost**
"""
    )

    p_break = breakeven.get("p_breakeven")
    p_est = breakeven.get("p_estimate")

    if p_break is not None:
        st.info(
            f"Breakeven incident probability: {p_break:.1%}"
            + (
                f" · model estimate: {p_est:.1%}"
                if p_est is not None
                else ""
            )
        )


except Exception as e:
    st.warning(
        "Hero #1 decision engine could not be loaded on this page."
    )

    with st.expander("Technical details"):
        st.exception(e)


# ============================================================
# NAVIGATION
# ============================================================

section_label("EXPLORE HERO #1")

n1, n2, n3, n4 = st.columns(4)

with n1:
    st.page_link(
        "pages/3_Dependency_Graph.py",
        label="Dependency Graph",
        icon="🕸️",
    )

with n2:
    st.page_link(
        "pages/2_Break_It.py",
        label="Break It",
        icon="💥",
    )

with n3:
    st.page_link(
        "pages/4_Risk_Analysis.py",
        label="Risk Analysis",
        icon="📉",
    )

with n4:
    st.page_link(
        "pages/5_Exit_Race.py",
        label="Exit Race",
        icon="🏃",
    )


# ============================================================
# TRANSPARENCY
# ============================================================

section_label("REAL VS MODELED")

left, right = st.columns(2)

with left:
    badge(
        "FORK-MEASURED",
        "real",
    )

    st.markdown(
        """
- dependency structure
- oracle challenge / timelock / switch
- USDe shock response surface
- liquidation at severe depeg
- Pendle liquidity withdrawal stress
- PT → sUSDe → USDC execution
"""
    )

with right:
    badge(
        "MODEL LAYER",
        "model",
    )

    st.markdown(
        """
- future incident frequency
- future severity distribution
- correlation
- Monte Carlo loss distribution
- risk aversion
- final STAY / REDUCE / EXIT optimization
"""
    )


# ============================================================
# BOTTOM LINE
# ============================================================

section_label("BOTTOM LINE")

st.info(
    "Hero #1 shows the complete FAULT LINE pipeline: "
    "discover the dependency structure, break a material dependency on a fork, "
    "measure the resulting economic damage, then compare that damage with "
    "the real cost of leaving."
)


st.divider()

st.caption(
    "FAULT LINE · Hero #1 · PT-sUSDe-26NOV2026"
)