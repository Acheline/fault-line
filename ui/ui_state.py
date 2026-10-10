import streamlit as st


def init_state():

    if "position_size" not in st.session_state:
        st.session_state.position_size = 500000

    if "selected_shock" not in st.session_state:
        st.session_state.selected_shock = "USDe depeg"

    if "probability_pct" not in st.session_state:
        st.session_state.probability_pct = 20

    if "risk_aversion" not in st.session_state:
        st.session_state.risk_aversion = 0.30

    if "shock_active" not in st.session_state:
        st.session_state.shock_active = False