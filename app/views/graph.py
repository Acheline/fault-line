"""Page 1: the discovered dependency graph of a position."""
from pathlib import Path

import pandas as pd
import streamlit as st

from core.fork import ROOT
from core.schemas import NodeType
from discovery.viz import build_html, load_graph

GRAPHS = ROOT / "data" / "graphs"


@st.cache_data(show_spinner="Rendering graph…")
def _render(path: str, mtime: float) -> str:
    return build_html(load_graph(Path(path)), height="860px")


st.title("🕸️ Dependency graph")
files = sorted(GRAPHS.glob("*.json"))
if not files:
    st.warning("No graph yet. Run `python -m discovery.hero1` (add `--offline` to replay from cache).")
    st.stop()

choice = st.selectbox("Position", files, format_func=lambda p: p.stem)
html = _render(str(choice), choice.stat().st_mtime)
g = load_graph(choice)
m = g.meta
depth = m.get("depth", {})

if choice.stem == "hero1" and (ROOT / "data" / "shocks" / "hero1.json").exists():
    from decision import hero1 as D1
    from risk import scenarios_hero1 as S1

    @st.cache_data(show_spinner="Monte Carlo on the fork-measured hero #1 shocks…")
    def _h1(scale, lam, horizon, incident, mtime):
        return D1.headline(scale=scale, lam=lam, horizon_days=horizon, incident=incident)
    with st.sidebar:
        st.markdown("**Hero #1 position**")
        scale = st.slider("Size × assumed book (P1 + P2)", 0.25, 4.0, 1.0, 0.25)
        lam1 = st.slider("Risk aversion λ ", 0.0, 1.0, 0.5, 0.05)
        hz1 = st.select_slider("Horizon (days) ", [7, 14, 30, 60, 90], 30)
    inc = st.session_state.get("h1_incident")
    h1 = _h1(scale, lam1, float(hz1), inc, (ROOT / "data" / "shocks" / "hero1.json").stat().st_mtime)
    col = {"STAY": "#2b8a3e", "REDUCE": "#e67700", "EXIT": "#c92a2a"}[h1["action"]]
    st.markdown(
        f"<div style='display:flex;gap:28px;align-items:baseline;flex-wrap:wrap'><div>"
        f"<div style='font-size:13px;opacity:.7'>Net value of exiting now{' · USDe observed −%.0f%%' % (inc * 100) if inc else ''}</div>"
        f"<div style='font-size:40px;font-weight:700'>{h1['net_value_exit_now_bps_book']:+.2f} bps</div>"
        f"<div style='font-size:13px;opacity:.7'>of the {h1['bps_basis']} (main) · {h1['net_value_exit_now_bps_aum']:+.3f} bps "
        f"of ~$400M AUM</div><div style='font-size:18px'>${h1['net_value_exit_now_usd']:+,.0f}</div></div>"
        f"<div style='font-size:36px;font-weight:800;color:{col}'>{h1['action']}"
        f"{' %.0f%%' % (h1['exit_fraction'] * 100) if h1['action'] == 'REDUCE' else ''}</div></div>", unsafe_allow_html=True)
    cf = h1["components_full_exit_now"]
    st.caption(f"Full exit now = loss avoided ${cf['loss_avoided_usd']:,.0f} − yield forgone ${cf['yield_forgone_usd']:,.0f} "
               f"(carry {h1['carry']['apy']:.2%}/yr: PT implied {h1['carry']['pt_implied_apy']:.2%}, borrow "
               f"{h1['carry']['borrow_apr']:.2%}, {h1['leverage']:.2f}x loop) − exit cost ${cf['exit_cost_usd']:,.0f} "
               "(executed Pendle + Kyber routes; negative = the market pays above the oracle's discount schedule)")
    for line in h1["reason"]:
        st.markdown(f"- {line}")
    with st.expander("💥 Break it: run a shock on the fork", expanded=bool(inc)):
        kind = st.radio("Shock", ["USDe depeg", "Morpho oracle mispricing", "Pendle LP withdrawal"], horizontal=True)
        d = S1.load()
        if kind == "USDe depeg":
            sev = st.select_slider("USDe move", S1.USDE_GRID, 0.05, format_func=lambda x: f"−{x:.0%}")
            rows = d["usde_depeg"]
        elif kind == "Morpho oracle mispricing":
            sev = st.select_slider("Oracle move", S1.ORACLE_GRID, 0.05, format_func=lambda x: f"−{x:.0%}")
            rows = d["oracle_shock"]
        else:
            sev = st.select_slider("LP supply removed", S1.LIQ_GRID, 0.5, format_func=lambda x: f"{x:.0%}")
            rows = d["pendle_liquidity"]
        if st.button("💥 Break it", type="primary"):
            from core.fork import Fork
            fk = Fork()
            sz = d["sizes"]
            if fk.offline:
                r = next(x for x in rows if abs(x["severity"] - sev) < 1e-9)
                st.info("Fork offline: showing the cached fork run for this size.")
            else:
                with st.spinner("Executing on the fork…"):
                    r = (S1.usde_depeg(fk, sev, sz) if kind == "USDe depeg" else S1.oracle_shock(fk, sev, sz)
                         if kind == "Morpho oracle mispricing" else S1.pendle_liquidity(fk, sev, sz, False))
            st.session_state["h1_last"] = (kind, r)
            if kind == "USDe depeg":
                st.session_state["h1_incident"] = sev
            st.rerun()
        if st.session_state.get("h1_last"):
            k2, r = st.session_state["h1_last"]
            st.markdown(f"**{k2}, measured on the fork**")
            if k2 == "USDe depeg":
                st.markdown(f"Frozen phase: oracle on its schedule, HF {r['frozen_phase']['hf']:.3f} (no liquidation). "
                            f"MetaOracle switch: {r['switch']['steps']} after {r['switch']['timelock_s'] / 3600:.0f} h → "
                            f"HF {r['after_switch']['hf']:.3f}, liquidated: **{r['after_switch']['liquidated']}**, "
                            f"penalty ${r['liquidation_penalty_usd']:,.0f}. P1 loss ${r['p1_loss_usd']:,.0f}, P2 loss "
                            f"${r['p2_loss_usd']:,.0f} → {r['loss_per_usd']:.2%} of the position.")
                st.caption("Lit path: PT-sUSDe → SY-sUSDe → sUSDe → USDe → MetaOracle (schedule) → backup PYLpOracle × USDe/USD")
            elif k2 == "Morpho oracle mispricing":
                st.markdown(f"HF {r['hf']:.3f}, liquidated: **{r['liquidated']}**, penalty ${r['liquidation_penalty_usd']:,.0f}.")
            else:
                st.markdown(f"{r['lp_burned_share']:.0%} of LP burned by {r['lps_impersonated']} impersonated LPs; "
                            f"extra AMM exit cost at 1×: {(r.get('extra_exit_cost') or 0):.3%}.")
            if st.button("Reset to calm"):
                st.session_state.pop("h1_last", None)
                st.session_state.pop("h1_incident", None)
                st.rerun()
    st.divider()

if choice.stem == "hero3" and (ROOT / "data" / "shocks" / "hero3.json").exists():
    from decision import hero3 as D3
    st.markdown("**Hero #3 · a vault routing capital into a perp exchange: Ethena sUSDe → Binance perps**")
    c3 = st.columns(2)
    lam3 = c3[0].slider("Risk aversion λ  ", 0.0, 1.0, 0.5, 0.05)
    halted = c3[1].toggle(f"Shock: {D3.VENUE} halts withdrawals (exit only via DEX)", False)
    h3 = D3.headline(lam=lam3, halted=halted)
    col = {"STAY": "#2b8a3e", "REDUCE": "#e67700", "EXIT": "#c92a2a"}[h3["action"]]
    st.markdown(f"<div style='display:flex;gap:28px;align-items:baseline'><div><div style='font-size:13px;opacity:.7'>"
                f"Net value of exiting now · ${h3['size_usd'] / 1e6:.0f}M sUSDe</div><div style='font-size:36px;font-weight:700'>"
                f"{h3['net_value_exit_now_bps_book']:+.2f} bps</div><div style='font-size:13px;opacity:.7'>of the "
                f"{h3['bps_basis']} · ${h3['net_value_exit_now_usd']:+,.0f}</div></div><div style='font-size:32px;"
                f"font-weight:800;color:{col}'>{h3['action']}</div></div>", unsafe_allow_html=True)
    for line in h3["reason"]:
        st.markdown(f"- {line}")
    et, cx = h3["ethena"], h3["cex"]
    st.dataframe(pd.DataFrame([
        {"shock": f"{D3.VENUE} freezes withdrawals", "family": "technical failure", "status": h3["label"],
         "effect": f"{et['venue_share']:.1%} of backing stuck; redemptions served from {et['unallocated_share']:.0%} "
                   "unallocated backing; exit only via DEX (toggle above)", "source": "Ethena API (collateral by exchange)"},
        {"shock": f"{D3.VENUE} loses assets (haircut)", "family": "security incident", "status": h3["label"],
         "effect": f"reaches sUSDe holders above a {h3['haircut_breakeven']:.1%} haircut; past incidents "
                   + ", ".join(f"{x['name']} {x['share']:.1%}" for x in cx["incidents"]),
         "source": f"DefiLlama hacks (CEX > $1B, {cx['venue_years']:.0f} venue-years) + Ethena reserve fund"}]),
        hide_index=True, width="stretch")
    ex = h3["exit"]
    st.caption(f"Exit: DEX ${ex['dex_now']['size_usd'] / 1e6:.0f}M {ex['dex_now']['cost']:.1%} ({ex['dex_now']['status']}); "
               f"unstake {h3['onchain']['cooldown_s'] / 3600:.0f} h then sell "
               + (f"{ex['unstake_then_sell']['cost']:.2%}" if ex['unstake_then_sell']['cost'] is not None else "n/a")
               + f" ({ex['unstake_then_sell']['status']}); other sizes: {ex['other_sizes']}. "
               f"On-chain reads at block {h3['onchain']['block']}: sUSDe.asset() = USDe, owner {h3['onchain']['owner']}.")
    st.divider()

st.caption(f"`{g.position_id}` · fork block **{g.fork_block}** · every node and edge carries the trace / "
           "storage read / disclosure it came from (hover in the graph).")
c = st.columns(5)
c[0].metric("Nodes", len(g.nodes))
c[1].metric("Edges", len(g.edges))
c[2].metric("Asset stack", f"{len(depth.get('asset_stack', [])) - 1} layers", delta="brief: 5", delta_color="off")
c[3].metric("Critical nodes", len(m.get("critical_nodes", [])), help="touched by ≥2 of value / exit / liquidation")
c[4].metric("Findings", len(m.get("findings", [])))

st.iframe(html, height=880)   # built by discovery.viz from our graph; on-chain strings are escaped
st.download_button("Download graph HTML", html, file_name=f"{g.position_id}_graph.html", mime="text/html")

left, right = st.columns([3, 2])
with left:
    st.subheader("Findings")
    for f in m.get("findings", []):
        st.markdown(f"- **{f['label']}** `{f['kind']}`: {f['why']}")
    if depth.get("asset_stack"):
        st.subheader("Deepest asset stack")
        st.code("\n → ".join(depth["asset_stack"]), language=None)
with right:
    st.subheader("Brief's 5 layers → found")
    st.dataframe(pd.DataFrame([{"layer": k, "nodes": len(v), "examples": ", ".join(v[:3])}
                               for k, v in m.get("brief_layers", {}).items()]),
                 hide_index=True, width="stretch")

st.subheader("Node inspector")
nodes = sorted((n for n in g.nodes.values() if n.type != NodeType.POSITION),
               key=lambda n: (-len(n.paths), n.label.lower()))
node = st.selectbox("Node", nodes, format_func=lambda n: f"{n.label} · {n.type.value} · "
                    f"{', '.join(sorted(p.value for p in n.paths)) or 'no critical path'}")
if node:
    a, b = st.columns([2, 3])
    with a:
        st.markdown(f"**{node.label}** · {node.type.value} · *{node.props.get('brief_layer', '')}*")
        if node.address:
            st.markdown(f"[{node.address}](https://etherscan.io/address/{node.address})")
        st.markdown(f"tags: `{', '.join(sorted(node.tags)) or '—'}`")
        st.json({k: v for k, v in node.props.items() if k != "brief_layer"}, expanded=False)
    with b:
        st.markdown("**Provenance**")
        st.dataframe(pd.DataFrame([p.model_dump() for p in node.provenance]), hide_index=True,
                     width="stretch")
        st.markdown("**Edges**")
        st.dataframe(pd.DataFrame(
            [{"dir": "→" if e.src == node.id else "←", "type": e.type.value,
              "other": g.nodes[e.dst if e.src == node.id else e.src].label,
              "path": e.path.value if e.path else "", "via": ", ".join(e.props.get("functions", []))
              or e.props.get("getter", "")}
             for e in g.edges.values() if node.id in (e.src, e.dst)]), hide_index=True, width="stretch")
    st.caption("Break it: see the panel at the top of the hero #1 page; hero #2 shocks are on the Vault view.")
