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
    st.button("💥 Break it", disabled=True, help="Fork-and-break engine lands in M2")
