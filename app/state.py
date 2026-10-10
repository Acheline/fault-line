"""Cross-page UI state."""
import streamlit as st

RED_BADGE = ("<span style='background:#c92a2a;color:#fff;border-radius:4px;padding:1px 6px;"
             "font-size:12px;font-weight:600'>{}</span>")


def overrides() -> dict:
    """Slider overrides of ASSUMED_ANSWERS.md values, shared across pages: {"risk.lambda": 0.8}."""
    return st.session_state.setdefault("overrides", {})


def placeholder_badge(text: str = "placeholder_prior") -> str:
    return RED_BADGE.format(text)
