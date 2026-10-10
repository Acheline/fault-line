import streamlit as st

st.title("⚡ Fault Line")
st.write("Fork it. Trace it. Break it.")
st.markdown(
    "Other tools guess the dependency graph and guess the losses. Fault Line reads them from the "
    "protocols' own code, executed on a fork of real state.\n\n"
    "- **Discover**: execute each position's value / exit / liquidation transactions on an anvil fork and "
    "trace them (callTracer + prestateTracer), then resolve proxies, admins, multisigs and timelocks.\n"
    "- **Break**: shock each critical node on the fork and re-execute exit and liquidation *(M2)*.\n"
    "- **Decide**: race other holders to the exit and output one number: net value of exiting now *(M3)*."
)
