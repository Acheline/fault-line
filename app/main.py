"""Fault Line UI.   streamlit run app/main.py"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402

st.set_page_config(page_title="Fault Line", page_icon="⚡", layout="wide")

nav = st.navigation([
    st.Page(ROOT / "app" / "views" / "graph.py", title="Dependency graph", icon="🕸️", default=True),
    st.Page(ROOT / "app" / "views" / "assumptions.py", title="Assumptions", icon="🎚️"),
    st.Page(ROOT / "app" / "views" / "base_rates.py", title="Base rates", icon="📊"),
    st.Page(ROOT / "app" / "views" / "about.py", title="About", icon="⚡"),
])
nav.run()
