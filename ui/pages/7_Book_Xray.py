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
    page_title="Book X-ray | FAULT LINE",
    page_icon="🩻",
    layout="wide",
)

init_state()
apply_global_style()


# =========================================================
# DATA
# =========================================================

ENGINE_ROOT = Path.home() / "Desktop" / "fault-line"

BOOK_XRAY_FILE = ENGINE_ROOT / "data" / "book_xray.json"
XRAY_FILE = ENGINE_ROOT / "data" / "xray.json"


@st.cache_data
def load_json(path):
    if not path.exists():
        return None

    with open(path, "r") as f:
        return json.load(f)


book_xray = load_json(BOOK_XRAY_FILE)
xray = load_json(XRAY_FILE)


if book_xray is None:
    st.error(
        "Book X-ray data not found.\n\n"
        "Expected: `~/Desktop/fault-line/data/book_xray.json`"
    )
    st.stop()


# =========================================================
# HERO
# =========================================================

hero(
    "BOOK X-RAY",
    "Look through the portfolio and find risks that appear diversified on the surface but depend on the same underlying issuers.",
    "PORTFOLIO DEPENDENCY ANALYSIS",
)

badge("25 VAULTS · SHARED DEPENDENCIES", "real")


# =========================================================
# HEADLINE
# =========================================================

book_usd = book_xray.get("book_usd", 0)
n_vaults = book_xray.get("n_vaults", 0)
effective_bets = book_xray.get("effective_bets", 0)

groups = book_xray.get("groups", [])

huma = next(
    (
        g for g in groups
        if str(g.get("issuer", "")).lower() == "huma"
    ),
    None,
)

huma_share = huma.get("share", 0) if huma else 0
huma_usd = huma.get("usd", 0) if huma else 0


section_label("PORTFOLIO HEADLINE")

h1, h2, h3, h4 = st.columns(4)

with h1:
    metric_card(
        "Vaults",
        f"{n_vaults}",
        "Belem / RockawayX book",
    )

with h2:
    metric_card(
        "Book Size",
        f"${book_usd / 1e6:,.1f}M",
        "Total represented TVL",
    )

with h3:
    metric_card(
        "Independent Bets",
        f"{effective_bets:.1f}",
        "Effective diversification",
    )

with h4:
    metric_card(
        "Huma Dependency",
        f"≥ {huma_share:.1%}",
        f"At least ${huma_usd / 1e6:,.1f}M",
    )


st.warning(
    f"The book contains {n_vaults} vaults, but only about "
    f"{effective_bets:.1f} effective independent bets. "
    f"At least {huma_share:.1%} of the book depends on Huma."
)


# =========================================================
# WHY "AT LEAST"
# =========================================================

with st.expander("Why does it say 'at least'?"):
    st.markdown(
        """
Not every vault has been fully resolved down to its underlying dependencies.

So when FAULT LINE says:

**at least 25.7% depends on Huma**

it means that this dependency has already been identified in the portion of the
portfolio we can resolve.

Additional unresolved vaults could increase the true concentration.
"""
    )


# =========================================================
# COVERAGE
# =========================================================

section_label("COVERAGE")

coverage = book_xray.get("coverage", {})

resolved_usd = coverage.get("resolved_usd", 0)
resolved_share = coverage.get("resolved_share", 0)
unresolved_usd = coverage.get("unresolved_usd", 0)
n_resolved = coverage.get("n_resolved", 0)

c1, c2, c3 = st.columns(3)

with c1:
    metric_card(
        "Resolved Vaults",
        f"{n_resolved}",
        "Resolved on-chain / Morpho API",
    )

with c2:
    metric_card(
        "Resolved TVL",
        f"{resolved_share:.1%}",
        f"${resolved_usd / 1e6:,.1f}M",
    )

with c3:
    metric_card(
        "Unresolved TVL",
        f"${unresolved_usd / 1e6:,.1f}M",
        "CSV / label-level only",
    )

st.caption(
    "Coverage is intentionally explicit: unresolved vaults are not silently "
    "treated as fully understood."
)


# =========================================================
# SHARED ISSUERS
# =========================================================

section_label("SHARED ISSUERS")

st.markdown(
    """
A portfolio can look diversified because it contains many vaults.

But if several vaults ultimately depend on the **same issuer**, those positions
can fail together.
"""
)

shared_groups = [
    group
    for group in groups
    if group.get("n_vaults", 0) >= 2
    or group.get("issuer") in (
        "Huma",
        "Tori Finance",
        "Re Protocol",
        "Midas",
        "OnRe",
    )
]

issuer_rows = []

for group in shared_groups:
    issuer_rows.append(
        {
            "Issuer / Dependency": group.get("issuer", ""),
            "Exposure ($)": group.get("usd", 0),
            "Book Share": group.get("share", 0),
            "Vaults": group.get("n_vaults", 0),
            "Tokens": ", ".join(group.get("tokens", [])),
            "Resolved Via": ", ".join(group.get("how", [])),
            "Vault Names": ", ".join(group.get("vaults", [])),
        }
    )

if issuer_rows:
    issuer_df = pd.DataFrame(issuer_rows)

    st.dataframe(
        issuer_df.style.format(
            {
                "Exposure ($)": "${:,.0f}",
                "Book Share": "{:.1%}",
            }
        ),
        hide_index=True,
        use_container_width=True,
    )


# =========================================================
# CONCENTRATION CHART
# =========================================================

section_label("WHERE IS THE CONCENTRATION?")

chart_rows = []

for group in groups:
    if group.get("share", 0) > 0:
        chart_rows.append(
            {
                "Issuer": group.get("issuer", ""),
                "Book Share": group.get("share", 0),
            }
        )

if chart_rows:
    chart_df = (
        pd.DataFrame(chart_rows)
        .sort_values("Book Share", ascending=False)
        .head(12)
        .set_index("Issuer")
    )

    st.bar_chart(chart_df)


# =========================================================
# TORI LOOP
# =========================================================

section_label("TORI LOOP")

tori = next(
    (
        group
        for group in groups
        if group.get("issuer") == "Tori Finance"
    ),
    None,
)

if tori:
    t1, t2, t3 = st.columns(3)

    with t1:
        metric_card(
            "Tori Exposure",
            f"${tori.get('usd', 0) / 1e6:,.1f}M",
            f"{tori.get('share', 0):.1%} of book",
        )

    with t2:
        metric_card(
            "Vaults",
            f"{tori.get('n_vaults', 0)}",
            "Connected to Tori",
        )

    with t3:
        metric_card(
            "Tokens",
            f"{len(tori.get('tokens', []))}",
            "Tori-linked assets",
        )

    st.markdown(
        """
The important finding is not just that several vaults have Tori exposure.

The portfolio contains a **dependency loop**: vault exposures can ultimately
reference assets created by the same ecosystem, so positions that appear
separate may actually share the same failure source.
"""
    )

    st.code(
        """
Belem vault A
      |
      v
Tori-linked collateral
      |
      v
Tori ecosystem
      ^
      |
Belem vault B
""",
        language=None,
    )

    st.caption(
        "This is why counting vaults is not the same thing as counting "
        "independent economic bets."
    )


# =========================================================
# EFFECTIVE BETS
# =========================================================

section_label("WHY 25 VAULTS ≠ 25 BETS")

st.markdown(
    """
If two vaults depend on the same issuer, oracle, collateral system or exit
liquidity, they may fail at the same time.

FAULT LINE therefore groups correlated exposures into **economic bets**.

The question becomes:

**How many genuinely independent things have to go wrong?**
"""
)

if xray:
    n_pockets = xray.get("n_pockets", 0)
    n_bets = xray.get("n_bets", 0)
    effective_independent = xray.get(
        "effective_independent_bets",
        0,
    )

    b1, b2, b3 = st.columns(3)

    with b1:
        metric_card(
            "Analyzed Pockets",
            f"{n_pockets}",
            "Detailed dependency pockets",
        )

    with b2:
        metric_card(
            "Grouped Bets",
            f"{n_bets}",
            "Pockets failing together",
        )

    with b3:
        metric_card(
            "Effective Bets",
            f"{effective_independent:.1f}",
            "Dependency-adjusted diversification",
        )


# =========================================================
# BET GROUPS
# =========================================================

if xray and xray.get("bets"):

    st.markdown("#### Dependency-adjusted bets")

    bet_rows = []

    for bet in xray["bets"]:
        bet_rows.append(
            {
                "Weight": bet.get("weight", 0),
                "Pockets": ", ".join(bet.get("pockets", [])),
                "Shared Via": ", ".join(
                    bet.get("shared_ancestors", [])[:5]
                ),
            }
        )

    bet_df = pd.DataFrame(bet_rows)

    st.dataframe(
        bet_df.style.format(
            {
                "Weight": "{:.1%}",
            }
        ),
        hide_index=True,
        use_container_width=True,
    )


# =========================================================
# SHARED ANCESTORS
# =========================================================

if xray and xray.get("shared_ancestors"):

    section_label("SHARED DEPENDENCY ANCESTORS")

    ancestors = xray["shared_ancestors"]

    ancestor_rows = []

    for item in ancestors:
        ancestor_rows.append(
            {
                "Dependency": item.get("label", ""),
                "Type": item.get("type", ""),
                "Book Share": item.get("book_share", 0),
                "Pockets": ", ".join(item.get("pockets", [])),
                "Numeraire": item.get("numeraire", False),
            }
        )

    ancestor_df = (
        pd.DataFrame(ancestor_rows)
        .sort_values(
            ["Numeraire", "Book Share"],
            ascending=[True, False],
        )
    )

    st.dataframe(
        ancestor_df.style.format(
            {
                "Book Share": "{:.1%}",
            }
        ),
        hide_index=True,
        use_container_width=True,
    )


# =========================================================
# WORST SINGLE POINT
# =========================================================

if xray and xray.get("worst_single_point_of_failure"):

    section_label("LARGEST SHARED SINGLE POINT OF FAILURE")

    worst = xray["worst_single_point_of_failure"]

    w1, w2, w3 = st.columns(3)

    with w1:
        metric_card(
            "Dependency",
            worst.get("label", "N/A"),
            worst.get("type", ""),
        )

    with w2:
        metric_card(
            "Book Share",
            f"{worst.get('book_share', 0):.1%}",
            "Exposed analyzed pockets",
        )

    with w3:
        metric_card(
            "Pockets",
            str(len(worst.get("pockets", []))),
            ", ".join(worst.get("pockets", [])),
        )


# =========================================================
# SHARED EXIT LIQUIDITY
# =========================================================

if xray:

    section_label("SHARED EXIT LIQUIDITY")

    shared_exit = xray.get("shared_exit_liquidity", [])

    if shared_exit:
        exit_rows = []

        for item in shared_exit:
            exit_rows.append(
                {
                    "Liquidity Dependency": item.get("label", ""),
                    "Pockets": ", ".join(item.get("pockets", [])),
                    "Book Share": item.get("book_share", 0),
                }
            )

        exit_df = pd.DataFrame(exit_rows)

        st.dataframe(
            exit_df.style.format(
                {
                    "Book Share": "{:.1%}",
                }
            ),
            hide_index=True,
            use_container_width=True,
        )

        st.warning(
            "These positions can compete for the same exit liquidity during "
            "stress. Their exits are therefore not independent."
        )

    else:
        st.info(
            "No shared executed exit-liquidity dependency was identified "
            "in the current analyzed pockets."
        )


# =========================================================
# KEY MESSAGE
# =========================================================

section_label("BOTTOM LINE")

st.success(
    f"{n_vaults} vaults do not mean {n_vaults} independent bets. "
    f"The current portfolio resolves to roughly {effective_bets:.1f} "
    f"effective bets, with at least {huma_share:.1%} depending on Huma."
)


# =========================================================
# TRANSPARENCY
# =========================================================

section_label("WHAT IS RESOLVED VS NOT RESOLVED")

left, right = st.columns(2)

with left:
    st.markdown("### ✅ Resolved")

    st.markdown(
        """
- supported Morpho vault structures
- wrapper chains
- underlying collateral / issuers
- shared dependencies
- dependency-adjusted bet grouping
- shared exit-liquidity links where available
"""
    )

with right:
    st.markdown("### ⚠️ Partial / unresolved")

    st.markdown(
        """
- some non-Morpho vaults
- some CSV-only entries
- issuer inference where only the vault/token name is available
- unresolved exposures are kept explicit rather than treated as known
"""
    )