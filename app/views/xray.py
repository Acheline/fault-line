"""Portfolio X-ray: shared ancestors across pockets, found from their own graphs."""
import json

import pandas as pd
import streamlit as st

from core.book import load_book
from core.fork import ROOT

st.title("🩻 Portfolio X-ray")

BX = ROOT / "data" / "book_xray.json"
if BX.exists():
    bx = json.loads(BX.read_text())
    st.subheader(f"Belem / RockawayX vaults: {bx['headline']}")
    cv = bx["coverage"]
    st.caption(f"TVL coverage: {cv['n_resolved']} Morpho vaults resolved on-chain / Morpho API = "
               f"${cv['resolved_usd'] / 1e6:.1f}M ({cv['resolved_share']:.1%} of ${bx['book_usd'] / 1e6:.2f}M); "
               f"${cv['unresolved_usd'] / 1e6:.1f}M (Kamino, Upshift, Ember, Feather, Oku, Accountable, Midas, Lista) "
               "from the CSV only, labelled not resolved. Unresolved vaults with no stated issuer count as separate bets.")
    st.dataframe(pd.DataFrame([{"issuer / collateral": r["issuer"], "$": r["usd"], "% of book": r["share"],
                                "vaults": r["n_vaults"], "via": ", ".join(r["how"]), "tokens": ", ".join(r["tokens"]),
                                "vault names": ", ".join(r["vaults"])}
                               for r in bx["groups"] if r["n_vaults"] >= 2 or r["issuer"] in ("Tori Finance", "Huma", "OnRe", "Re Protocol")]),
                 hide_index=True, width="stretch",
                 column_config={"$": st.column_config.NumberColumn(format="dollar"),
                                "% of book": st.column_config.NumberColumn(format="percent")})
    st.divider()
path = ROOT / "data" / "xray.json"
if not path.exists():
    st.warning("Run `python -m discovery.xray` first.")
    st.stop()
x = json.loads(path.read_text())
book = load_book(ROOT / "books" / "belem_assumed_book.yaml")
st.caption(f"{book.name} · {book.owner} · source: {book.source}")
st.subheader(x["headline"])
c = st.columns(3)
c[0].metric("Pockets", x["n_pockets"])
c[1].metric("Bets", x["n_bets"])
c[2].metric("Effective independent bets", f"{x['effective_independent_bets']:.1f}")
st.caption(x["method"])

st.markdown("**Bets** (pockets that fail together)")
st.dataframe(pd.DataFrame([{"weight": f"{b['weight']:.1%}", "pockets": ", ".join(b["pockets"]),
                            "shared via": ", ".join(b["shared_ancestors"][:4])} for b in x["bets"]]),
             hide_index=True, width="stretch")

st.markdown("**Shared ancestors** (non-numeraire first)")
rows = [{"book share": round(s["book_share"], 4), "type": s["type"], "node": s["label"],
         "pockets": ", ".join(s["pockets"]), "numeraire": s["numeraire"]} for s in x["shared_ancestors"]]
df = pd.DataFrame(rows).sort_values(["numeraire", "book share"], ascending=[True, False])
st.dataframe(df, hide_index=True, width="stretch")

sel = st.selectbox("How does each pocket reach…", [s for s in x["shared_ancestors"] if not s["numeraire"]],
                   format_func=lambda s: f"{s['label']} ({', '.join(s['pockets'])})")
if sel:
    for p, hops in sel["how"].items():
        st.markdown(f"**{p}**: " + " → ".join(f"`{h['edge']}` {h['to']} *({'/'.join(h['sources'])})*" for h in hops))

st.markdown("**Shared exit liquidity** (pockets whose executed exits hit the same pools: they race each other)")
st.dataframe(pd.DataFrame(x["shared_exit_liquidity"])[["label", "pockets", "book_share"]] if x["shared_exit_liquidity"]
             else pd.DataFrame(), hide_index=True, width="stretch")
