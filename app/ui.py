"""Shared look for every page: one color per action, money / percent formats, the headline card, clean Plotly."""
import html

import plotly.graph_objects as go
import streamlit as st

# design tokens (dark navy theme of PR #1): same roles as before, dark-background values
BG, PANEL, PANEL_2, BORDER, DIVIDER = "#071018", "#0d1722", "#0c1721", "#223142", "#1d2d3c"
TEXT, BODY, CYAN = "#f4f7fb", "#c2ccd7", "#27d3ff"
GREEN, ORANGE, RED = "#28d17c", "#ffad3b", "#ff5864"
ACTION_COLORS = {"STAY": GREEN, "REDUCE": ORANGE, "EXIT": RED, "QUEUE EXIT NOW": RED}
INK, MUTED, ACCENT, NEUTRAL = TEXT, "#8ea0b4", "#4aa8ff", "#40566b"
ALERT = RED                 # also used to highlight a flagged dependency (oracle stuck at par)
BLUES = ["#1b3a50", "#1f6f99", "#27a9e0", "#5cdfff"]

THEME_CSS = """<style>
:root {--bg: #071018; --panel: #0d1722; --border: #223142; --text: #f4f7fb; --muted: #8ea0b4;
       --accent: #27d3ff; --green: #28d17c; --orange: #ffad3b; --red: #ff5864}

/* global: dark navy with a subtle cyan glow */
.stApp {background: radial-gradient(circle at top right, rgba(39, 211, 255, 0.06), transparent 30%), #071018;
        color: var(--text)}
h1, h2, h3 {color: #fff !important}
p, li {color: #c2ccd7}
hr {border: none !important; border-top: 1px solid #1d2d3c !important}

/* sidebar: navy gradient, thin divider, cyan selection and hover */
[data-testid="stSidebar"] {background: radial-gradient(circle at top, rgba(39, 211, 255, 0.08), transparent 25%),
                           linear-gradient(180deg, #0a141e 0%, #071018 100%); border-right: 1px solid #1c3041}
[data-testid="stSidebarNav"] a {border-radius: 10px; border: 1px solid transparent; transition: all 0.16s ease}
[data-testid="stSidebarNav"] a:hover {background: rgba(39, 211, 255, 0.06); border-color: rgba(39, 211, 255, 0.18);
                                      transform: translateX(2px)}
[data-testid="stSidebarNav"] a[aria-current="page"] {
    background: linear-gradient(90deg, rgba(39, 211, 255, 0.15), rgba(39, 211, 255, 0.04));
    border: 1px solid rgba(39, 211, 255, 0.28)}
[data-testid="stSidebarNav"] a[aria-current="page"] span {color: #5cdfff !important; font-weight: 700}
[data-testid="stSidebarUserContent"] {border-top: 1px solid #1d2d3c}

/* page header: the hero treatment around the existing title + subtitle */
.st-key-fl_hero {background: radial-gradient(circle at 90% 10%, rgba(39, 211, 255, 0.15), transparent 32%),
                 linear-gradient(135deg, #0d1924, #09131c);
                 border: 1px solid #26384a; border-radius: 18px; padding: 0.9rem 1.6rem 0.7rem 1.6rem;
                 margin-bottom: 0.4rem; box-shadow: 0 18px 50px rgba(0, 0, 0, 0.22); gap: 0}
.st-key-fl_hero h1 {font-weight: 800 !important; letter-spacing: -0.03em; padding: 0.3rem 0 0.35rem 0 !important;
                    line-height: 1.15 !important}
.st-key-fl_hero [data-testid="stMarkdownContainer"] > div {margin: 0 0 0.35rem 0 !important}

/* section labels (#### headers): cyan, small, uppercase */
.block-container h4 {color: #27d3ff !important; font-size: 0.8rem !important; font-weight: 750 !important;
                     letter-spacing: 0.12em; text-transform: uppercase; padding-top: 1rem}

/* metrics and expanders: navy panels, thin borders, cyan hover */
[data-testid="stMetric"] {background: linear-gradient(180deg, rgba(17, 29, 41, 0.98), rgba(10, 20, 30, 0.98));
                          border: 1px solid var(--border); border-radius: 15px; padding: 0.8rem 1rem;
                          box-shadow: 0 10px 30px rgba(0, 0, 0, 0.15); transition: all 0.18s ease}
[data-testid="stMetric"]:hover {border-color: rgba(39, 211, 255, 0.45); transform: translateY(-2px)}
[data-testid="stMetricLabel"] p {color: var(--muted) !important}
[data-testid="stExpander"] details {background: #0c1721; border: 1px solid var(--border) !important;
                                    border-radius: 12px; transition: border-color 0.18s ease}
[data-testid="stExpander"] details:hover {border-color: rgba(39, 211, 255, 0.35) !important}
[data-testid="stAlert"] {border-radius: 12px}

/* buttons: cyan-to-blue gradient for primary actions, soft glow, small lift */
.stButton > button {border-radius: 12px; min-height: 44px; font-weight: 650; transition: all 0.18s ease}
.stButton > button:hover {transform: translateY(-2px)}
.stButton > button[kind="primary"] {background: linear-gradient(135deg, #14bde8, #258cff);
                                    border: 1px solid #27d3ff; color: #fff;
                                    box-shadow: 0 8px 28px rgba(39, 211, 255, 0.18)}
.stButton > button[kind="primary"]:hover {box-shadow: 0 10px 35px rgba(39, 211, 255, 0.30)}
[data-testid="stPageLink"] a {border-radius: 10px; transition: all 0.16s ease}
[data-testid="stPageLink"] a:hover {background: rgba(39, 211, 255, 0.08)}
[data-testid="stPageLink"] a p {color: #5cdfff !important; font-weight: 650}

/* inputs */
[data-baseweb="select"] > div {background: #0c1721 !important; border-color: #26394a !important}
[data-testid="stNumberInput"] input {background: #0c1721 !important; color: #fff !important}

/* charts and the graph frame */
[data-testid="stPlotlyChart"], iframe {border-radius: 14px}
iframe {border: 1px solid var(--border) !important}

/* scrollbar */
::-webkit-scrollbar {width: 8px}
::-webkit-scrollbar-track {background: #071018}
::-webkit-scrollbar-thumb {background: #273b4d; border-radius: 20px}
::-webkit-scrollbar-thumb:hover {background: #36566f}
</style>"""


def usd(x: float | None, signed: bool = False) -> str:
    """$1.2M / $120k / $950."""
    if x is None:
        return "n/a"
    sign = ("+" if x > 0 else "−" if x < 0 else "") if signed else ("−" if x < 0 else "")
    a = abs(x)
    if a >= 1e9:
        s = f"${a / 1e9:.2f}B"
    elif a >= 1e6:
        s = f"${a / 1e6:.1f}M"
    elif a >= 1e3:
        s = f"${a / 1e3:.0f}k"
    else:
        s = f"${a:,.0f}"
    return sign + s


def pct(x: float | None, signed: bool = False) -> str:
    if x is None:
        return "n/a"
    return f"{x * 100:+.1f}%" if signed else f"{x * 100:.1f}%"


def bps(x: float) -> str:
    return f"{x:+.1f}".replace("-", "−")


def action_label(h: dict) -> str:
    return h["action"] + (f" {h['exit_fraction']:.0%}" if h["action"] == "REDUCE" else "")


def setup(title: str, subtitle: str = "") -> None:
    """Page title + the CSS that keeps key numbers readable on a projector (>= 14px)."""
    st.markdown(THEME_CSS, unsafe_allow_html=True)
    st.markdown("""<style>
    .block-container {padding-top: 1.4rem; max-width: 1400px}
    h1 {font-size: 2.1rem !important; padding-bottom: .2rem !important}
    [data-testid="stMetricValue"] {font-size: 1.6rem}
    [data-testid="stMetricLabel"] p {font-size: 0.95rem}
    .fl-card {border: 1px solid var(--border); border-left: 6px solid var(--c); border-radius: 16px;
              padding: 14px 20px; margin: 4px 0 10px 0;
              background: linear-gradient(180deg, rgba(17, 29, 41, 0.98), rgba(10, 20, 30, 0.98));
              box-shadow: 0 10px 30px rgba(0, 0, 0, 0.15); transition: all 0.18s ease}
    .fl-card:hover {transform: translateY(-3px); border-color: rgba(39, 211, 255, 0.45); border-left-color: var(--c);
                    box-shadow: 0 14px 36px rgba(0, 0, 0, 0.25)}
    .fl-card .row {display: flex; gap: 28px; align-items: baseline; flex-wrap: wrap}
    .fl-card .act {font-size: 44px; font-weight: 800; color: var(--c); line-height: 1.1}
    .fl-card .num {font-size: 30px; font-weight: 760; color: #fff; letter-spacing: -0.03em}
    .fl-card .sub {font-size: 15px; color: #8ea0b4}
    .fl-card .why {font-size: 17px; color: #e3e9f0; margin-top: 6px}
    .fl-card .lab {font-size: 13px; color: #8ea0b4; font-weight: 750; text-transform: uppercase; letter-spacing: .09em}
    .fl-card.small .act {font-size: 32px} .fl-card.small .num {font-size: 22px} .fl-card.small .why {font-size: 15px}
    .fl-card.small .row {gap: 4px 16px} .fl-card.small .sub {font-size: 14px}
    .fl-find {font-size: 16px; line-height: 1.5; margin: 0 0 4px 0; color: #c2ccd7}
    .fl-find b {color: #fff}
    .fl-take {font-size: 16px; color: #c2ccd7; margin: -6px 0 6px 0}
    .fl-card .num .words {font-size: 0.62em; font-weight: 600; color: #c2ccd7; letter-spacing: 0}
    .fl-marginal {--c: #40566b; color: #c2ccd7 !important; font-size: 13px !important; font-weight: 650;
                  margin-left: 10px; vertical-align: middle; letter-spacing: .04em}
    .fl-tag {display: inline-block; border-radius: 4px; padding: 1px 7px; font-size: 13px; font-weight: 600;
             color: #fff; background: var(--c)}
    </style>""", unsafe_allow_html=True)
    with st.container(key="fl_hero"):       # styled as the hero header (THEME_CSS .st-key-fl_hero)
        st.title(title)
        if subtitle:
            st.markdown(f"<div style='font-size:17px;color:#a7b5c3;margin:-10px 0 8px 0'>{subtitle}</div>",
                        unsafe_allow_html=True)


def headline_card(h: dict, why: str, label: str = "Net value of exiting now", small: bool = False,
                  extra: str = "") -> None:
    """Action in large colored text, net $ and bps next to it, one-line why."""
    c = ACTION_COLORS.get(h["action"], INK)
    net, b = h["net_value_exit_now_usd"], h["net_value_exit_now_bps_book"]
    # plain words; the sign decides (a budget-forced REDUCE can carry a negative net, which is a cost, not a saving)
    saves = net >= 0
    words = "Exiting now saves you" if saves else "Exiting now would cost you"
    marginal = "<span class='fl-tag fl-marginal'>marginal</span>" if abs(b) < 1 else ""
    st.markdown(
        f"<div class='fl-card{' small' if small else ''}' style='--c:{c}'>"
        f"<div class='lab'>{html.escape(label)}</div><div class='row'>"
        f"<div class='act'>{html.escape(action_label(h))}{marginal}</div>"
        f"<div><div class='num'><span class='words'>{words}</span> {usd(abs(net))}</div>"
        f"<div class='sub'>{'saves' if saves else 'would cost'} {abs(b):.1f} bps of the "
        f"{html.escape(h['bps_basis'])}</div></div>"
        f"</div><div class='why'>{html.escape(why)}</div>{extra}</div>", unsafe_allow_html=True)


def findings(lines: list[str]) -> None:
    st.markdown("".join(f"<p class='fl-find'>• {x}</p>" for x in lines[:3]), unsafe_allow_html=True)


def takeaway(text: str) -> None:
    st.markdown(f"<p class='fl-take'>{text}</p>", unsafe_allow_html=True)


def table(rows: list[dict], money: tuple = (), pcts: tuple = ()) -> None:
    """A dataframe with $1.2M / 12.3% formatting (display only)."""
    import pandas as pd
    df = pd.DataFrame(rows)
    for col in money:
        if col in df:
            df[col] = df[col].map(lambda v: usd(v) if v is not None and v == v else "")
    for col in pcts:
        if col in df:
            df[col] = df[col].map(lambda v: pct(v) if v is not None and v == v else "")
    st.dataframe(df, hide_index=True, width="stretch")


def clean(fig: go.Figure, title: str, height: int = 360, **layout) -> go.Figure:
    """No gridline clutter, a title that states the takeaway, readable fonts."""
    legend = layout.get("showlegend", False)
    fig.update_layout(title={"text": title, "font": {"size": 18, "color": INK}, "x": 0, "xanchor": "left"},
                      template="simple_white", height=height,
                      margin={"l": 10, "r": 20, "t": 84 if legend else 56, "b": 10},
                      font={"size": 14, "color": BODY}, showlegend=layout.pop("showlegend", False),
                      legend={"orientation": "h", "y": 1.0, "yanchor": "bottom", "x": 0}, plot_bgcolor=PANEL,
                      paper_bgcolor=PANEL, hoverlabel={"bgcolor": PANEL_2, "bordercolor": CYAN, "font_color": TEXT},
                      **layout)
    for ax in (fig.update_xaxes, fig.update_yaxes):
        ax(showgrid=False, zeroline=False, linecolor=BORDER, tickcolor=BORDER, tickfont_color=MUTED,
           title_font_color=MUTED)
    return fig


def chart(fig: go.Figure) -> None:
    st.plotly_chart(fig, width="stretch", theme=None, config={"displayModeBar": False})
