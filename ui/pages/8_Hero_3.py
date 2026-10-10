import json
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
    page_title="Hero #3 | FAULT LINE",
    page_icon="🌐",
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

SHOCK_FILE = ENGINE_ROOT / "data" / "shocks" / "hero3.json"
GRAPH_FILE = ENGINE_ROOT / "data" / "graphs" / "hero3.json"


@st.cache_data
def load_json(path):
    if not path.exists():
        return None

    with open(path, "r") as f:
        return json.load(f)


shock_data = load_json(SHOCK_FILE)
graph_data = load_json(GRAPH_FILE)


if shock_data is None:
    st.error(
        "Hero #3 data not found.\n\n"
        "Expected: `~/Desktop/fault-line/data/shocks/hero3.json`"
    )
    st.stop()


# =========================================================
# HERO
# =========================================================

hero(
    "HERO #3 — OFF-CHAIN VENUE RISK",
    "Trace an on-chain sUSDe position into the off-chain exchange infrastructure supporting Ethena's hedge.",
    "ON-CHAIN POSITION · OFF-CHAIN FAILURE",
)

badge("HYBRID ON-CHAIN / OFF-CHAIN DEPENDENCY", "model")


# =========================================================
# BASIC DATA
# =========================================================

size_usd = shock_data.get("size_usd", 0)

ethena = shock_data.get("ethena", {})
cex = shock_data.get("cex", {})
onchain = shock_data.get("onchain", {})
exit_data = shock_data.get("exit", {})

venue_share = ethena.get("venue_share", 0)
venue_usd = ethena.get("venue_usd", 0)
reserve_usd = ethena.get("reserve_fund_usd", 0)
reserve_buffer = ethena.get("reserve_buffer", 0)
apy = ethena.get("susde_apy_30d", 0)

fork_block = onchain.get("block", "N/A")
cooldown_s = onchain.get("cooldown_s", 0)
cooldown_h = cooldown_s / 3600 if cooldown_s else 0


# =========================================================
# POSITION SNAPSHOT
# =========================================================

section_label("POSITION")

c1, c2, c3, c4 = st.columns(4)

with c1:
    metric_card(
        "Position Size",
        f"${size_usd / 1e6:,.1f}M",
        "Hero #3 test position",
    )

with c2:
    metric_card(
        "sUSDe APY",
        f"{apy:.2%}",
        "30-day Ethena yield",
    )

with c3:
    metric_card(
        "Cooldown",
        f"{cooldown_h:.0f} h",
        "sUSDe unstake delay",
    )

with c4:
    metric_card(
        "Fork Block",
        f"{fork_block:,}" if isinstance(fork_block, int) else str(fork_block),
        "Pinned Ethereum state",
    )


# =========================================================
# CORE STORY
# =========================================================

section_label("WHERE DOES THE RISK GO?")

st.markdown(
    """
The user only sees **sUSDe** on Ethereum.

But economically, the position depends on more than that token.

Ethena backs USDe using collateral and a **delta hedge** implemented through
short perpetual positions on centralized exchanges.

So the dependency chain is shown below.
"""
)

st.code(
    """
sUSDe position
      |
      v
USDe
      |
      v
Ethena Labs
      |
      v
Delta hedge: short perpetuals
      |
      v
Binance
""",
    language=None,
)

st.warning(
    "This is the key Hero #3 insight: an on-chain DeFi position can depend on "
    "an off-chain venue that does not appear in the user's wallet."
)


# =========================================================
# BINANCE DEPENDENCY
# =========================================================

section_label("OFF-CHAIN VENUE EXPOSURE")

b1, b2, b3, b4 = st.columns(4)

with b1:
    metric_card(
        "Venue",
        "Binance",
        "Largest identified perp venue",
    )

with b2:
    metric_card(
        "Backing Share",
        f"{venue_share:.1%}",
        "Ethena backing associated with Binance",
    )

with b3:
    metric_card(
        "Venue Exposure",
        f"${venue_usd / 1e6:,.0f}M",
        "Current Ethena collateral data",
    )

with b4:
    metric_card(
        "Reserve Fund",
        f"${reserve_usd / 1e6:,.0f}M",
        f"{reserve_buffer:.2%} of backing",
    )


# =========================================================
# VENUE DISTRIBUTION
# =========================================================

section_label("ETHENA BACKING BY VENUE")

by_venue = ethena.get("by_venue", {})

if by_venue:
    venue_df = pd.DataFrame(
        {
            "Venue": list(by_venue.keys()),
            "USD": list(by_venue.values()),
        }
    ).sort_values("USD", ascending=False)

    st.dataframe(
        venue_df.style.format(
            {
                "USD": "${:,.0f}",
            }
        ),
        hide_index=True,
        use_container_width=True,
    )

    st.bar_chart(
        venue_df.set_index("Venue")
    )


# =========================================================
# RUN DECISION ENGINE
# =========================================================

section_label("DECISION")

lam = st.slider(
    "Risk aversion λ",
    min_value=0.0,
    max_value=1.0,
    value=0.5,
    step=0.05,
)

horizon = st.select_slider(
    "Decision horizon",
    options=[7, 14, 30, 60, 90],
    value=30,
    format_func=lambda x: f"{x} days",
)

halted = st.toggle(
    "Stress state: Binance withdrawals halted",
    value=False,
)


try:
    from decision import hero3 as hero3_decision

    @st.cache_data(show_spinner="Running Hero #3 decision engine…")
    def run_headline(lam, horizon, halted):
        return hero3_decision.headline(
            lam=float(lam),
            horizon_days=float(horizon),
            halted=halted,
        )

    result = run_headline(
        lam,
        horizon,
        halted,
    )

except Exception as e:
    st.error("Hero #3 decision engine failed.")
    st.exception(e)
    st.stop()


# =========================================================
# HEADLINE
# =========================================================

action = result.get("action", "N/A")

if action == "EXIT":
    shock_banner(
        "EXIT — the modeled venue risk makes leaving economically preferable."
    )

elif action == "REDUCE":
    shock_banner(
        f"REDUCE — recommended exit fraction "
        f"{result.get('exit_fraction', 0):.0%}."
    )

else:
    st.success(
        "STAY — under the current model inputs, staying remains economically preferred."
    )


# =========================================================
# RISK METRICS
# =========================================================

loss = result.get("loss_usd", {})

r1, r2, r3 = st.columns(3)

with r1:
    metric_card(
        "Expected Loss",
        f"${loss.get('E[L]', 0):,.0f}",
        f"Over {horizon} days",
    )

with r2:
    metric_card(
        "CVaR 95%",
        f"${loss.get('CVaR95', 0):,.0f}",
        "Average loss in worst 5%",
    )

with r3:
    metric_card(
        "Net Value Exit Now",
        f"${result.get('net_value_exit_now_usd', 0):+,.0f}",
        "Risk avoided − yield − exit cost",
    )

badge("VENUE SHOCKS ARE MODELLED", "model")


# =========================================================
# FAILURE MODE 1
# =========================================================

section_label("FAILURE MODE 1 — VENUE LOSS")

st.markdown(
    """
**Scenario:** Binance suffers an asset loss.

The model assumes that only the portion of Ethena backing associated with
Binance is exposed.

The Ethena reserve fund absorbs losses first.

Only losses beyond that buffer reach the position.
"""
)

haircut_break = result.get("haircut_breakeven")

if haircut_break is not None:
    metric_card(
        "Reserve-Fund Breakeven",
        f"{haircut_break:.1%}",
        "Approximate Binance haircut absorbed before position loss begins",
    )


# =========================================================
# FAILURE MODE 2
# =========================================================

section_label("FAILURE MODE 2 — VENUE HALT")

st.markdown(
    """
**Scenario:** Binance freezes withdrawals.

In this scenario, the model does **not automatically assume a direct value loss**.

Instead, the main effect is on exitability:

the position may have to rely on the stressed DEX route rather than waiting
for normal off-chain settlement conditions.
"""
)


# =========================================================
# CEX BASE RATE
# =========================================================

section_label("WHERE DOES THE FAILURE RATE COME FROM?")

annual_rate = cex.get("annual_rate")
venue_years = cex.get("venue_years", 0)
incidents = cex.get("incidents", [])

q1, q2, q3 = st.columns(3)

with q1:
    metric_card(
        "CEX Incident Rate",
        f"{annual_rate:.1%}/yr" if annual_rate is not None else "N/A",
        "Historical proxy",
    )

with q2:
    metric_card(
        "Observed Venue-Years",
        f"{venue_years:.1f}",
        "Large CEX sample",
    )

with q3:
    metric_card(
        "Incidents",
        f"{len(incidents)}",
        "DefiLlama hacks sample",
    )


if incidents:
    incident_df = pd.DataFrame(incidents)

    st.dataframe(
        incident_df.style.format(
            {
                "usd": "${:,.0f}",
                "share": "{:.1%}",
            }
        ),
        hide_index=True,
        use_container_width=True,
    )

st.caption(
    cex.get(
        "note",
        "Historical incidents are used as a proxy for venue-loss severity.",
    )
)


# =========================================================
# EXIT REALITY
# =========================================================

section_label("CAN WE EXIT?")

dex_now = exit_data.get("dex_now", {})
unstake = exit_data.get("unstake_then_sell", {})

x1, x2 = st.columns(2)

with x1:
    st.markdown("### Exit now")

    metric_card(
        "Fork-Executed Cost",
        f"{dex_now.get('cost', 0):.1%}",
        f"${dex_now.get('size_usd', 0) / 1e6:,.1f}M sUSDe → USDC",
    )

    st.caption(
        dex_now.get(
            "status",
            "Executed on fork",
        )
    )

with x2:
    st.markdown("### Wait for unstake")

    unstake_cost = unstake.get("cost")

    metric_card(
        "Quoted Cost",
        f"{unstake_cost:.1%}" if unstake_cost is not None else "N/A",
        "Quote only — not executed",
    )

    st.caption(
        unstake.get(
            "status",
            "Quote only",
        )
    )


# =========================================================
# LIVE CROSS-CHECK
# =========================================================

live_check = dex_now.get("live_quote_check", {})

if live_check:

    section_label("LIVE KYBER CROSS-CHECK")

    st.markdown(
        """
The large fork exit cost was checked again against a live Kyber quote.

This helps answer whether the bad execution was merely a fork artifact.
"""
    )

    costs = live_check.get("cost_by_size", {})

    check_rows = []

    for label, cost in costs.items():
        check_rows.append(
            {
                "Trade Size": label,
                "Live Quote Cost": cost,
            }
        )

    if check_rows:
        st.dataframe(
            pd.DataFrame(check_rows).style.format(
                {
                    "Live Quote Cost": "{:.2%}",
                }
            ),
            hide_index=True,
            use_container_width=True,
        )

    st.success(
        live_check.get(
            "verdict",
            "The live quote confirms the same depth problem.",
        )
    )


# =========================================================
# DEPTH WALL
# =========================================================

section_label("THE DEPTH WALL")

st.markdown(
    """
At around **$1.25M**, the live quote is close to par.

At **$5M**, execution becomes dramatically more expensive.

That means liquidity is not just a yes/no question.

There is a **size-dependent depth wall**:

- small exit → little market impact
- large exit → available liquidity gets exhausted
- exhausted liquidity → much larger execution loss
"""
)


# =========================================================
# REAL VS MODEL
# =========================================================

section_label("WHAT IS REAL VS MODELED")

real_col, model_col = st.columns(2)

with real_col:
    st.markdown("### ✅ Observed / measured")

    st.markdown(
        """
- sUSDe on-chain configuration
- sUSDe → USDe relationship
- cooldown period
- Ethena venue allocation data
- Binance venue share
- Ethena reserve fund
- $5M sUSDe → USDC fork execution
- live Kyber quote cross-check
"""
    )

with model_col:
    st.markdown("### ⚠️ Modeled")

    st.markdown(
        """
- Binance asset-loss shock
- Binance withdrawal-halt shock
- loss severity distribution
- future CEX incident probability
- Monte Carlo risk metrics
- STAY / REDUCE / EXIT decision under those scenarios
"""
    )


# =========================================================
# REASONS
# =========================================================

section_label("WHY DID THE ENGINE CHOOSE THIS?")

reasons = result.get("reason", [])

if reasons:
    for reason in reasons:
        st.markdown(f"- {reason}")
else:
    st.info("No explanation returned by the engine.")


# =========================================================
# BOTTOM LINE
# =========================================================

section_label("BOTTOM LINE")

st.warning(
    f"An apparently on-chain sUSDe position depends on an off-chain hedge stack. "
    f"Binance represents about {venue_share:.1%} of identified Ethena backing, "
    f"while a $5M immediate exit cost about {dex_now.get('cost', 0):.1%} "
    f"in the fork execution."
)