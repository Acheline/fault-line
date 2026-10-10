"""Shared look for every page: one color per action, money / percent formats, the headline card, clean Plotly."""
import html

import plotly.graph_objects as go
import streamlit as st

ACTION_COLORS = {"STAY": "#2b8a3e", "REDUCE": "#e67700", "EXIT": "#c92a2a", "QUEUE EXIT NOW": "#c92a2a"}
INK, MUTED, ACCENT, NEUTRAL = "#212529", "#868e96", "#1971c2", "#ced4da"
ALERT = "#c92a2a"           # also used to highlight a flagged dependency (oracle stuck at par)
BLUES = ["#d0ebff", "#74c0fc", "#339af0", "#1864ab"]


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
    st.markdown("""<style>
    .block-container {padding-top: 1.4rem; max-width: 1400px}
    h1 {font-size: 2.1rem !important; padding-bottom: .2rem !important}
    [data-testid="stMetricValue"] {font-size: 1.6rem}
    [data-testid="stMetricLabel"] p {font-size: 0.95rem}
    .fl-card {border: 1px solid #e9ecef; border-left: 8px solid var(--c); border-radius: 10px; padding: 14px 20px;
              background: #fff; margin: 4px 0 10px 0}
    .fl-card .row {display: flex; gap: 28px; align-items: baseline; flex-wrap: wrap}
    .fl-card .act {font-size: 44px; font-weight: 800; color: var(--c); line-height: 1.1}
    .fl-card .num {font-size: 30px; font-weight: 700; color: #212529}
    .fl-card .sub {font-size: 15px; color: #495057}
    .fl-card .why {font-size: 17px; color: #212529; margin-top: 6px}
    .fl-card .lab {font-size: 14px; color: #868e96; text-transform: uppercase; letter-spacing: .04em}
    .fl-card.small .act {font-size: 32px} .fl-card.small .num {font-size: 22px} .fl-card.small .why {font-size: 15px}
    .fl-card.small .row {gap: 4px 16px} .fl-card.small .sub {font-size: 14px}
    .fl-find {font-size: 16px; line-height: 1.5; margin: 0 0 4px 0}
    .fl-take {font-size: 16px; color: #212529; margin: -6px 0 6px 0}
    .fl-tag {display: inline-block; border-radius: 4px; padding: 1px 7px; font-size: 13px; font-weight: 600;
             color: #fff; background: var(--c)}
    </style>""", unsafe_allow_html=True)
    st.title(title)
    if subtitle:
        st.markdown(f"<div style='font-size:17px;color:#495057;margin:-10px 0 8px 0'>{subtitle}</div>",
                    unsafe_allow_html=True)


def headline_card(h: dict, why: str, label: str = "Net value of exiting now", small: bool = False,
                  extra: str = "") -> None:
    """Action in large colored text, net $ and bps next to it, one-line why."""
    c = ACTION_COLORS.get(h["action"], INK)
    net = h["net_value_exit_now_usd"]
    st.markdown(
        f"<div class='fl-card{' small' if small else ''}' style='--c:{c}'>"
        f"<div class='lab'>{html.escape(label)}</div><div class='row'>"
        f"<div class='act'>{html.escape(action_label(h))}</div>"
        f"<div><div class='num'>{usd(net, signed=True)}</div>"
        f"<div class='sub'>{bps(h['net_value_exit_now_bps_book'])} bps of the {html.escape(h['bps_basis'])}</div></div>"
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
                      font={"size": 14, "color": INK}, showlegend=layout.pop("showlegend", False),
                      legend={"orientation": "h", "y": 1.0, "yanchor": "bottom", "x": 0}, plot_bgcolor="#fff",
                      paper_bgcolor="#fff",
                      **layout)
    fig.update_xaxes(showgrid=False, zeroline=False)
    fig.update_yaxes(showgrid=False, zeroline=False)
    return fig


def chart(fig: go.Figure) -> None:
    st.plotly_chart(fig, width="stretch", theme=None, config={"displayModeBar": False})
