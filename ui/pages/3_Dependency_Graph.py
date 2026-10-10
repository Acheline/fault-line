import json
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components
from pyvis.network import Network

from ui_state import init_state
from ui_style import (
    apply_global_style,
    hero,
    badge,
    metric_card,
    section_label,
)


# ============================================================
# PAGE SETUP
# ============================================================

st.set_page_config(
    page_title="Dependency Graph | FAULT LINE",
    page_icon="🕸️",
    layout="wide",
)

init_state()
apply_global_style()


# ============================================================
# DATA
# ============================================================

ENGINE_ROOT = Path.home() / "Desktop" / "fault-line"

GRAPH_FILE = ENGINE_ROOT / "data" / "graphs" / "hero1.json"


@st.cache_data
def load_json(path):
    if not path.exists():
        return {}

    with open(path, "r") as f:
        return json.load(f)


graph_data = load_json(GRAPH_FILE)


if not graph_data:
    st.error(
        "Hero #1 dependency graph not found.\n\n"
        "Expected: `~/Desktop/fault-line/data/graphs/hero1.json`"
    )
    st.stop()


# ============================================================
# NORMALIZE NODES
# ============================================================

raw_nodes = graph_data.get("nodes", {})

if isinstance(raw_nodes, dict):
    nodes = list(raw_nodes.values())
else:
    nodes = raw_nodes


raw_edges = graph_data.get("edges", [])

if isinstance(raw_edges, dict):
    edges = list(raw_edges.values())
else:
    edges = raw_edges


fork_block = graph_data.get("fork_block")


# ============================================================
# HELPERS
# ============================================================

def edge_source(edge):
    return (
        edge.get("source")
        or edge.get("src")
        or edge.get("from")
    )


def edge_target(edge):
    return (
        edge.get("target")
        or edge.get("dst")
        or edge.get("to")
    )


def edge_type(edge):
    return str(
        edge.get("type")
        or edge.get("relationship")
        or edge.get("edge_type")
        or ""
    )


def provenance_sources(node):
    result = []

    for item in node.get("provenance", []):
        if not isinstance(item, dict):
            continue

        source = item.get("source")

        if source and source not in result:
            result.append(source)

    return result


# ============================================================
# HERO
# ============================================================

hero(
    "HERO #1 — DEPENDENCY GRAPH",
    "See what PT-sUSDe actually depends on for value, exit and liquidation.",
    kicker="FAULT LINE · DISCOVERY ENGINE",
)

badge(
    "REAL DISCOVERED DEPENDENCIES",
    "real",
)


# ============================================================
# CRITICAL NODES
# ============================================================

critical_ids = set()

for node in nodes:
    if "critical" in node.get("tags", []):
        critical_ids.add(node.get("id"))


critical_ids.discard(None)


# ============================================================
# SNAPSHOT
# ============================================================

section_label("GRAPH SNAPSHOT")

c1, c2, c3, c4 = st.columns(4)

with c1:
    metric_card(
        "Fork Block",
        f"{fork_block:,}" if isinstance(fork_block, int) else "N/A",
        "Ethereum",
    )

with c2:
    metric_card(
        "Nodes",
        str(len(nodes)),
        "Discovered dependencies",
    )

with c3:
    metric_card(
        "Relationships",
        str(len(edges)),
        "Dependency edges",
    )

with c4:
    metric_card(
        "Critical",
        str(len(critical_ids)),
        "Value / exit / liquidation",
    )


# ============================================================
# WHAT CRITICAL MEANS
# ============================================================

section_label("WHAT DOES CRITICAL MEAN?")

c1, c2, c3 = st.columns(3)

with c1:
    metric_card(
        "VALUE",
        "Pricing Path",
        "Can change what the position is worth",
    )

with c2:
    metric_card(
        "EXIT",
        "Liquidity Path",
        "Touched when the position is unwound",
    )

with c3:
    metric_card(
        "LIQUIDATION",
        "Collateral Path",
        "Can determine whether Morpho liquidates",
    )


st.caption(
    "A dependency is critical only if it matters to this specific position's "
    "value, exit or liquidation path."
)


# ============================================================
# CONTROLS
# ============================================================

section_label("GRAPH CONTROLS")

c1, c2, c3 = st.columns([2, 2, 1])

with c1:
    view_mode = st.radio(
        "View",
        [
            "Presentation View",
            "Full Dependency Graph",
        ],
        horizontal=True,
    )

with c2:
    selected_path = st.selectbox(
        "Critical Path",
        [
            "All",
            "value",
            "exit",
            "liquidation",
        ],
    )

with c3:
    show_edge_labels = st.checkbox(
        "Edge labels",
        value=False,
    )


# ============================================================
# PRESENTATION VIEW FILTER
# ============================================================

all_node_ids = {
    node.get("id")
    for node in nodes
    if node.get("id")
}


if view_mode == "Full Dependency Graph":

    candidate_ids = set(all_node_ids)

else:

    candidate_ids = set(critical_ids)

    # Always show position
    for node in nodes:
        if node.get("type") == "POSITION":
            candidate_ids.add(node.get("id"))

    # Add immediate neighbours of critical nodes
    neighbour_ids = set()

    for edge in edges:
        src = edge_source(edge)
        dst = edge_target(edge)

        if src in critical_ids:
            neighbour_ids.add(dst)

        if dst in critical_ids:
            neighbour_ids.add(src)

    candidate_ids.update(neighbour_ids)


candidate_ids.discard(None)


# ============================================================
# PATH FILTER
# ============================================================

visible_nodes = []

for node in nodes:

    node_id = node.get("id")

    if node_id not in candidate_ids:
        continue

    if selected_path != "All":

        paths = node.get("paths", [])
        node_type = node.get("type", "")

        if (
            selected_path not in paths
            and node_type != "POSITION"
        ):
            continue

    visible_nodes.append(node)


visible_ids = {
    node.get("id")
    for node in visible_nodes
    if node.get("id")
}


visible_edges = []

for edge in edges:

    src = edge_source(edge)
    dst = edge_target(edge)

    if src in visible_ids and dst in visible_ids:
        visible_edges.append(edge)


# ============================================================
# VIEW STATUS
# ============================================================

section_label("CURRENT VIEW")

c1, c2, c3 = st.columns(3)

with c1:
    metric_card(
        "Visible Nodes",
        str(len(visible_nodes)),
        view_mode,
    )

with c2:
    metric_card(
        "Relationships",
        str(len(visible_edges)),
        selected_path,
    )

with c3:
    visible_critical = sum(
        1
        for node in visible_nodes
        if node.get("id") in critical_ids
    )

    metric_card(
        "Critical Visible",
        str(visible_critical),
        "Highlighted dependencies",
    )


if not visible_nodes:
    st.error("No nodes match this path.")
    st.stop()


# ============================================================
# NODE COLORS
# ============================================================

NODE_COLORS = {
    "POSITION": "#27d3ff",
    "ASSET": "#28d17c",
    "ORACLE": "#ff77b7",
    "LENDING_MARKET": "#a78bfa",
    "LIQUIDITY_VENUE": "#4aa8ff",
    "CHAIN": "#5f8cff",
    "ISSUER": "#ffad3b",
    "GOVERNANCE": "#d892ff",
    "OFFCHAIN": "#8ea0b4",
    "CONTRACT": "#657789",
    "VAULT": "#27bfa6",
}


def get_color(node):
    return NODE_COLORS.get(
        node.get("type", ""),
        "#657789",
    )


def get_size(node):

    if node.get("type") == "POSITION":
        return 42

    if node.get("id") in critical_ids:
        return 34

    return 22


# ============================================================
# GRAPH
# ============================================================

section_label("INTERACTIVE DEPENDENCY MAP")

net = Network(
    height="700px",
    width="100%",
    directed=True,
    bgcolor="#071018",
    font_color="#f4f7fb",
    cdn_resources="in_line",
)


# ============================================================
# ADD NODES
# ============================================================

for node in visible_nodes:

    node_id = node.get("id")

    if not node_id:
        continue

    label = str(
        node.get("label")
        or node_id
    )

    node_type = node.get(
        "type",
        "UNKNOWN",
    )

    paths = node.get(
        "paths",
        [],
    )

    sources = provenance_sources(node)

    props = node.get(
        "props",
        {},
    )

    tooltip = [
        f"<b>{label}</b>",
        f"Type: {node_type}",
    ]

    if node_id in critical_ids:
        tooltip.append(
            "<b>CRITICAL DEPENDENCY</b>"
        )

    if paths:
        tooltip.append(
            "Critical paths: "
            + ", ".join(paths)
        )

    if sources:
        tooltip.append(
            "Evidence: "
            + ", ".join(sources)
        )

    layer = props.get(
        "brief_layer"
    )

    if layer:
        tooltip.append(
            "Layer: "
            + str(layer)
        )

    address = node.get(
        "address"
    )

    if address:
        tooltip.append(
            "Address: "
            + str(address)
        )

    net.add_node(
        node_id,
        label=label,
        title="<br>".join(tooltip),
        color={
            "background": get_color(node),
            "border": (
                "#ffffff"
                if node_id in critical_ids
                else "#1d2d3c"
            ),
            "highlight": {
                "background": get_color(node),
                "border": "#27d3ff",
            },
        },
        size=get_size(node),
        borderWidth=(
            4
            if node_id in critical_ids
            else 1
        ),
        font={
            "size": (
                17
                if node_id in critical_ids
                else 13
            ),
            "color": "#f4f7fb",
            "face": "Inter",
        },
    )


# ============================================================
# ADD EDGES
# ============================================================

for edge in visible_edges:

    src = edge_source(edge)
    dst = edge_target(edge)

    if not src or not dst:
        continue

    relationship = edge_type(edge)

    kwargs = {
        "title": relationship,
        "width": 1.6,
        "color": {
            "color": "#40566b",
            "highlight": "#27d3ff",
            "hover": "#27d3ff",
        },
        "arrows": "to",
        "smooth": {
            "enabled": True,
            "type": "dynamic",
        },
    }

    if show_edge_labels:
        kwargs["label"] = relationship

        kwargs["font"] = {
            "color": "#8ea0b4",
            "size": 10,
            "align": "middle",
        }

    net.add_edge(
        src,
        dst,
        **kwargs,
    )


# ============================================================
# GRAPH PHYSICS
# ============================================================

net.repulsion(
    node_distance=250,
    central_gravity=0.08,
    spring_length=210,
    spring_strength=0.035,
    damping=0.12,
)


# ============================================================
# DISPLAY
# ============================================================

HTML_FILE = Path.home() / "Desktop" / "fault-line-ui" / "dependency_graph.html"

net.write_html(
    str(HTML_FILE),
    open_browser=False,
    notebook=False,
)

with open(
    HTML_FILE,
    "r",
    encoding="utf-8",
) as f:
    graph_html = f.read()


components.html(
    graph_html,
    height=720,
    scrolling=False,
)


# ============================================================
# LEGEND
# ============================================================

with st.expander("How to read the graph"):

    st.markdown(
        """
🔵 **Position** — the position being analyzed

🟢 **Asset** — token / economic asset

🟣 **Lending market** — Morpho dependency

🌸 **Oracle** — pricing dependency

🔷 **Liquidity venue** — route needed for exit

🟠 **Issuer** — issuer / yield-source dependency

⚪ **Off-chain** — custodians, CEXs and disclosed infrastructure

**Large nodes with white borders** — critical dependencies for this position
"""
    )


# ============================================================
# CRITICAL DEPENDENCIES
# ============================================================

section_label("CRITICAL DEPENDENCIES")

critical_visible = [
    node
    for node in visible_nodes
    if node.get("id") in critical_ids
]


if critical_visible:

    for node in critical_visible:

        label = node.get(
            "label",
            node.get("id"),
        )

        node_type = node.get(
            "type",
            "UNKNOWN",
        )

        paths = node.get(
            "paths",
            [],
        )

        sources = provenance_sources(node)

        with st.expander(label):

            c1, c2, c3 = st.columns(3)

            with c1:
                st.markdown("**Type**")
                st.write(node_type)

            with c2:
                st.markdown("**Critical paths**")
                st.write(
                    ", ".join(paths)
                    if paths
                    else "N/A"
                )

            with c3:
                st.markdown("**Evidence**")
                st.write(
                    ", ".join(sources)
                    if sources
                    else "N/A"
                )

            props = node.get(
                "props",
                {},
            )

            if props:
                layer = props.get(
                    "brief_layer"
                )

                if layer:
                    st.caption(
                        f"Brief layer: {layer}"
                    )


else:
    st.info(
        "No critical dependencies are visible under the current filter."
    )


# ============================================================
# PROVENANCE
# ============================================================

section_label("HOW WAS THIS DISCOVERED?")

p1, p2, p3, p4 = st.columns(4)

with p1:
    metric_card(
        "Trace",
        "Execution",
        "Which contracts were actually called",
    )

with p2:
    metric_card(
        "Storage",
        "Configuration",
        "Which addresses and parameters contracts store",
    )

with p3:
    metric_card(
        "On-chain Read",
        "State",
        "Direct contract reads at the pinned block",
    )

with p4:
    metric_card(
        "Disclosure",
        "Off-chain",
        "Documented infrastructure not directly visible on-chain",
    )


# ============================================================
# IMPORTANT ORACLE INSIGHT
# ============================================================

section_label("ORACLE BLIND SPOT")

st.warning(
    "The collateral pricing path does not necessarily execute every market "
    "component shown elsewhere in the ecosystem. In particular, some risks "
    "can exist economically without being immediately reflected in the "
    "primary Morpho oracle path."
)


st.markdown(
    """
This is why FAULT LINE separates:

**economic dependency**

from

**currently executed oracle dependency**.

A dependency can matter for the position even if it is not touched by every
price update.
"""
)


# ============================================================
# NAVIGATION
# ============================================================

section_label("NEXT")

c1, c2, c3 = st.columns(3)

with c1:
    st.page_link(
        "pages/2_Break_It.py",
        label="Break a Dependency →",
        icon="💥",
    )

with c2:
    st.page_link(
        "pages/4_Risk_Analysis.py",
        label="Measure the Risk →",
        icon="📉",
    )

with c3:
    st.page_link(
        "pages/6_Evidence.py",
        label="Inspect Evidence →",
        icon="🔎",
    )


# ============================================================
# SOURCE
# ============================================================

section_label("DATA SOURCE")

badge(
    "REAL DISCOVERY DATA",
    "real",
)

st.write(
    "The graph is loaded directly from the latest Hero #1 discovery output "
    "generated by the blockchain engine."
)

st.caption(
    "Fork block "
    + (
        f"{fork_block:,}"
        if isinstance(fork_block, int)
        else "N/A"
    )
)


st.divider()

st.caption(
    "FAULT LINE · Hero #1 Dependency Discovery"
)