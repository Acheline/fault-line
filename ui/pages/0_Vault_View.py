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
    page_title="Vault View | FAULT LINE",
    page_icon="🏦",
    layout="wide",
)

init_state()
apply_global_style()


# =========================================================
# CONNECT TO COLLEAGUE ENGINE
# =========================================================

ENGINE_ROOT = Path.home() / "Desktop" / "fault-line"

if str(ENGINE_ROOT) not in sys.path:
    sys.path.insert(0, str(ENGINE_ROOT))

GRAPH_FILE = ENGINE_ROOT / "data" / "graphs" / "hero2.json"
SHOCK_FILE = ENGINE_ROOT / "data" / "shocks" / "hero2.json"


@st.cache_data
def load_json(path):
    if not path.exists():
        return None

    with open(path, "r") as f:
        return json.load(f)


graph_data = load_json(GRAPH_FILE)
shock_data = load_json(SHOCK_FILE)


if graph_data is None:
    st.error(
        "Hero #2 data not found.\n\n"
        "Expected: `~/Desktop/fault-line/data/graphs/hero2.json`"
    )
    st.stop()


m = graph_data.get("meta", {})
q1 = m.get("q1", {})
q3 = m.get("q3", {})
roles = q1.get("roles", {})
withdrawable = q3.get("withdrawable_now", {})


# =========================================================
# HERO
# =========================================================

hero(
    "VAULT VIEW",
    "Belem YIELD USDC — understand where the money goes, whether borrowers can repay, and whether depositors can exit.",
    "BELEM / ROCKAWAYX VAULT",
)

badge("FORK-DERIVED VAULT ANALYSIS", "real")


# =========================================================
# VAULT IDENTITY
# =========================================================

name = roles.get("name", "Belem Vault")
symbol = roles.get("symbol", "")
fork_block = m.get("fork_block", "N/A")

total_assets = roles.get("total_assets_usd", 0)

instant = (
    withdrawable.get("idle_usd", 0)
    + withdrawable.get("instant_from_liquidity_market_usd", 0)
)

reachable = withdrawable.get("total_reachable_usd", 0)

st.caption(
    f"{name} ({symbol}) · Ethereum fork block {fork_block}"
)


# =========================================================
# USER INPUTS
# =========================================================

section_label("YOUR POSITION")

c1, c2, c3, c4 = st.columns(4)

default_size = int(min(5_000_000, max(100_000, total_assets * 0.15)))

with c1:
    size = st.number_input(
        "Deposit size ($)",
        min_value=100_000,
        max_value=10_000_000,
        value=default_size,
        step=50_000,
    )

with c2:
    rank = st.number_input(
        "Exit queue rank",
        min_value=1,
        max_value=11,
        value=1,
        step=1,
        help="1 = you exit first. Rank 6 means five larger depositors leave before you.",
    )

with c3:
    lam = st.slider(
        "Risk aversion λ",
        min_value=0.0,
        max_value=1.0,
        value=0.5,
        step=0.05,
    )

with c4:
    horizon = st.select_slider(
        "Decision horizon",
        options=[7, 14, 30, 60, 90],
        value=30,
        format_func=lambda x: f"{x} days",
    )


rho = st.slider(
    "Driver correlation ρ",
    min_value=0.0,
    max_value=0.8,
    value=0.3,
    step=0.1,
    help="Model assumption: correlation between risk drivers.",
)


# =========================================================
# INCIDENT / GOVERNANCE
# =========================================================

section_label("SITUATION")

s1, s2 = st.columns(2)

with s1:
    situation = st.radio(
        "trUSD situation",
        [
            "Calm — no observed incident",
            "Observed trUSD depeg",
        ],
    )

    incident = None

    if situation == "Observed trUSD depeg":
        incident = st.slider(
            "Observed trUSD depeg depth",
            min_value=0.01,
            max_value=0.50,
            value=0.05,
            step=0.01,
            format_func=lambda x: f"−{x:.0%}",
        )

with s2:
    governance_shock = st.toggle(
        "Governance shock: curator raises exit penalty to 2%",
        value=False,
    )


# =========================================================
# RUN DECISION ENGINE
# =========================================================

headline = None

if shock_data is not None:
    try:
        from decision import hero2 as hero2_decision

        @st.cache_data(show_spinner="Running vault risk engine…")
        def run_headline(
            size,
            rank,
            lam,
            horizon,
            rho,
            governance,
            incident,
        ):
            return hero2_decision.headline(
                size_usd=float(size),
                rank=int(rank),
                lam=float(lam),
                horizon_days=float(horizon),
                rho=float(rho),
                governance=governance,
                incident=incident,
            )

        headline = run_headline(
            size,
            rank,
            lam,
            horizon,
            rho,
            governance_shock,
            incident,
        )

    except Exception as e:
        st.error("Hero #2 decision engine could not run.")
        st.exception(e)


# =========================================================
# MAIN ANSWER
# =========================================================

if headline:

    section_label("FAULT LINE ANSWER")

    action = headline.get("action", "N/A")
    exit_fraction = headline.get("exit_fraction", 0)

    if action in ("EXIT", "QUEUE EXIT NOW"):
        shock_banner(
            f"{action} — removing the risk is currently economically preferred."
        )

    elif action == "REDUCE":
        shock_banner(
            f"REDUCE — recommended reduction approximately {exit_fraction:.0%}."
        )

    else:
        st.success(
            "STAY — under the current inputs, staying is economically preferred."
        )

    net_usd = headline.get("net_value_exit_now_usd", 0)
    bps_book = headline.get("net_value_exit_now_bps_book", 0)
    bps_aum = headline.get("net_value_exit_now_bps_aum", 0)

    h1, h2, h3, h4 = st.columns(4)

    with h1:
        metric_card(
            "Decision",
            action,
            "STAY / REDUCE / EXIT",
        )

    with h2:
        metric_card(
            "Net Value Exit Now",
            f"${net_usd:+,.0f}",
            "Economic benefit of leaving now",
        )

    with h3:
        metric_card(
            "Mandate Impact",
            f"{bps_book:+.1f} bps",
            "Against the $50M mandate",
        )

    with h4:
        metric_card(
            "AUM Impact",
            f"{bps_aum:+.2f} bps",
            "Against Belem AUM",
        )


    # =====================================================
    # LOSS / BREAKEVEN / DRIVER
    # =====================================================

    section_label("WHY?")

    loss = headline.get("loss_usd", {})
    breakeven = headline.get("breakeven", {})
    driver = headline.get("driver", {})

    expected_loss = loss.get("E[L]", 0)
    cvar = loss.get("CVaR95", 0)

    p_break = breakeven.get("p_breakeven")
    p_est = breakeven.get("p_estimate")

    time_impact = driver.get("time_to_impact_s")

    d1, d2, d3, d4 = st.columns(4)

    with d1:
        metric_card(
            "Expected Loss",
            f"${expected_loss:,.0f}",
            f"CVaR95 ${cvar:,.0f}",
        )

    with d2:
        metric_card(
            "Breakeven Risk",
            f"{p_break:.1%}" if p_break is not None else "N/A",
            (
                f"Our estimate {p_est:.1%}"
                if p_est is not None
                else "No estimate"
            ),
        )

    with d3:
        metric_card(
            "#1 Driver",
            str(driver.get("driver") or driver.get("label") or "N/A"),
            (
                f"{driver.get('share_of_risk_adjusted_loss', 0):.0%} "
                "of risk-adjusted loss"
            ),
        )

    with d4:
        if time_impact is None:
            time_text = "N/A"
        elif time_impact == 0:
            time_text = "Immediate"
        elif time_impact < 3600:
            time_text = f"{time_impact / 60:.0f} min"
        else:
            time_text = f"{time_impact / 3600:.1f} h"

        metric_card(
            "Time to Impact",
            time_text,
            f"Confidence: {driver.get('confidence', 'N/A')}",
        )


    # =====================================================
    # EXIT ECONOMICS
    # =====================================================

    section_label("EXIT ECONOMICS")

    comp = headline.get("components_full_exit_now", {})

    e1, e2, e3, e4 = st.columns(4)

    with e1:
        metric_card(
            "Loss Avoided",
            f"${comp.get('loss_avoided_usd', 0):,.0f}",
            "Risk removed by exiting",
        )

    with e2:
        metric_card(
            "Yield Forgone",
            f"${comp.get('yield_forgone_usd', 0):,.0f}",
            "Carry sacrificed",
        )

    with e3:
        metric_card(
            "Exit Cost",
            f"${comp.get('exit_cost_usd', 0):,.0f}",
            "Withdrawal / liquidity cost",
        )

    with e4:
        metric_card(
            "Net",
            f"${comp.get('net_usd', 0):+,.0f}",
            "Loss avoided − yield − exit cost",
        )


    # =====================================================
    # QUEUE WARNING
    # =====================================================

    if headline.get("queue"):
        queue = headline["queue"]

        st.warning(
            f"QUEUE EXIT NOW — depositors ahead of you represent "
            f"${headline.get('ahead_usd', 0):,.0f} of claims. "
            f"Estimated lock time: ~{queue.get('locked_hours', 0):.0f} h. "
            f"Expected loss while locked: "
            f"${queue.get('expected_loss_while_locked_usd', 0):,.0f}."
        )


    # =====================================================
    # REASONS
    # =====================================================

    with st.expander("Why did FAULT LINE choose this?"):
        for reason in headline.get("reason", []):
            st.markdown(f"- {reason}")


# =========================================================
# VAULT LIQUIDITY SNAPSHOT
# =========================================================

section_label("VAULT LIQUIDITY")

top1 = q3.get("depositor_concentration", {}).get("top1_share", 0)
top5 = q3.get("depositor_concentration", {}).get("top5_share", 0)

v1, v2, v3, v4 = st.columns(4)

with v1:
    metric_card(
        "Total Assets",
        f"${total_assets / 1e6:,.2f}M",
        "Vault TVL",
    )

with v2:
    metric_card(
        "Instantly Withdrawable",
        f"${instant / 1e6:,.2f}M",
        f"{instant / total_assets:.1%} of vault"
        if total_assets
        else "N/A",
    )

with v3:
    metric_card(
        "Reachable Liquidity",
        f"${reachable / 1e6:,.2f}M",
        f"Penalty {withdrawable.get('force_deallocate_penalty', 0):.2%}",
    )

with v4:
    metric_card(
        "Depositor Concentration",
        f"{top1:.1%}",
        f"Top 5 = {top5:.1%}",
    )


# =========================================================
# Q1
# =========================================================

section_label("Q1 — WHERE DOES THE MONEY GO?")

st.markdown(
    """
FAULT LINE resolves the vault allocations down to the underlying collateral,
issuer structure and oracle basis.
"""
)

markets = q1.get("markets", [])
oracle_quality = m.get("oracle_quality", {}).get("per_market", {})

market_rows = []

for market in markets:
    symbol = market.get("collateral_symbol", "")
    oracle = oracle_quality.get(symbol, {})

    market_rows.append(
        {
            "Market": symbol,
            "Allocation ($)": market.get("allocation_usd", 0),
            "Share": market.get("allocation_pct", 0),
            "LLTV": market.get("lltv", 0),
            "Utilization": market.get("utilization", 0),
            "Free Liquidity ($)": market.get("free_liquidity_usd", 0),
            "Root Asset": market.get("root_symbol", ""),
            "Price Basis": oracle.get("price_basis", ""),
            "Oracle Confidence": oracle.get("confidence", ""),
        }
    )

if market_rows:
    q1_df = pd.DataFrame(market_rows)

    st.dataframe(
        q1_df.style.format(
            {
                "Allocation ($)": "${:,.0f}",
                "Share": "{:.1%}",
                "LLTV": "{:.1%}",
                "Utilization": "{:.1%}",
                "Free Liquidity ($)": "${:,.0f}",
            }
        ),
        hide_index=True,
        use_container_width=True,
    )


# =========================================================
# EXPOSURE
# =========================================================

exposure = q1.get("exposure", {})

if exposure:
    e1, e2 = st.columns(2)

    with e1:
        st.markdown("#### By root asset")

        root_data = exposure.get("root_asset", {})

        if root_data:
            st.bar_chart(
                pd.Series(
                    root_data,
                    name="Share of vault",
                )
            )

    with e2:
        st.markdown("#### By oracle price basis")

        price_data = exposure.get("price_basis", {})

        if price_data:
            st.bar_chart(
                pd.Series(
                    price_data,
                    name="Share of vault",
                )
            )


# =========================================================
# Q2
# =========================================================

section_label("Q2 — CAN BORROWERS REPAY?")

borrower_rows = []
shock_rows = []

for item in m.get("q2", []):
    hf = item.get("hf_buckets", {})
    collateral_exit = item.get("collateral_exit", {})

    liquidatable = hf.get(
        "<1.00 (liquidatable)",
        {},
    ).get("debt_share", 0)

    near = hf.get(
        "1.00-1.05",
        {},
    ).get("debt_share", 0)

    borrower_rows.append(
        {
            "Market": item.get("market"),
            "Borrowers Read": item.get("n_borrowers_read", 0),
            "Debt HF < 1.05": liquidatable + near,
            "Liquidation Capacity ($)": collateral_exit.get(
                "liquidation_capacity_usd"
            ),
            "Exit Confidence": collateral_exit.get("confidence", ""),
        }
    )

    for shock in item.get("shocks", []):
        shock_rows.append(
            {
                "Market": item.get("market"),
                "Oracle Move": shock.get("move", 0),
                "Vault Bad Debt ($)": shock.get(
                    "bad_debt_vault_usd",
                    0,
                ),
                "Loss Per Share": shock.get(
                    "loss_per_share",
                    0,
                ),
                "Liquidated Borrowers": shock.get(
                    "n_liquidated",
                    0,
                ),
                "Frozen Oracle Shortfall ($)": shock.get(
                    "frozen_oracle_shortfall_usd",
                    0,
                ),
            }
        )


if borrower_rows:
    borrower_df = pd.DataFrame(borrower_rows)

    st.dataframe(
        borrower_df.style.format(
            {
                "Debt HF < 1.05": "{:.1%}",
                "Liquidation Capacity ($)": "${:,.0f}",
            }
        ),
        hide_index=True,
        use_container_width=True,
    )


if shock_rows:
    shock_df = pd.DataFrame(shock_rows)

    st.markdown("#### Bad debt under shocks")

    st.dataframe(
        shock_df.style.format(
            {
                "Oracle Move": "{:+.0%}",
                "Vault Bad Debt ($)": "${:,.0f}",
                "Loss Per Share": "{:.2%}",
                "Frozen Oracle Shortfall ($)": "${:,.0f}",
            }
        ),
        hide_index=True,
        use_container_width=True,
    )


# =========================================================
# Q3
# =========================================================

section_label("Q3 — CAN DEPOSITORS WITHDRAW?")

run = q3.get("run", {})

ranks = run.get("ranks", [])

if ranks:
    rank_df = pd.DataFrame(ranks)

    st.markdown(
        "**Bank run executed on the fork:** depositors exit in size order, "
        "each withdrawal reduces the liquidity available to the next."
    )

    display_columns = [
        c
        for c in [
            "rank",
            "address",
            "owned_usd",
            "recovered_usd",
            "recovered_pct",
        ]
        if c in rank_df.columns
    ]

    st.dataframe(
        rank_df[display_columns].style.format(
            {
                "owned_usd": "${:,.0f}",
                "recovered_usd": "${:,.0f}",
                "recovered_pct": "{:.1%}",
            }
        ),
        hide_index=True,
        use_container_width=True,
    )

    if "rank" in rank_df and "recovered_pct" in rank_df:
        chart = rank_df[
            ["rank", "recovered_pct"]
        ].set_index("rank")

        st.bar_chart(chart)

    if run.get("note"):
        st.caption(run["note"])


# =========================================================
# FINDINGS
# =========================================================

section_label("KEY FINDINGS")

for finding in m.get("findings", []):
    st.markdown(
        f"- **{finding.get('q', '')}** "
        f"`{finding.get('kind', '')}` — "
        f"{finding.get('why', '')}"
    )


# =========================================================
# TRANSPARENCY
# =========================================================

section_label("REAL VS MODELED")

real_col, model_col = st.columns(2)

with real_col:
    st.markdown("### ✅ Measured / derived")

    st.markdown(
        """
- vault allocations
- borrower positions
- Health Factors
- vault liquidity
- depositor queue
- fork bank-run execution
- oracle structure
- withdrawal capacity
- shock response surfaces
"""
    )

with model_col:
    st.markdown("### ⚠️ Decision assumptions")

    st.markdown(
        """
- risk aversion λ
- decision horizon
- correlation ρ
- future event frequencies
- future shock severity
- governance scenario
"""
    )