"""Book X-ray: shared issuers across the Belem / RockawayX vaults, and the assumed 10-pocket book in an expander."""
import json

import plotly.graph_objects as go
import streamlit as st

from app import ui
from core.book import load_book
from core.fork import ROOT

BX, PX = ROOT / "data" / "book_xray.json", ROOT / "data" / "xray.json"
ui.setup("🩻 Book X-ray", "Vaults that look different by name, grouped by the issuer their collateral really "
         "depends on.")
if not BX.exists():
    st.warning("Run `python -m discovery.book_xray` first.")
    st.stop()
bx = json.loads(BX.read_text())
groups = sorted(bx["groups"], key=lambda g: -g["usd"])
top, cv = groups[0], bx["coverage"]
st.markdown(f"<div style='font-size:28px;font-weight:700;margin:4px 0'>{bx['n_vaults']} vaults, "
            f"{bx['effective_bets']:.1f} independent bets; at least {ui.pct(top['share'])} depends on "
            f"{top['issuer']}</div>", unsafe_allow_html=True)
st.markdown(f"<div style='font-size:15px;color:#495057'>Coverage: {ui.pct(cv['resolved_share'])} of "
            f"{ui.usd(bx['book_usd'])} resolved on-chain / Morpho API ({cv['n_resolved']} Morpho vaults); the rest "
            "from the vault list (books/belem_vaults.csv). An unresolved vault with no stated issuer counts as its own "
            "bet, so the true concentration can only be higher.</div>", unsafe_allow_html=True)

multi = [g for g in groups if g["n_vaults"] >= 2]
ui.findings([f"<b>{g['issuer']}</b>: {ui.pct(g['share'])} of the book ({ui.usd(g['usd'])}) across {g['n_vaults']} vaults: "
             f"{', '.join(g['vaults'])}." for g in multi[:3]])

show = groups[:14]
fig = go.Figure()
buckets = [(1, "1 vault"), (2, "2 vaults"), (3, "3 vaults"), (4, "4+ vaults")]
for (n, name), color in zip(buckets, ui.BLUES):
    sel = [g for g in show if min(g["n_vaults"], 4) == n]
    if not sel:
        continue
    fig.add_bar(y=[g["issuer"] for g in sel], x=[g["usd"] for g in sel], orientation="h", name=name, marker_color=color,
                marker_line={"color": "#1864ab", "width": 1}, text=[f"{ui.usd(g['usd'])} · {ui.pct(g['share'])}"
                                                                     for g in sel],
                textposition="outside", cliponaxis=False,
                customdata=[", ".join(g["vaults"]) for g in sel], hovertemplate="%{y}<br>%{customdata}<extra></extra>")
fig.update_yaxes(categoryorder="array", categoryarray=[g["issuer"] for g in show][::-1])
fig.update_xaxes(visible=False, range=[0, top["usd"] * 1.45])
tori = next((g for g in show if g["issuer"].startswith("Tori")), None)
if tori:
    fig.add_annotation(y=tori["issuer"], x=tori["usd"] * 1.68, text=f"<b>{tori['n_vaults']} Belem vaults, one issuer</b>",
                       showarrow=False, xanchor="left", font={"size": 14, "color": ui.INK})
ui.chart(ui.clean(fig, f"{top['issuer']} sits behind {top['n_vaults']} vaults: the book is fewer bets than it looks",
                  520, showlegend=True, legend_title_text="shared by", barmode="overlay"))

with st.expander("Show details: every issuer group"):
    ui.table([{"issuer / collateral": g["issuer"], "$": g["usd"], "% of book": g["share"], "vaults": g["n_vaults"],
               "via": ", ".join(g["how"]), "tokens": ", ".join(g["tokens"]), "vault names": ", ".join(g["vaults"])}
              for g in groups], money=("$",), pcts=("% of book",))

if PX.exists():
    with st.expander("Show details: the assumed 10-pocket book (Belem-style mandate)"):
        x = json.loads(PX.read_text())
        book = load_book(ROOT / "books" / "belem_assumed_book.yaml")
        st.caption(f"{book.name} · {book.owner} · source: {book.source}")
        st.markdown(f"**{x['headline']}**")
        k = st.columns(3)
        k[0].metric("Pockets", x["n_pockets"])
        k[1].metric("Bets", x["n_bets"])
        k[2].metric("Effective independent bets", f"{x['effective_independent_bets']:.1f}")
        st.caption(x["method"])
        st.markdown("**Bets** (pockets that fail together)")
        ui.table([{"weight": b["weight"], "pockets": ", ".join(b["pockets"]),
                   "shared via": ", ".join(b["shared_ancestors"][:4])} for b in x["bets"]], pcts=("weight",))
        st.markdown("**Shared ancestors** (non-numeraire first)")
        sa = sorted(x["shared_ancestors"], key=lambda s: (s["numeraire"], -s["book_share"]))
        ui.table([{"book share": s["book_share"], "type": s["type"], "node": s["label"],
                   "pockets": ", ".join(s["pockets"]), "numeraire": s["numeraire"]} for s in sa], pcts=("book share",))
        sel = st.selectbox("How does each pocket reach…", [s for s in x["shared_ancestors"] if not s["numeraire"]],
                           format_func=lambda s: f"{s['label']} ({', '.join(s['pockets'])})")
        if sel:
            for p, hops in sel["how"].items():
                st.markdown(f"**{p}**: " + " → ".join(f"`{h['edge']}` {h['to']} *({'/'.join(h['sources'])})*"
                                                      for h in hops))
        st.markdown("**Shared exit liquidity** (pockets whose executed exits hit the same pools: they race each other)")
        if x["shared_exit_liquidity"]:
            ui.table([{k: s[k] for k in ("label", "pockets", "book_share")} for s in x["shared_exit_liquidity"]],
                     pcts=("book_share",))
        else:
            st.write("None found.")
