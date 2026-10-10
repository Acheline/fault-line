import json
from pathlib import Path

import streamlit as st

from ui_style import (
    apply_global_style,
    hero,
    badge,
    metric_card,
    section_label,
)


# ============================================================
# PAGE
# ============================================================

st.set_page_config(
    page_title="FAULT LINE",
    page_icon="⚡",
    layout="wide",
)

apply_global_style()


# ============================================================
# ENGINE DATA
# ============================================================

ENGINE_ROOT = Path.home() / "Desktop" / "fault-line"

HERO1_GRAPH = ENGINE_ROOT / "data" / "graphs" / "hero1.json"
HERO1_SHOCKS = ENGINE_ROOT / "data" / "shocks" / "hero1.json"

BOOK_XRAY = ENGINE_ROOT / "data" / "book_xray.json"

HERO3_GRAPH = ENGINE_ROOT / "data" / "graphs" / "hero3.json"
HERO3_SHOCKS = ENGINE_ROOT / "data" / "shocks" / "hero3.json"


@st.cache_data
def load_json(path):
    if not path.exists():
        return {}

    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return {}


hero1_graph = load_json(HERO1_GRAPH)
hero1_shocks = load_json(HERO1_SHOCKS)

book_xray = load_json(BOOK_XRAY)

hero3_graph = load_json(HERO3_GRAPH)
hero3_shocks = load_json(HERO3_SHOCKS)


# ============================================================
# SAFE VALUES
# ============================================================

hero1_nodes = hero1_graph.get("nodes", [])
hero1_edges = hero1_graph.get("edges", [])

hero1_meta = hero1_graph.get("meta", {})

critical_nodes = hero1_meta.get("critical_nodes", [])

fork_block = (
    hero1_shocks.get("fork_block")
    or hero1_graph.get("fork_block")
    or 26162857
)

n_vaults = book_xray.get("n_vaults", 0)
book_usd = book_xray.get("book_usd", 0)
effective_bets = book_xray.get("effective_bets", 0)

groups = book_xray.get("groups", [])

huma = next(
    (
        g
        for g in groups
        if str(g.get("issuer", "")).lower() == "huma"
    ),
    {},
)

huma_share = huma.get("share", 0)

hero3_ethena = hero3_shocks.get("ethena", {})
hero3_exit = hero3_shocks.get("exit", {}).get("dex_now", {})

venue_share = hero3_ethena.get("venue_share", 0)
hero3_exit_cost = hero3_exit.get("cost")


# ============================================================
# HERO
# ============================================================

hero(
    "FAULT LINE",
    "Trace the dependency. Break it. Measure the loss. Decide.",
)

badge(
    "DEFI RISK DEPENDENCY ENGINE",
    "accent",
)

st.markdown(
    """
FAULT LINE turns a DeFi position into a map of the systems it actually depends on,
then tests what happens when one of those dependencies fails.

The output is not just a risk score.

It is a decision:

**STAY · REDUCE · EXIT**
"""
)


# ============================================================
# PLATFORM SNAPSHOT
# ============================================================

section_label("PLATFORM SNAPSHOT")

c1, c2, c3, c4 = st.columns(4)

with c1:
    metric_card(
        "Hero #1",
        "PT-sUSDe",
        f"Ethereum fork block {fork_block:,}"
        if isinstance(fork_block, int)
        else "Ethereum fork",
    )

with c2:
    metric_card(
        "Portfolio X-ray",
        f"{n_vaults} vaults",
        (
            f"${book_usd / 1e6:,.1f}M book"
            if book_usd
            else "Belem / RockawayX"
        ),
    )

with c3:
    metric_card(
        "Effective Bets",
        f"{effective_bets:.1f}"
        if effective_bets
        else "N/A",
        (
            f"≥ {huma_share:.1%} Huma"
            if huma_share
            else "Dependency-adjusted"
        ),
    )

with c4:
    metric_card(
        "Hero #3",
        "Off-chain Risk",
        (
            f"Binance {venue_share:.1%} of backing"
            if venue_share
            else "Ethena → CEX dependency"
        ),
    )


# ============================================================
# PRIMARY ENTRY POINT
# ============================================================

section_label("START HERE")

left, right = st.columns([2, 1])

with left:

    st.markdown(
        """
### 🏦 Vault View

Start with the portfolio manager's actual question:

**Should I stay, reduce, or exit?**

The Vault View combines:

- vault allocation
- borrower solvency
- withdrawal liquidity
- depositor queue position
- shock losses
- exit cost
- carry forgone
- risk-adjusted decision
"""
    )

    st.page_link(
        "pages/0_Vault_View.py",
        label="Open Vault View →",
        icon="🏦",
    )

with right:

    badge(
        "MAIN JUDGE-FACING VIEW",
        "real",
    )

    st.markdown(
        """
**Why first?**

It gives the answer before forcing the user to inspect every technical detail.

Then FAULT LINE lets the user drill down into the evidence.
"""
    )


# ============================================================
# THREE CORE DEMOS
# ============================================================

section_label("THREE WAYS FAULT LINE FINDS HIDDEN RISK")

d1, d2, d3 = st.columns(3)


with d1:

    st.markdown("### ① Hero #1")

    metric_card(
        "On-chain dependency",
        "PT-sUSDe",
        "Pendle · Morpho · Ethena · oracle · liquidity",
    )

    st.markdown(
        """
Discover a deep dependency chain, break real components on an Ethereum fork,
measure the loss and compare it with exit economics.
"""
    )

    st.page_link(
        "pages/2_Break_It.py",
        label="Break Hero #1 →",
        icon="💥",
    )


with d2:

    st.markdown("### ② Book X-ray")

    metric_card(
        "Portfolio dependency",
        f"{n_vaults} vaults",
        (
            f"≈ {effective_bets:.1f} effective bets"
            if effective_bets
            else "Shared risk discovery"
        ),
    )

    st.markdown(
        """
Find exposures that look diversified by vault name but ultimately depend
on the same issuer, collateral system or exit liquidity.
"""
    )

    st.page_link(
        "pages/7_Book_Xray.py",
        label="Open Book X-ray →",
        icon="🩻",
    )


with d3:

    st.markdown("### ③ Hero #3")

    metric_card(
        "Off-chain dependency",
        "sUSDe → CEX",
        (
            f"$5M exit cost {hero3_exit_cost:.1%}"
            if isinstance(hero3_exit_cost, (int, float))
            else "Ethena hedge venue risk"
        ),
    )

    st.markdown(
        """
Trace an on-chain token into the centralized exchanges supporting its
economic hedge and expose the liquidity depth wall.
"""
    )

    st.page_link(
        "pages/8_Hero_3.py",
        label="Open Hero #3 →",
        icon="🌐",
    )


# ============================================================
# HERO #1 DEEP DIVE
# ============================================================

section_label("HERO #1 — DEEP DIVE")

st.markdown(
    """
The PT-sUSDe position is the full technical demonstration of the FAULT LINE pipeline.
"""
)

h1, h2, h3, h4 = st.columns(4)

with h1:

    metric_card(
        "1 · Discover",
        "Dependency Graph",
        (
            f"{len(hero1_nodes)} nodes · {len(hero1_edges)} edges"
            if hero1_nodes
            else "Trace protocol dependencies"
        ),
    )

    st.page_link(
        "pages/3_Dependency_Graph.py",
        label="Dependency Graph",
        icon="🕸️",
    )


with h2:

    metric_card(
        "2 · Break",
        "Stress",
        "USDe · oracle · Pendle liquidity",
    )

    st.page_link(
        "pages/2_Break_It.py",
        label="Break It",
        icon="💥",
    )


with h3:

    metric_card(
        "3 · Measure",
        "Risk",
        "Expected loss · VaR · CVaR",
    )

    st.page_link(
        "pages/4_Risk_Analysis.py",
        label="Risk Analysis",
        icon="📉",
    )


with h4:

    metric_card(
        "4 · Decide",
        "Exit Race",
        "Loss avoided − carry − exit cost",
    )

    st.page_link(
        "pages/5_Exit_Race.py",
        label="Exit Race",
        icon="🏃",
    )


# ============================================================
# PRODUCT WORKFLOW
# ============================================================

section_label("HOW FAULT LINE WORKS")

w1, w2, w3, w4 = st.columns(4)

with w1:

    metric_card(
        "01",
        "DISCOVER",
        "Follow real protocol operations and map dependencies.",
    )

with w2:

    metric_card(
        "02",
        "IDENTIFY",
        "Find dependencies that matter for value, exit or liquidation.",
    )

with w3:

    metric_card(
        "03",
        "BREAK",
        "Execute measurable failures on a fork where possible.",
    )

with w4:

    metric_card(
        "04",
        "DECIDE",
        "Compare risk avoided against exit cost and carry forgone.",
    )


# ============================================================
# EVIDENCE MODEL
# ============================================================

section_label("MEASURED EVIDENCE VS MODEL")

real_col, model_col = st.columns(2)

with real_col:

    badge(
        "MEASURED / OBSERVED",
        "real",
    )

    st.markdown(
        """
- on-chain reads
- storage inspection
- transaction traces
- Ethereum fork execution
- real liquidation paths
- real exit execution
- liquidity withdrawal stress
- protocol configuration
- live API cross-checks
- historical base-rate calculations
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
- future severity distributions
- Monte Carlo simulations
- driver correlations
- risk aversion λ
- decision horizon
- fallback priors
- STAY / REDUCE / EXIT optimization
"""
    )


# ============================================================
# EVIDENCE / ASSUMPTIONS LINKS
# ============================================================

section_label("AUDIT THE ANSWER")

a1, a2 = st.columns(2)

with a1:

    st.markdown(
        """
### 🔎 Evidence

Inspect where dependency findings came from:

**trace · storage · on-chain read · disclosure**
"""
    )

    st.page_link(
        "pages/6_Evidence.py",
        label="Open Evidence →",
        icon="🔎",
    )

with a2:

    st.markdown(
        """
### 🎚️ Assumptions

Inspect the values that are modeled rather than measured and identify
fallback priors explicitly.
"""
    )

    st.page_link(
        "pages/9_Assumptions.py",
        label="Open Assumptions →",
        icon="🎚️",
    )


# ============================================================
# DEMO ROUTE
# ============================================================

section_label("3-MINUTE DEMO ROUTE")

st.markdown(
    """
**1. Vault View** → show the final decision and the withdrawal problem.

**2. Hero #1 / Dependency Graph** → show that a single PT position actually
depends on Pendle, Morpho, Ethena, oracles, liquidity and governance.

**3. Break It** → select a USDe depeg and show the fork-measured health factor,
loss and liquidation response.

**4. Exit Race** → show that knowing the loss is not enough; leaving also costs money.

**5. Book X-ray** → show that 25 vaults are not 25 independent bets.

**6. Hero #3** → show that on-chain risk can terminate in an off-chain CEX.
"""
)


# ============================================================
# THESIS
# ============================================================

section_label("CORE THESIS")

metric_card(
    "FAULT LINE",
    "Read the system, don't guess it.",
    "Discover the dependency structure first. "
    "Then break the material dependency, measure the economic damage, "
    "and decide whether staying is still rational.",
)


st.divider()

st.caption(
    "FAULT LINE · DeFi Risk Dependency Engine · EPFL Hackathon 2026"
)