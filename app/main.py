"""Fault Line UI.   streamlit run app/main.py"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402

from app.state import PAGES  # noqa: E402

st.set_page_config(page_title="Fault Line", page_icon="⚡", layout="wide")

nav = st.navigation([
    st.Page(PAGES["overview"], title="Overview", icon="⚡", default=True),
    st.Page(PAGES["vault"], title="Belem vault", icon="🏦"),
    st.Page(PAGES["deps"], title="Dependencies", icon="🕸️"),
    st.Page(PAGES["xray"], title="Book X-ray", icon="🩻"),
    st.Page(PAGES["assumptions"], title="Assumptions & data", icon="🎚️"),
])
nav.run()
