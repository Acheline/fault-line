"""Dependencies: hero #1 (PT-sUSDe loop, the brief's 5-layer stack) and hero #3 (sUSDe -> Binance perps, a yield
token routing capital into an external venue). Collapsed graph by default, full graph and provenance in expanders."""
import plotly.graph_objects as go
import streamlit as st

from app import ui
from app.state import overrides
from core.config import cfg
from core.fork import ROOT
from core.schemas import NodeType
from discovery.report import BEYOND, BRIEF_LAYERS
from discovery.viz import LAYER_COLORS, build_html, collapse, load_graph

GRAPHS, SHOCKS = ROOT / "data" / "graphs", ROOT / "data" / "shocks"
POS = {"PT-sUSDe loop": "hero1", "sUSDe → Binance": "hero3"}

ui.setup("🕸️ Dependencies", "Read from the protocols' own code: each position's value, exit and liquidation calls are "
         "executed on a mainnet fork and traced.")
if "pos" in st.query_params:            # deep link from the Overview cards
    st.session_state["dep_pos"] = next((k for k, v in POS.items() if v == st.query_params["pos"]), "PT-sUSDe loop")
    del st.query_params["pos"]
st.session_state.setdefault("dep_pos", "PT-sUSDe loop")
choice = st.segmented_control("Position", list(POS), key="dep_pos") or "PT-sUSDe loop"
pid = POS[choice]
gpath = GRAPHS / f"{pid}.json"
if not gpath.exists() or not (SHOCKS / f"{pid}.json").exists():
    st.warning(f"No data for {choice} yet. Run `python -m discovery.{pid}` (add `--offline` to replay from cache).")
    st.stop()
g = load_graph(gpath)
ov = overrides()
ov_key = tuple(sorted(ov.items()))
MTIME = (SHOCKS / f"{pid}.json").stat().st_mtime


@st.cache_data(show_spinner="Rendering graph…")
def render(path: str, full: bool, mtime: float) -> str:
    gg = load_graph(ROOT / path)
    return build_html(gg, height="860px") if full else build_html(collapse(gg), height="540px", compact=True)


def graph_block() -> None:
    full = st.toggle("Show full graph", False, key=f"full_{pid}",
                     help="collapsed: one node per protocol / asset / oracle / venue; full: every traced contract")
    html = render(str(gpath.relative_to(ROOT)), full, gpath.stat().st_mtime)
    st.iframe(html, height=880 if full else 560)    # built by discovery.viz from our graph; on-chain strings escaped
    st.caption("Color = the brief's 5 layers, plus the layers found beyond them · red border = hardcoded or "
               "issuer-reported price · node size = number of critical paths (value / exit / liquidation) · hover for "
               "the trace or storage read each node came from.")


def layers_chart() -> None:
    bl = g.meta.get("brief_layers", {})
    if not bl:
        return
    order = BRIEF_LAYERS + list(BEYOND.values())
    rows = [(k, bl.get(k, [])) for k in order][::-1]
    short = [k.lstrip("+ ").split(":")[0].split(" (")[0] for k, _ in rows]
    fig = go.Figure(go.Bar(
        y=short, x=[len(v) for _, v in rows], orientation="h",
        marker_color=[LAYER_COLORS.get(k, ui.NEUTRAL) for k, _ in rows],
        text=[str(len(v)) for _, v in rows], textposition="outside", cliponaxis=False,
        customdata=[", ".join(v[:4]) for _, v in rows], hovertemplate="%{y}: %{x} nodes<br>%{customdata}<extra></extra>"))
    fig.update_xaxes(visible=False, range=[0, max(len(v) for _, v in rows) * 1.15])
    fig.add_hline(y=4.5, line={"color": ui.MUTED, "dash": "dot", "width": 1})
    n_found = sum(1 for _, v in rows if v)
    ui.chart(ui.clean(fig, f"5 layers in the brief, {n_found} found on the fork", 380))
    st.caption(f"Below the dotted line: the brief's 5 layers. Above it: what the trace found beyond them "
               f"({len(g.nodes)} nodes in all). Hover a bar for examples.")


def before_after(before: dict, after: dict, title: str) -> None:
    def box(lab, d, color):
        return (f"<div style='flex:1;border:1px solid #e9ecef;border-top:6px solid {color};border-radius:8px;"
                f"padding:10px 16px'><div class='lab' style='font-size:14px;color:#868e96'>{lab}</div>"
                + "".join(f"<div style='font-size:17px;margin-top:4px'>{k}: <b>{v}</b></div>" for k, v in d.items())
                + "</div>")
    st.markdown(f"<div style='font-size:17px;font-weight:600;margin-top:6px'>{title}</div>"
                f"<div style='display:flex;gap:16px;margin:6px 0 10px 0'>"
                f"{box('Before (calm)', before, ui.ACTION_COLORS['STAY'])}"
                f"{box('After, measured on the fork', after, ui.ALERT)}</div>", unsafe_allow_html=True)


# =============================================================================================== hero #1
if pid == "hero1":
    from decision import hero1 as D1
    from risk import scenarios_hero1 as S1

    @st.cache_data(show_spinner="Running 10,000 Monte Carlo paths on the fork-measured shocks…")
    def headline(scale, lam, horizon, incident, ovk, mtime):
        return D1.headline(scale=scale, lam=lam, horizon_days=horizon, incident=incident, overrides=dict(ovk))

    with st.sidebar:
        st.markdown("**PT-sUSDe position**")
        lam = st.slider("Risk appetite λ", 0.0, 1.0, float(cfg(ov)["risk"]["lambda"]), 0.05,
                        help="weight on the worst case: 0 = expected loss only, 1 = worst-case average (CVaR95)")
        scale = st.slider("Size × assumed book", 0.25, 4.0, 1.0, 0.25, help="held outright (P1) + Morpho loop (P2)")
        with st.expander("Advanced"):
            horizon = st.select_slider("Horizon (days)", [7, 14, 30, 60, 90], 30)
    inc = st.session_state.get("h1_incident")
    h = headline(scale, lam, float(horizon), inc, ov_key, MTIME)
    tl = (h["time_to_liquidation_s"] or 0) / 3600
    why = ((f"USDe observed −{inc:.0%}: the Morpho oracle ignores it for {tl:.0f} h, then the backup feed takes over. "
            if inc else "")
           + f"#1 risk: {h['driver']['label'].split('(')[0].strip()} "
           f"({(h['driver']['share_of_risk_adjusted_loss'] or 0):.0%} of risk-adjusted loss) on a "
           f"{ui.usd(h['size_usd'])} position, {h['leverage']:.1f}x loop.")
    ui.headline_card(h, why, label="Net value of exiting now" + (f" · USDe observed −{inc:.0%}" if inc else ""))

    fd = {f["kind"]: f for f in g.meta.get("findings", [])}
    tvl = [t for t in g.meta.get("tvl_concentration", []) if t.get("flag")]
    lines = []
    if "fixed_schedule_oracle" in fd:
        lines.append(f"<b>The lending oracle is a fixed schedule</b> ({fd['fixed_schedule_oracle']['label']}): it cannot "
                     "see a PT or USDe crash.")
    lines.append(f"<b>Liquidation waits {tl:.0f} h</b> behind the MetaOracle's challenge timelock"
                 + (f" (fork: liquidated at USDe −{h['liquidated_at_usde_depeg']:.0%})." if h["liquidated_at_usde_depeg"]
                    else "."))
    if tvl:
        lines.append("<b>Chain-level concentration</b>: " + ", ".join(
            f"{t['name']} {ui.pct(t['share_of_chain'])}" for t in tvl[:2]) + " of Ethereum DeFi TVL (DefiLlama).")
    ui.findings(lines)

    a, b = st.columns([3, 2])
    with a:
        graph_block()
    with b:
        layers_chart()
        if g.meta.get("depth", {}).get("asset_stack"):
            st.markdown("**Deepest asset stack**")
            st.code("\n → ".join(g.meta["depth"]["asset_stack"]), language=None)

    # ------------------------------------------------------------------------------------------- break it
    st.markdown("### 💥 Break it")
    st.markdown("Pick a size, press a shock: it runs on the fork (or replays the cached fork run when offline) and "
                "the headline above updates.")
    lvl = st.select_slider("Shock size", ["small", "medium", "large", "extreme"], "medium", key="h1_lvl")
    i = ["small", "medium", "large", "extreme"].index(lvl)
    sev = {"USDe depeg": S1.USDE_GRID[i], "Oracle mispricing": S1.ORACLE_GRID[i],
           "Pendle LPs pull out": S1.LIQ_GRID[0 if i < 2 else 1]}
    btn = st.columns(3)
    labels = {"USDe depeg": f"USDe depeg −{sev['USDe depeg']:.0%}",
              "Oracle mispricing": f"Morpho oracle −{sev['Oracle mispricing']:.0%}",
              "Pendle LPs pull out": f"Pendle LPs pull {sev['Pendle LPs pull out']:.0%} of liquidity"}
    clicked = next((k for k, col in zip(labels, btn) if col.button("💥 " + labels[k], width="stretch",
                                                                   type="primary")), None)
    if clicked:
        d = S1.load()
        rows = {"USDe depeg": d["usde_depeg"], "Oracle mispricing": d["oracle_shock"],
                "Pendle LPs pull out": d["pendle_liquidity"]}[clicked]
        from core.fork import Fork
        fk = Fork()
        if fk.offline:
            res, src = next(x for x in rows if abs(x["severity"] - sev[clicked]) < 1e-9), "cached fork run"
        else:
            with st.spinner("Executing on the fork…"):
                res = (S1.usde_depeg(fk, sev[clicked], d["sizes"]) if clicked == "USDe depeg" else
                       S1.oracle_shock(fk, sev[clicked], d["sizes"]) if clicked == "Oracle mispricing" else
                       S1.pendle_liquidity(fk, sev[clicked], d["sizes"], False))
                src = "live fork run"
        st.session_state["h1_last"] = (clicked, sev[clicked], res, src)
        if clicked == "USDe depeg":
            st.session_state["h1_incident"] = sev[clicked]
        st.rerun()
    if st.session_state.get("h1_last"):
        kind, s, res, src = st.session_state["h1_last"]
        sz = S1.load()["sizes"]
        hf0 = sz["loop"]["lltv"] / sz["loop"]["target_ltv"]
        before = {"health factor": f"{hf0:.2f}", "liquidated": "no", "loss": "$0"}
        pos = sz["p1_usd"] + sz["p2_equity_usd"]
        if kind == "USDe depeg":
            loss = res["p1_loss_usd"] + res["p2_loss_usd"]
            after = {"health factor": f"{res['frozen_phase']['hf']:.2f} for {res['switch']['timelock_s'] / 3600:.0f} h "
                                      f"(oracle on its schedule) → {res['after_switch']['hf']:.2f}",
                     "liquidated": "yes" if res["after_switch"]["liquidated"] else "no",
                     "loss": f"{ui.usd(loss)} ({ui.pct(loss / pos)} of the position)"}
        elif kind == "Oracle mispricing":
            after = {"health factor": f"{res['hf']:.2f}", "liquidated": "yes" if res["liquidated"] else "no",
                     "loss": f"{ui.usd(res['loss_per_usd'] * pos)} (penalty {ui.usd(res['liquidation_penalty_usd'])})"}
        else:
            after = {"health factor": f"{hf0:.2f} (unchanged)", "liquidated": "no",
                     "loss if you must exit": f"{ui.usd(res['loss_per_usd'] * pos)} (extra exit cost "
                                              f"{ui.pct(res.get('extra_exit_cost') or 0)})"}
        name = {"USDe depeg": f"USDe depeg −{s:.0%}", "Oracle mispricing": f"Morpho oracle −{s:.0%}",
                "Pendle LPs pull out": f"Pendle LPs pull {s:.0%} of liquidity"}[kind]
        before_after(before, after, f"{name} · {src} · measured on the {ui.usd(pos)} test position")
        if kind == "USDe depeg":
            st.caption("Lit path: PT-sUSDe → SY-sUSDe → sUSDe → USDe → MetaOracle (schedule) → backup PYLpOracle × "
                       "USDe/USD. The headline now conditions on the observed depeg.")
        if st.button("Reset to calm"):
            st.session_state.pop("h1_last", None)
            st.session_state.pop("h1_incident", None)
            st.rerun()

# =============================================================================================== hero #3
else:
    from decision import hero3 as D3

    with st.sidebar:
        st.markdown("**sUSDe position**")
        lam = st.slider("Risk appetite λ", 0.0, 1.0, float(cfg(ov)["risk"]["lambda"]), 0.05,
                        help="weight on the worst case: 0 = expected loss only, 1 = worst-case average (CVaR95)")
    halted = st.toggle(f"💥 Shock: {D3.VENUE} halts withdrawals (exit only via DEX)", False)
    h = D3.headline(lam=lam, halted=halted, overrides=ov)
    et, cx, ex = h["ethena"], h["cex"], h["exit"]
    why = (f"{ui.pct(et['venue_share'])} of sUSDe's backing sits on {D3.VENUE} perps; a {D3.VENUE} loss reaches "
           f"holders only above a {ui.pct(h['haircut_breakeven'])} haircut, and exiting {ui.usd(h['size_usd'])} on DEX "
           f"costs {ui.pct(ex['dex_now']['cost'])} today.")
    ui.headline_card(h, why, label=f"Net value of exiting now · {ui.usd(h['size_usd'])} sUSDe")
    top = cx["incidents"][0] if cx["incidents"] else {}
    ui.findings([
        f"<b>The venue is an off-chain node</b>: no trace can see it; its share of backing comes from Ethena's API "
        f"({ui.pct(et['venue_share'])} of {ui.usd(et['backing_usd'])}).",
        f"<b>Loss threshold</b>: the reserve fund ({ui.usd(et['reserve_fund_usd'])}) absorbs a {D3.VENUE} haircut up "
        f"to {ui.pct(h['haircut_breakeven'])}; the largest CEX incident in the data: {top.get('name')} "
        f"{ui.pct(top.get('share', 0))}.",
        f"<b>The exit is the risk</b>: sUSDe trades at par up to ~$1.25M on DEX; {ui.usd(h['size_usd'])} costs "
        f"{ui.pct(ex['dex_now']['cost'])} (executed on the fork)."])

    a, b = st.columns([3, 2])
    with a:
        graph_block()
    with b:
        lq = ex["dex_now"].get("live_quote_check") or {}
        pts = [(f"${float(k.rstrip('M')):g}M<br>live quote", v, ui.ACCENT) for k, v in sorted(
            (lq.get("cost_by_size") or {}).items(), key=lambda kv: float(kv[0].rstrip("M"))) if v is not None]
        pts.append((f"{ui.usd(ex['dex_now']['size_usd'])}<br>on the fork", ex["dex_now"]["cost"], ui.INK))
        if ex["unstake_then_sell"]["cost"] is not None:
            pts.append((f"unstake {h['onchain']['cooldown_s'] / 3600:.0f} h<br>then sell", ex["unstake_then_sell"]["cost"],
                        ui.NEUTRAL))
        fig = go.Figure(go.Bar(x=[p[0] for p in pts], y=[p[1] for p in pts], marker_color=[p[2] for p in pts],
                               text=[ui.pct(p[1]) for p in pts], textposition="outside", cliponaxis=False))
        fig.update_yaxes(tickformat=".0%", range=[0, max(p[1] for p in pts) * 1.25], title="exit cost")
        fig.update_xaxes(tickangle=0)
        ui.chart(ui.clean(fig, f"Par up to ~$1.25M, then a wall: {ui.usd(ex['dex_now']['size_usd'])} costs "
                               f"{ui.pct(ex['dex_now']['cost'])}", 340))
        st.markdown("**Two modelled shocks on the venue**")
        ui.table([{"shock": f"{D3.VENUE} freezes withdrawals", "family": "technical failure",
                   "effect": f"{ui.pct(et['venue_share'])} of backing stuck; exit only via DEX (toggle above)"},
                  {"shock": f"{D3.VENUE} loses assets", "family": "security incident",
                   "effect": f"reaches holders above a {ui.pct(h['haircut_breakeven'])} haircut"}])

    with st.expander("Show details: exit routes, sources, on-chain reads"):
        for line in h["reason"]:
            st.markdown(f"- {line}")
        st.markdown(f"Status: {h['label']}. Freeze: Ethena API (collateral by exchange). Haircut: DefiLlama hacks "
                    f"(CEX > $1B, {cx['venue_years']:.0f} venue-years) + Ethena reserve fund. Past incidents: "
                    + ", ".join(f"{x['name']} {ui.pct(x['share'])}" for x in cx["incidents"]) + ".")
        st.markdown(f"Exit: DEX {ui.usd(ex['dex_now']['size_usd'])} {ui.pct(ex['dex_now']['cost'])} "
                    f"({ex['dex_now']['status']}); unstake then sell "
                    + (ui.pct(ex["unstake_then_sell"]["cost"]) if ex["unstake_then_sell"]["cost"] is not None else "n/a")
                    + f" ({ex['unstake_then_sell']['status']}); other sizes: {ex['other_sizes']}."
                    + (f" Live quote check (no fork): {lq.get('verdict')}." if lq else ""))
        st.markdown(f"On-chain reads at block {h['onchain']['block']}: `sUSDe.asset()` = USDe, owner "
                    f"`{h['onchain']['owner']}`.")
        cf = h["components_full_exit_now"]
        st.markdown(f"Full exit now = loss avoided {ui.usd(cf['loss_avoided_usd'])} − yield given up "
                    f"{ui.usd(cf['yield_forgone_usd'])} − exit cost {ui.usd(cf['exit_cost_usd'])} = "
                    f"{ui.usd(cf['net_usd'], signed=True)}. Expected loss {ui.usd(h['loss_usd']['E[L]'])}, worst-case "
                    f"average (CVaR95) {ui.usd(h['loss_usd']['CVaR95'])}.")

# =============================================================================================== details (both)
if pid == "hero1":
    with st.expander("Show details: the numbers behind the headline"):
        be = h["breakeven"]
        k = st.columns(4)
        k[0].metric("Expected loss", ui.usd(h["loss_usd"]["E[L]"]))
        k[1].metric("Worst-case average (CVaR95)", ui.usd(h["loss_usd"]["CVaR95"]))
        k[2].metric("Breakeven belief", ui.pct(be["p_breakeven"]) if be["p_breakeven"] is not None else "n/a",
                    f"our estimate {ui.pct(be['p_estimate'])}", delta_color="off",
                    help=f"P({be['event']}) above which exiting now pays")
        k[3].metric("Time to liquidation", f"{tl:.0f} h", "MetaOracle challenge timelock", delta_color="off")
        cf = h["components_full_exit_now"]
        st.markdown(f"Full exit now = loss avoided {ui.usd(cf['loss_avoided_usd'])} − yield given up "
                    f"{ui.usd(cf['yield_forgone_usd'])} (carry {ui.pct(h['carry']['apy'])}/yr: PT implied "
                    f"{ui.pct(h['carry']['pt_implied_apy'])}, borrow {ui.pct(h['carry']['borrow_apr'])}, "
                    f"{h['leverage']:.2f}x loop) − exit cost {ui.usd(cf['exit_cost_usd'])} (executed Pendle + Kyber "
                    "routes; negative = the market pays above the oracle's discount schedule). Secondary: "
                    f"{h['net_value_exit_now_bps_aum']:+.3f} bps of ~$400M AUM.")
        for line in h["reason"]:
            st.markdown(f"- {line}")

with st.expander("Show details: graph metrics and findings"):
    m = g.meta
    k = st.columns(5)
    k[0].metric("Nodes", len(g.nodes))
    k[1].metric("Edges", len(g.edges))
    k[2].metric("Asset stack", f"{max(0, len(m.get('depth', {}).get('asset_stack', [])) - 1)} layers", "brief: 5",
                delta_color="off")
    k[3].metric("Critical nodes", len(m.get("critical_nodes", [])), help="touched by ≥2 of value / exit / liquidation")
    k[4].metric("Findings", len(m.get("findings", [])))
    st.caption(f"`{g.position_id}` · fork block **{g.fork_block}**")
    for f in m.get("findings", []):
        st.markdown(f"- **{f['label']}** `{f['kind']}`: {f['why']}")
    if m.get("brief_layers"):
        ui.table([{"layer": k, "nodes": len(v), "examples": ", ".join(v[:3])} for k, v in m["brief_layers"].items()])
    st.download_button("Download full graph HTML", render(str(gpath.relative_to(ROOT)), True, gpath.stat().st_mtime),
                       file_name=f"{g.position_id}_graph.html", mime="text/html")

with st.expander("Show details: node inspector and provenance"):
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
            st.dataframe([p.model_dump() for p in node.provenance], hide_index=True, width="stretch")
            st.markdown("**Edges**")
            st.dataframe(
                [{"dir": "→" if e.src == node.id else "←", "type": e.type.value,
                  "other": g.nodes[e.dst if e.src == node.id else e.src].label,
                  "path": e.path.value if e.path else "",
                  "via": ", ".join(e.props.get("functions", [])) or e.props.get("getter", "")}
                 for e in g.edges.values() if node.id in (e.src, e.dst)], hide_index=True, width="stretch")
