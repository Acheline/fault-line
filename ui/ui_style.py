import streamlit as st
from textwrap import dedent


def apply_global_style():

    st.markdown(
        """
<style>

:root {
    --bg: #071018;
    --panel: #0d1722;
    --border: #223142;
    --text: #f4f7fb;
    --muted: #8ea0b4;

    --accent: #27d3ff;
    --green: #28d17c;
    --orange: #ffad3b;
    --red: #ff5864;
}


/* ============================================================
   GLOBAL
============================================================ */

.stApp {
    background:
        radial-gradient(
            circle at top right,
            rgba(39, 211, 255, 0.06),
            transparent 30%
        ),
        #071018;

    color: var(--text);
}


.block-container {
    max-width: 1450px;

    padding-top: 2rem;
    padding-bottom: 4rem;
    padding-left: 2.5rem;
    padding-right: 2.5rem;
}


h1,
h2,
h3 {
    color: white !important;
}


p,
li {
    color: #c2ccd7;
}


/* ============================================================
   SIDEBAR
============================================================ */

[data-testid="stSidebar"] {

    background:
        radial-gradient(
            circle at top,
            rgba(39, 211, 255, 0.08),
            transparent 25%
        ),
        linear-gradient(
            180deg,
            #0a141e 0%,
            #071018 100%
        );

    border-right:
        1px solid #1c3041;
}


[data-testid="stSidebar"] > div:first-child {

    padding-top:
        0.8rem;
}


/* Sidebar product branding */

[data-testid="stSidebarNav"]::before {

    content:
        "⚡ FAULT LINE";

    display:
        block;

    color:
        #ffffff;

    font-size:
        1.35rem;

    font-weight:
        800;

    letter-spacing:
        -0.03em;

    padding:
        0.7rem 1rem 0.1rem 1rem;
}


[data-testid="stSidebarNav"]::after {

    content:
        "DEFI RISK ENGINE  •  ETHEREUM FORK";

    display:
        block;

    color:
        #27d3ff;

    font-size:
        0.61rem;

    font-weight:
        750;

    letter-spacing:
        0.10em;

    padding:
        0.2rem 1rem 1.15rem 1rem;

    border-bottom:
        1px solid #1c3041;

    margin-bottom:
        0.65rem;
}


/* Individual nav links */

[data-testid="stSidebarNav"] a {

    border-radius:
        10px;

    margin:
        0.13rem 0.55rem;

    padding:
        0.55rem 0.7rem;

    transition:
        all 0.16s ease;

    border:
        1px solid transparent;
}


[data-testid="stSidebarNav"] a:hover {

    background:
        rgba(39, 211, 255, 0.06);

    border-color:
        rgba(39, 211, 255, 0.18);

    transform:
        translateX(2px);
}


/* Active page */

[data-testid="stSidebarNav"] a[aria-current="page"] {

    background:
        linear-gradient(
            90deg,
            rgba(39, 211, 255, 0.15),
            rgba(39, 211, 255, 0.04)
        );

    border:
        1px solid rgba(39, 211, 255, 0.28);
}


[data-testid="stSidebarNav"] a[aria-current="page"] span {

    color:
        #5cdfff !important;

    font-weight:
        700;
}


/* ============================================================
   METRICS
============================================================ */

[data-testid="stMetric"] {

    background:
        #0d1722;

    border:
        1px solid var(--border);

    border-radius:
        15px;

    padding:
        1rem;
}


/* ============================================================
   EXPANDERS
============================================================ */

[data-testid="stExpander"] {

    background:
        #0c1721;

    border:
        1px solid var(--border);

    border-radius:
        12px;

    transition:
        border-color 0.18s ease;
}


[data-testid="stExpander"]:hover {

    border-color:
        rgba(39, 211, 255, 0.35);
}


/* ============================================================
   ALERTS
============================================================ */

[data-testid="stAlert"] {

    border-radius:
        12px;
}


/* ============================================================
   BUTTONS
============================================================ */

.stButton > button {

    border-radius:
        12px;

    min-height:
        44px;

    font-weight:
        650;

    transition:
        all 0.18s ease;
}


.stButton > button:hover {

    transform:
        translateY(-2px);
}


.stButton > button[kind="primary"] {

    background:
        linear-gradient(
            135deg,
            #14bde8,
            #258cff
        );

    border:
        1px solid #27d3ff;

    color:
        white;

    box-shadow:
        0 8px 28px rgba(39, 211, 255, 0.18);
}


.stButton > button[kind="primary"]:hover {

    box-shadow:
        0 10px 35px rgba(39, 211, 255, 0.30);
}


/* ============================================================
   INPUTS
============================================================ */

[data-baseweb="select"] > div {

    background:
        #0c1721 !important;

    border-color:
        #26394a !important;
}


[data-testid="stNumberInput"] input {

    background:
        #0c1721 !important;

    color:
        white !important;
}


/* ============================================================
   DIVIDERS
============================================================ */

hr {

    border:
        none !important;

    border-top:
        1px solid #1d2d3c !important;
}


/* ============================================================
   HERO
============================================================ */

.fl-hero {

    background:
        radial-gradient(
            circle at 90% 10%,
            rgba(39, 211, 255, 0.15),
            transparent 32%
        ),
        linear-gradient(
            135deg,
            #0d1924,
            #09131c
        );

    border:
        1px solid #26384a;

    border-radius:
        22px;

    padding:
        2rem 2.2rem;

    margin-bottom:
        1rem;

    box-shadow:
        0 18px 50px rgba(0, 0, 0, 0.22);
}


.fl-hero-kicker {

    color:
        #27d3ff;

    font-size:
        0.76rem;

    font-weight:
        750;

    letter-spacing:
        0.14em;

    text-transform:
        uppercase;

    margin-bottom:
        0.7rem;
}


.fl-hero-title {

    color:
        white;

    font-size:
        3.2rem;

    line-height:
        1;

    font-weight:
        800;

    letter-spacing:
        -0.055em;
}


.fl-hero-subtitle {

    color:
        #a7b5c3;

    font-size:
        1.05rem;

    margin-top:
        0.8rem;
}


/* ============================================================
   CARDS
============================================================ */

.fl-card {

    background:
        linear-gradient(
            180deg,
            rgba(17, 29, 41, 0.98),
            rgba(10, 20, 30, 0.98)
        );

    border:
        1px solid var(--border);

    border-radius:
        16px;

    padding:
        1.15rem 1.25rem;

    min-height:
        115px;

    box-shadow:
        0 10px 30px rgba(0, 0, 0, 0.15);

    transition:
        all 0.18s ease;
}


.fl-card:hover {

    transform:
        translateY(-3px);

    border-color:
        rgba(39, 211, 255, 0.45);

    box-shadow:
        0 14px 36px rgba(0, 0, 0, 0.25);
}


.fl-card-title {

    color:
        var(--muted);

    font-size:
        0.72rem;

    font-weight:
        750;

    letter-spacing:
        0.09em;

    text-transform:
        uppercase;
}


.fl-card-value {

    color:
        white;

    font-size:
        1.55rem;

    font-weight:
        760;

    margin-top:
        0.45rem;

    letter-spacing:
        -0.03em;
}


.fl-card-subtitle {

    color:
        #8ea0b4;

    font-size:
        0.82rem;

    margin-top:
        0.35rem;
}


/* ============================================================
   BADGES
============================================================ */

.fl-badge {

    display:
        inline-flex;

    align-items:
        center;

    border-radius:
        999px;

    padding:
        0.3rem 0.7rem;

    font-size:
        0.72rem;

    font-weight:
        750;

    letter-spacing:
        0.05em;

    border:
        1px solid;
}


.fl-badge-real {

    color:
        #59e89b;

    border-color:
        rgba(40, 209, 124, 0.45);

    background:
        rgba(40, 209, 124, 0.10);
}


.fl-badge-model {

    color:
        #ffbf61;

    border-color:
        rgba(255, 173, 59, 0.45);

    background:
        rgba(255, 173, 59, 0.10);
}


.fl-badge-risk {

    color:
        #ff7882;

    border-color:
        rgba(255, 88, 100, 0.45);

    background:
        rgba(255, 88, 100, 0.10);
}


.fl-badge-accent {

    color:
        #5cdfff;

    border-color:
        rgba(39, 211, 255, 0.45);

    background:
        rgba(39, 211, 255, 0.10);
}


/* ============================================================
   SECTION LABEL
============================================================ */

.fl-section-label {

    color:
        #27d3ff;

    font-size:
        0.73rem;

    font-weight:
        750;

    letter-spacing:
        0.12em;

    text-transform:
        uppercase;

    margin-top:
        1.4rem;

    margin-bottom:
        0.55rem;
}


/* ============================================================
   SHOCK BANNER
============================================================ */

.fl-shock-banner {

    background:
        linear-gradient(
            90deg,
            rgba(255, 88, 100, 0.15),
            rgba(255, 88, 100, 0.03)
        );

    border:
        1px solid rgba(255, 88, 100, 0.4);

    border-radius:
        14px;

    color:
        #ff8b94;

    font-weight:
        700;

    padding:
        1rem 1.2rem;

    margin:
        1rem 0;

    box-shadow:
        0 8px 26px rgba(255, 88, 100, 0.06);
}


/* ============================================================
   SCROLLBAR
============================================================ */

::-webkit-scrollbar {

    width:
        8px;
}


::-webkit-scrollbar-track {

    background:
        #071018;
}


::-webkit-scrollbar-thumb {

    background:
        #273b4d;

    border-radius:
        20px;
}


::-webkit-scrollbar-thumb:hover {

    background:
        #36566f;
}

</style>
""",
        unsafe_allow_html=True
    )


# ============================================================
# HERO COMPONENT
# ============================================================

def hero(
    title,
    subtitle,
    kicker="DEFI RISK ENGINE"
):

    html = f"""
<div class="fl-hero">
    <div class="fl-hero-kicker">{kicker}</div>
    <div class="fl-hero-title">{title}</div>
    <div class="fl-hero-subtitle">{subtitle}</div>
</div>
"""

    st.markdown(
        dedent(html),
        unsafe_allow_html=True
    )


# ============================================================
# BADGE COMPONENT
# ============================================================

def badge(
    text,
    kind="accent"
):

    classes = {

        "real":
            "fl-badge-real",

        "model":
            "fl-badge-model",

        "risk":
            "fl-badge-risk",

        "accent":
            "fl-badge-accent"
    }


    css_class = classes.get(
        kind,
        "fl-badge-accent"
    )


    html = f"""
<span class="fl-badge {css_class}">{text}</span>
"""


    st.markdown(
        dedent(html),
        unsafe_allow_html=True
    )


# ============================================================
# METRIC CARD
# ============================================================

def metric_card(
    title,
    value,
    subtitle=""
):

    html = f"""
<div class="fl-card">
    <div class="fl-card-title">{title}</div>
    <div class="fl-card-value">{value}</div>
    <div class="fl-card-subtitle">{subtitle}</div>
</div>
"""


    st.markdown(
        dedent(html),
        unsafe_allow_html=True
    )


# ============================================================
# SECTION LABEL
# ============================================================

def section_label(
    text
):

    html = f"""
<div class="fl-section-label">{text}</div>
"""


    st.markdown(
        dedent(html),
        unsafe_allow_html=True
    )


# ============================================================
# SHOCK BANNER
# ============================================================

def shock_banner(
    text
):

    html = f"""
<div class="fl-shock-banner">💥 {text}</div>
"""


    st.markdown(
        dedent(html),
        unsafe_allow_html=True
    )