"""Interactive dependency-graph export (pyvis, vis.js inlined: works offline).

    python -m discovery.viz                      # data/graphs/hero1.json -> output/hero1_graph.html

Nodes are colored by the brief's 5 layers + the layers Fault Line found beyond them, sized by how many critical
paths (value / exit / liquidation) touch them; edges are labelled by type; hover shows provenance.
"""
from __future__ import annotations

import html
import json
import re
import sys
from pathlib import Path

from pyvis.network import Network

from core.fork import ROOT
from core.schemas import DependencyGraph, NodeType
from discovery.report import BEYOND, BRIEF_LAYERS

LAYER_COLORS = {
    BRIEF_LAYERS[0]: "#343a40",     # settlement chain
    BRIEF_LAYERS[1]: "#2f9e44",     # yield source & issuer
    BRIEF_LAYERS[2]: "#e8590c",     # oracle
    BRIEF_LAYERS[3]: "#1971c2",     # PT AMM
    BRIEF_LAYERS[4]: "#7048e8",     # lending market
    BEYOND["gov"]: "#c92a2a",
    BEYOND["feeds"]: "#f59f00",
    BEYOND["offchain"]: "#868e96",
    BEYOND["exit"]: "#74c0fc",
    BEYOND["code"]: "#ced4da",
}
POSITION_COLOR = "#000000"
EDGE_COLORS = {
    "prices": "#e8590c", "exit_route": "#1971c2", "liquidation_route": "#7048e8", "governs": "#c92a2a",
    "wraps": "#2f9e44", "backs": "#868e96", "issued_by": "#2b8a3e", "allocates_to": "#9c36b5",
    "delegates_to": "#adb5bd", "holds": "#000000", "uses_collateral": "#5f3dc4", "lends": "#5f3dc4",
    "references": "#ced4da",
}
FLAG_TAGS = {"fixed_schedule", "fixed_price", "issuer_reported"}
ETHERSCAN = "https://etherscan.io/address/"


def _prov_html(provs: list) -> str:
    rows = []
    for p in provs[:6]:
        bits = [f"<b>{html.escape(p.source)}</b>"]
        if p.block:
            bits.append(f"block {p.block}")
        if p.call:
            bits.append(f"call <code>{html.escape(p.call)}</code>")
        if p.detail:
            bits.append(html.escape(p.detail))
        if p.url:
            bits.append(f'<a href="{html.escape(p.url)}" target="_blank">{html.escape(p.url)}</a>')
        if p.confidence < 1:
            bits.append(f"confidence {p.confidence:.1f}")
        rows.append("<li>" + " · ".join(bits) + "</li>")
    more = f"<li>… +{len(provs) - 6} more</li>" if len(provs) > 6 else ""
    return f"<ul style='margin:4px 0 0 14px;padding:0'>{''.join(rows)}{more}</ul>" if rows else "<i>no provenance</i>"


def _node_title(n) -> str:
    addr = f'<a href="{ETHERSCAN}{n.address}" target="_blank">{n.address}</a>' if n.address else html.escape(n.id)
    paths = ", ".join(sorted(p.value for p in n.paths)) or "—"
    tags = ", ".join(sorted(n.tags)) or "—"
    extra = []
    for k in ("contract_name", "symbol", "description", "implementation", "proxy_admin", "threshold", "n_owners",
              "min_delay_s", "protocol"):
        if n.props.get(k) not in (None, ""):
            extra.append(f"{k}: {html.escape(str(n.props[k]))}")
    fq = n.props.get("feed_quality")
    if fq:
        extra.append(f"feed: {fq['provider']} / <b>{fq['kind']}</b>; who can change: "
                     f"{html.escape(fq['who_can_change']['summary'])}")
        if fq["flags"]:
            extra.append(f"<span style='color:#c92a2a'>flags: {html.escape(', '.join(fq['flags']))}</span>")
    return (f"<div style='max-width:460px;white-space:normal;font:12px sans-serif'>"
            f"<b style='font-size:13px'>{html.escape(n.label)}</b><br>"
            f"{n.type.value} · <i>{html.escape(n.props.get('brief_layer', ''))}</i><br>{addr}<br>"
            f"critical paths: <b>{paths}</b><br>tags: {html.escape(tags)}<br>"
            + "".join(f"{x}<br>" for x in extra)
            + f"<b>provenance</b>{_prov_html(n.provenance)}</div>")


def _edge_title(e, g: DependencyGraph) -> str:
    fn = e.props.get("functions") or ([e.props["getter"] + "()"] if e.props.get("getter") else [])
    roles = e.props.get("roles") or ([e.props["role"]] if e.props.get("role") else [])
    return (f"<div style='max-width:460px;white-space:normal;font:12px sans-serif'>"
            f"<b>{e.type.value}</b>{' · path ' + e.path.value if e.path else ''}<br>"
            f"{html.escape(g.nodes[e.src].label)} → {html.escape(g.nodes[e.dst].label)}<br>"
            + (f"functions: <code>{html.escape(', '.join(fn))}</code><br>" if fn else "")
            + (f"roles: {html.escape(', '.join(roles))}<br>" if roles else "")
            + (f"<span style='color:#c92a2a'>reverted: {html.escape(str(e.props['reverted']))}</span><br>"
               if e.props.get("reverted") else "")
            + f"<b>provenance</b>{_prov_html(e.provenance)}</div>")


def _legend(g: DependencyGraph) -> str:
    counts: dict[str, int] = {}
    for n in g.nodes.values():
        lay = n.props.get("brief_layer")
        if lay:
            counts[lay] = counts.get(lay, 0) + 1
    def row(layer, color):
        return (f"<div class='lg-row' data-layer='{html.escape(layer)}' title='click to show/hide'>"
                f"<span class='sw' style='background:{color}'></span>{html.escape(layer)} "
                f"<span class='ct'>{counts.get(layer, 0)}</span></div>")
    brief = "".join(row(l, LAYER_COLORS[l]) for l in BRIEF_LAYERS)
    beyond = "".join(row(l, LAYER_COLORS[l]) for l in BEYOND.values())
    edges = "".join(f"<div><span class='ln' style='background:{c}'></span>{t}</div>"
                    for t, c in EDGE_COLORS.items() if any(e.type.value == t for e in g.edges.values()))
    d = g.meta.get("depth", {})
    return f"""
<div id="fl-legend">
  <div class="lg-h">Fault Line · {html.escape(g.position_id)} · block {g.fork_block}</div>
  <div class="lg-sub">{len(g.nodes)} nodes · {len(g.edges)} edges · asset stack {len(d.get('asset_stack', [])) - 1} layers</div>
  <div class="lg-t">Brief's 5 layers</div>{brief}
  <div class="lg-t">Found beyond the brief</div>{beyond}
  <div class="lg-row-static"><span class="sw" style="background:{POSITION_COLOR}"></span>position</div>
  <div class="lg-t">Node size</div>
  <div class="lg-row-static"><span class="dot" style="width:8px;height:8px"></span>0 critical paths
    <span class="dot" style="width:12px;height:12px;margin-left:6px"></span>1
    <span class="dot" style="width:16px;height:16px;margin-left:6px"></span>2
    <span class="dot" style="width:20px;height:20px;margin-left:6px"></span>3</div>
  <div class="lg-row-static"><span class="sw" style="background:#fff;border:3px solid #c92a2a"></span>hardcoded / issuer-reported price</div>
  <div class="lg-t">Edges (dependent → dependency)</div><div class="lg-edges">{edges}</div>
  <div class="lg-t">dashed = off-chain disclosure</div>
  <div class="lg-foot">Click a layer to hide/show it · hover for provenance</div>
</div>
<style>
#fl-legend{{position:fixed;top:10px;left:10px;z-index:10;background:rgba(255,255,255,.95);border:1px solid #ddd;
  border-radius:8px;padding:10px 12px;font:12px/1.5 system-ui,sans-serif;max-width:330px;max-height:95vh;overflow:auto;
  box-shadow:0 2px 8px rgba(0,0,0,.12);color:#212529}}
#fl-legend .lg-h{{font-weight:700;font-size:13px}} #fl-legend .lg-sub{{color:#666;margin-bottom:4px}}
#fl-legend .lg-t{{font-weight:600;margin-top:8px;color:#495057}}
#fl-legend .lg-row{{cursor:pointer;user-select:none}} #fl-legend .lg-row.off{{opacity:.35;text-decoration:line-through}}
#fl-legend .sw{{display:inline-block;width:12px;height:12px;border-radius:50%;margin-right:6px;vertical-align:-1px}}
#fl-legend .dot{{display:inline-block;border-radius:50%;background:#888;vertical-align:middle;margin-right:4px}}
#fl-legend .ct{{color:#868e96}} #fl-legend .ln{{display:inline-block;width:18px;height:3px;margin-right:6px;vertical-align:3px}}
#fl-legend .lg-edges{{columns:2}} #fl-legend .lg-foot{{color:#868e96;margin-top:6px;font-size:11px}}
</style>"""


# runs inside pyvis' drawGraph(), right after `network` is created
_JS = """
                  // vis-network 9 renders string titles as text: turn our HTML tooltips into elements
                  function _el(s){ var d=document.createElement('div'); d.innerHTML=s; return d; }
                  nodes.update(nodes.get().filter(function(n){return typeof n.title==='string';})
                                .map(function(n){return {id:n.id, title:_el(n.title)};}));
                  edges.update(edges.get().filter(function(e){return typeof e.title==='string';})
                                .map(function(e){return {id:e.id, title:_el(e.title)};}));
                  network.once('stabilizationIterationsDone', function(){ network.setOptions({physics:false}); });
                  document.querySelectorAll('#fl-legend .lg-row').forEach(function(row){
                    row.addEventListener('click', function(){
                      row.classList.toggle('off');
                      var hide = row.classList.contains('off'), layer = row.dataset.layer;
                      nodes.update(nodes.get({filter:function(n){return n.layer===layer;}})
                                    .map(function(n){return {id:n.id, hidden:hide};}));
                    });
                  });
"""


def build_html(g: DependencyGraph, height: str = "900px") -> str:
    net = Network(height=height, width="100%", directed=True, cdn_resources="in_line", bgcolor="#ffffff")
    for n in g.nodes.values():
        layer = n.props.get("brief_layer", "")
        is_pos = n.type == NodeType.POSITION
        color = POSITION_COLOR if is_pos else LAYER_COLORS.get(layer, "#dee2e6")
        flagged = bool(n.tags & FLAG_TAGS)
        net.add_node(n.id, label=n.label[:34], title=_node_title(n), layer=layer, shape="dot",
                     size=40 if is_pos else 8 + 4 * len(n.paths),
                     color={"background": color, "border": "#c92a2a" if flagged else color,
                            "highlight": {"background": color, "border": "#000"}},
                     borderWidth=5 if flagged else 1,
                     font={"size": 16 if is_pos or n.paths else 11, "face": "system-ui"})
    for k, e in g.edges.items():
        disclosed = all(p.source == "disclosure" for p in e.provenance) and e.provenance
        net.add_edge(e.src, e.dst, id=k, title=_edge_title(e, g), label=e.type.value,
                     color=EDGE_COLORS.get(e.type.value, "#999"), dashes=bool(disclosed),
                     width=2.5 if e.path else 1, arrows="to",
                     font={"size": 8, "align": "middle", "color": "#495057", "strokeWidth": 2})
    net.set_options(json.dumps({
        "physics": {"solver": "forceAtlas2Based",
                    "forceAtlas2Based": {"gravitationalConstant": -80, "springLength": 120, "avoidOverlap": 0.4},
                    "stabilization": {"iterations": 400}},
        "interaction": {"hover": True, "tooltipDelay": 120, "navigationButtons": True},
        "edges": {"smooth": {"type": "continuous"}},
    }))
    out = net.generate_html()
    # pyvis pulls Bootstrap from a CDN for widgets we don't use: drop it so the file works offline
    out = re.sub(r"<link\s+href=\"https://cdn\.jsdelivr\.net/npm/bootstrap[^>]*/>", "", out)
    out = re.sub(r"<script\s+src=\"https://cdn\.jsdelivr\.net/npm/bootstrap[^>]*></script>", "", out)
    out = re.sub(r"<center>\s*<h1></h1>\s*</center>", "", out)
    marker = "network = new vis.Network(container, data, options);"
    assert marker in out, "pyvis template changed: cannot inject tooltip/legend script"
    out = out.replace(marker, marker + _JS, 1)
    out = out.replace("<body>", "<body>" + _legend(g), 1)
    return out.replace("<head>", "<head><title>Fault Line · dependency graph</title>", 1)


def load_graph(path: Path) -> DependencyGraph:
    return DependencyGraph.model_validate_json(path.read_text())


def export(src: Path = ROOT / "data" / "graphs" / "hero1.json",
           dst: Path = ROOT / "output" / "hero1_graph.html") -> Path:
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(build_html(load_graph(src)))
    return dst


if __name__ == "__main__":
    args = sys.argv[1:]
    p = export(*(Path(a) for a in args)) if args else export()
    print(f"→ {p}")
