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
)


# =========================================================
# PAGE SETUP
# =========================================================

st.set_page_config(
    page_title="Evidence | FAULT LINE",
    page_icon="🔎",
    layout="wide",
)

init_state()
apply_global_style()


# =========================================================
# DATA PATHS
# =========================================================

ENGINE_ROOT = Path.home() / "Desktop" / "fault-line"

GRAPH_FILE = ENGINE_ROOT / "data" / "graphs" / "hero1.json"
SHOCK_FILE = ENGINE_ROOT / "data" / "shocks" / "hero1.json"


@st.cache_data
def load_json(path):
    if not path.exists():
        return None

    with open(path, "r") as f:
        return json.load(f)


graph = load_json(GRAPH_FILE)
shocks = load_json(SHOCK_FILE)


# =========================================================
# HERO
# =========================================================

hero(
    "EVIDENCE",
    "Every risk claim should be traceable back to the source that produced it.",
    "PROVENANCE & TRANSPARENCY",
)

badge("AUDITABLE RISK ANALYSIS", "real")


# =========================================================
# WHY THIS PAGE EXISTS
# =========================================================

with st.expander("Why does FAULT LINE need an Evidence page?"):
    st.markdown(
        """
A risk engine should not just say:

**"This dependency is dangerous."**

It should also be able to answer:

- Where did we discover it?
- Was it observed on-chain?
- Was it found in an execution trace?
- Was it read from contract storage?
- Was it measured on the fork?
- Or is it still a model assumption?

This is what FAULT LINE calls **provenance**.

Provenance means:

**where a finding came from and how we know it.**
"""
    )


# =========================================================
# DATA STATUS
# =========================================================

section_label("EVIDENCE SOURCES")

c1, c2, c3 = st.columns(3)

with c1:
    metric_card(
        "Dependency Graph",
        "LOADED" if graph else "MISSING",
        "data/graphs/hero1.json",
    )

with c2:
    metric_card(
        "Shock Results",
        "LOADED" if shocks else "MISSING",
        "data/shocks/hero1.json",
    )

with c3:
    fork_block = shocks.get("fork_block") if shocks else None

    metric_card(
        "Fork Block",
        f"{fork_block:,}" if fork_block else "N/A",
        "Pinned Ethereum state",
    )


# =========================================================
# PROVENANCE TYPES
# =========================================================

section_label("HOW DEPENDENCIES ARE DISCOVERED")

p1, p2, p3, p4 = st.columns(4)

with p1:
    metric_card(
        "TRACE",
        "Execution",
        "Which contracts called which contracts",
    )

with p2:
    metric_card(
        "STORAGE",
        "Contract state",
        "Values stored inside smart contracts",
    )

with p3:
    metric_card(
        "ON-CHAIN READ",
        "Configuration",
        "Direct reads from live protocol contracts",
    )

with p4:
    metric_card(
        "DISCLOSURE",
        "Off-chain",
        "Custodian / venue / protocol disclosures",
    )


# =========================================================
# POSITION-SPECIFIC EVIDENCE
# =========================================================

section_label("HERO #1 POSITION")

st.markdown(
    """
The position being analysed is:

**PT-sUSDe-26NOV2026**

held in two forms:

- **P1:** outright PT exposure
- **P2:** PT used as collateral in a leveraged Morpho Blue position

FAULT LINE follows the operations that economically matter to this exact position.
"""
)


# =========================================================
# IMPORTANT PATHS
# =========================================================

section_label("CRITICAL ECONOMIC PATHS")

col1, col2, col3 = st.columns(3)

with col1:
    st.markdown("### VALUE PATH")

    st.code(
        """
PT-sUSDe
   ↓
Pendle pricing
   ↓
SY-sUSDe
   ↓
sUSDe
   ↓
USDe
""",
        language=None,
    )

with col2:
    st.markdown("### EXIT PATH")

    st.code(
        """
PT-sUSDe
   ↓
Pendle Market
   ↓
Pendle Router
   ↓
sUSDe
   ↓
KyberSwap
   ↓
USDC
""",
        language=None,
    )

with col3:
    st.markdown("### LIQUIDATION PATH")

    st.code(
        """
PT collateral
   ↓
Morpho Market
   ↓
Collateral Oracle
   ↓
Health Factor
   ↓
Liquidation
""",
        language=None,
    )


# =========================================================
# CRITICAL NODES
# =========================================================

section_label("CRITICAL DEPENDENCIES")

critical_nodes = []

if graph:
    critical_nodes = graph.get("critical_nodes", [])

if critical_nodes:

    rows = []

    for node in critical_nodes:
        if isinstance(node, dict):
            rows.append(
                {
                    "Dependency": node.get(
                        "label",
                        node.get("name", node.get("id", "Unknown")),
                    ),
                    "Value Path": "✓" if "value" in node.get("paths", []) else "",
                    "Exit Path": "✓" if "exit" in node.get("paths", []) else "",
                    "Liquidation Path": (
                        "✓" if "liquidation" in node.get("paths", []) else ""
                    ),
                }
            )
        else:
            rows.append(
                {
                    "Dependency": str(node),
                    "Value Path": "",
                    "Exit Path": "",
                    "Liquidation Path": "",
                }
            )

    st.dataframe(
        pd.DataFrame(rows),
        hide_index=True,
        use_container_width=True,
    )

else:
    st.info(
        "The graph does not expose critical_nodes in the expected format. "
        "The Dependency Graph page still contains the full discovered graph."
    )


# =========================================================
# FORK-MEASURED EVIDENCE
# =========================================================

section_label("WHAT WAS ACTUALLY MEASURED ON THE FORK")

st.markdown("### 1. USDe depeg")

st.markdown(
    """
FAULT LINE did not simply assume that a USDe depeg causes liquidation.

The shock engine:

1. shocks USDe,
2. triggers the oracle challenge,
3. waits through the protocol timelock,
4. switches the oracle,
5. recomputes Health Factor,
6. attempts liquidation when appropriate.
"""
)

if shocks:
    usde_rows = shocks.get("usde_depeg", [])

    if usde_rows:
        table = []

        for row in usde_rows:
            table.append(
                {
                    "USDe Shock": f"-{row.get('severity', 0):.0%}",
                    "HF Frozen": row.get("frozen_phase", {}).get("hf"),
                    "HF After Switch": row.get("after_switch", {}).get("hf"),
                    "Liquidated": row.get("after_switch", {}).get(
                        "liquidated", False
                    ),
                    "Time to Impact": (
                        f"{row.get('time_to_liquidation_s', 0) / 3600:.0f} h"
                    ),
                }
            )

        df = pd.DataFrame(table)

        st.dataframe(
            df.style.format(
                {
                    "HF Frozen": "{:.3f}",
                    "HF After Switch": "{:.3f}",
                }
            ),
            hide_index=True,
            use_container_width=True,
        )


# =========================================================
# ORACLE EVIDENCE
# =========================================================

st.markdown("### 2. Morpho oracle stress")

st.markdown(
    """
The Morpho collateral price is stressed directly and the resulting
Health Factor is measured.

This tells us how close the leveraged position is to liquidation if the
price used by the lending protocol moves against the position.
"""
)

if shocks:
    oracle_rows = shocks.get("oracle_shock", [])

    if oracle_rows:
        table = []

        for row in oracle_rows:
            table.append(
                {
                    "Oracle Shock": f"-{row.get('severity', 0):.0%}",
                    "Health Factor": row.get("hf"),
                    "Liquidated": row.get("liquidated", False),
                }
            )

        st.dataframe(
            pd.DataFrame(table).style.format(
                {
                    "Health Factor": "{:.3f}",
                }
            ),
            hide_index=True,
            use_container_width=True,
        )


# =========================================================
# LIQUIDITY EVIDENCE
# =========================================================

st.markdown("### 3. Pendle liquidity withdrawal")

st.markdown(
    """
FAULT LINE also tests an execution failure:

**What if liquidity disappears?**

Liquidity providers are removed on the fork and the exit is executed again.

This measures the change in actual exit cost rather than merely assuming
that lower liquidity is dangerous.
"""
)

if shocks:
    liquidity_rows = shocks.get("pendle_liquidity", [])

    if liquidity_rows:
        table = []

        for row in liquidity_rows:
            table.append(
                {
                    "Liquidity Removed": f"{row.get('severity', 0):.0%}",
                    "LPs Impersonated": row.get("lps_impersonated", 0),
                    "Extra Exit Cost": row.get("extra_exit_cost", 0),
                }
            )

        st.dataframe(
            pd.DataFrame(table).style.format(
                {
                    "Extra Exit Cost": "{:.3%}",
                }
            ),
            hide_index=True,
            use_container_width=True,
        )


# =========================================================
# EXIT EXECUTION EVIDENCE
# =========================================================

section_label("REAL EXIT EXECUTION")

if shocks:
    exit_curve = shocks.get("exit_curve", [])

    if exit_curve:
        rows = []

        for row in exit_curve:
            rows.append(
                {
                    "Size": f"{row.get('x', 0):.2f}×",
                    "Oracle Value ($)": row.get("oracle_value_usd", 0),
                    "USDC Received": row.get("usdc_out", 0),
                    "Exit Cost": row.get("cost", 0),
                    "Executed": row.get("executed", False),
                }
            )

        df = pd.DataFrame(rows)

        st.dataframe(
            df.style.format(
                {
                    "Oracle Value ($)": "${:,.2f}",
                    "USDC Received": "${:,.2f}",
                    "Exit Cost": "{:.4%}",
                }
            ),
            hide_index=True,
            use_container_width=True,
        )

badge("PT → sUSDe → USDC EXECUTED ON FORK", "real")


# =========================================================
# ORACLE BLIND SPOT
# =========================================================

section_label("IMPORTANT FINDING: ORACLE BLIND SPOT")

st.warning(
    """
The lending protocol's collateral pricing path does not necessarily observe
every market dependency that affects the economic value or exitability of PT-sUSDe.

That means:

**market risk can develop before the lending oracle fully reflects it.**

This is why FAULT LINE follows the full dependency structure instead of
looking only at the final Morpho Health Factor.
"""
)


# =========================================================
# REAL VS MODEL
# =========================================================

section_label("EVIDENCE CLASSIFICATION")

real_col, model_col = st.columns(2)

with real_col:
    st.markdown("### ✅ Observed / measured")

    st.markdown(
        """
- contract relationships discovered from execution
- protocol configuration
- fork block state
- USDe depeg shock response
- MetaOracle challenge / switch
- Health Factor after shock
- liquidation execution
- PT seized
- debt repaid
- Pendle liquidity withdrawal
- PT exit executions
- USDC actually received
- exit-cost curve
"""
    )

with model_col:
    st.markdown("### ⚠️ Modeled / assumed")

    st.markdown(
        """
- probability of future incidents
- Monte Carlo draws
- correlation between risk events
- risk-aversion parameter λ
- decision horizon
- future liquidity refill between exit tranches
- interpolation between executed exit sizes
- extrapolation beyond measured sizes
"""
    )


# =========================================================
# WHY THIS MATTERS
# =========================================================

section_label("WHY THIS MATTERS")

st.markdown(
    """
FAULT LINE tries to keep three things separate:

**1. Discovery**

What does this position depend on?

**2. Measurement**

What actually happens when one dependency fails?

**3. Decision model**

Given those measurements, should the user stay, reduce, or exit?

That separation makes the final recommendation easier to audit and defend.
"""
)


# =========================================================
# FINAL TRACE
# =========================================================

section_label("AUDIT TRAIL")

st.code(
    """
POSITION
   ↓
REAL PROTOCOL OPERATIONS
   ↓
TRACE / STORAGE / ON-CHAIN READ
   ↓
DEPENDENCY GRAPH
   ↓
CRITICAL PATHS
   ↓
FORK-MEASURED SHOCKS
   ↓
MEASURED EXIT COST
   ↓
MONTE CARLO + DECISION MODEL
   ↓
STAY / REDUCE / EXIT
""",
    language=None,
)

st.success(
    "The recommendation is not a black box: FAULT LINE keeps the dependency, "
    "measurement and model layers explicitly separated."
)