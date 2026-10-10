"""Cross-page UI state."""
from pathlib import Path

import streamlit as st

VIEWS = Path(__file__).resolve().parent / "views"
PAGES = {k: VIEWS / f"{k}.py" for k in ("overview", "vault", "deps", "xray", "assumptions")}

RED_BADGE = ("<span style='background:#c92a2a;color:#fff;border-radius:4px;padding:1px 6px;"
             "font-size:12px;font-weight:600'>{}</span>")

VAULT_DEFAULT_LAMBDA = 0.0      # the Belem vault page opens risk-neutral; the calm day then reads STAY (see implied λ)


def overrides() -> dict:
    """Slider overrides of ASSUMED_ANSWERS.md values, shared across pages: {"risk.lambda": 0.8}. Every headline()
    call passes this, so moving an Assumptions slider changes the other pages."""
    return st.session_state.setdefault("overrides", {})


def placeholder_badge(text: str = "placeholder_prior") -> str:
    return RED_BADGE.format(text)
