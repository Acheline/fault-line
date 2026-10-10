"""Overview: the three headline numbers and where each of the brief's four scenarios is shown."""
import json

import streamlit as st

from app import ui
from app.state import PAGES, VAULT_DEFAULT_LAMBDA, overrides
from core.config import cfg
from core.fork import ROOT

ui.setup("⚡ Fault Line", "Fork it. Trace it. Break it. Then: stay or get out.")
st.markdown("<div style='font-size:17px;margin-bottom:8px'>Other tools guess the dependency graph and guess the losses. "
            "Fault Line reads them from the protocols' own code, executed on a fork of real Ethereum state, and turns "
            "them into <b>one number</b> per position: the net value of exiting now.</div>", unsafe_allow_html=True)

ov = overrides()
ov_key = tuple(sorted(ov.items()))
c = cfg(ov)
G, S = ROOT / "data" / "graphs", ROOT / "data" / "shocks"


@st.cache_data(show_spinner="Computing the three headlines…")
def headlines(ovk, mtimes):
    o, out = dict(ovk), {}
    if (S / "hero2.json").exists():
        from decision import hero2 as D2
        out["hero2"] = D2.headline(lam=VAULT_DEFAULT_LAMBDA, with_tornado=False, overrides=o)
    if (S / "hero1.json").exists():
        from decision import hero1 as D1
        out["hero1"] = D1.headline(with_tornado=False, overrides=o)
    if (S / "hero3.json").exists():
        from decision import hero3 as D3
        out["hero3"] = D3.headline(overrides=o)
    return out


hl = headlines(ov_key, tuple((S / f"hero{i}.json").stat().st_mtime if (S / f"hero{i}.json").exists() else 0
                             for i in (1, 2, 3)))
cards = [
    ("hero2", "🏦 Belem vault", "RockawayX USDC Yield · lender side", PAGES["vault"], None,
     lambda h: f"Calm day at λ = {h['lambda']:.0f}: expected loss {ui.usd(h['loss_usd']['E[L]'])} vs "
               f"{ui.usd(h['components_full_exit_now']['yield_forgone_usd'])} of yield over {h['horizon_days']:.0f} days."),
    ("hero1", "🕸️ PT-sUSDe loop", "Pendle PT on Morpho · the brief's 5-layer stack", PAGES["deps"], {"pos": "hero1"},
     lambda h: f"#1 risk: {h['driver']['label'].split('(')[0].strip()}; liquidation waits "
               f"{(h['time_to_liquidation_s'] or 0) / 3600:.0f} h behind the oracle's timelock."),
    ("hero3", "🌐 sUSDe → Binance", "yield token routing into a perp venue", PAGES["deps"], {"pos": "hero3"},
     lambda h: f"{ui.pct(h['ethena']['venue_share'])} of backing on {h['ethena'].get('venue', 'Binance')} perps; "
               f"exiting {ui.usd(h['size_usd'])} on DEX costs {ui.pct(h['exit']['dex_now']['cost'])}."),
]
cols = st.columns(3)
for col, (key, title, sub, page, qp, why) in zip(cols, cards):
    with col:
        st.markdown(f"<div style='font-size:20px;font-weight:700'>{title}</div>"
                    f"<div style='font-size:15px;color:var(--muted)'>{sub}</div>", unsafe_allow_html=True)
        if key in hl:
            ui.headline_card(hl[key], why(hl[key]), small=True)
        else:
            st.info("No cached data yet.")
        st.page_link(page, label="Open →", query_params=qp)

# ------------------------------------------------------------------------------------------- brief scenarios
st.markdown("### The brief's four scenarios, and where each one is shown")
rows = []
if (G / "hero1.json").exists():
    m1 = json.loads((G / "hero1.json").read_text())["meta"]
    bl = m1.get("brief_layers", {})
    rows.append(("a", "Pendle PT 5-layer stack",
                 f"PT-sUSDe → SY → sUSDe → USDe, priced by a schedule oracle, looped on Morpho: {m1.get('n_nodes')} "
                 f"nodes traced, {sum(1 for v in bl.values() if v)} layers vs the brief's 5.",
                 PAGES["deps"], {"pos": "hero1"}, "PT-sUSDe loop →"))
if "hero3" in hl:
    rows.append(("b", "Vault routing into a perp venue",
                 f"Ethena sUSDe: {ui.pct(hl['hero3']['ethena']['venue_share'])} of backing on Binance perps, an "
                 "off-chain venue node with two modelled shocks (freeze, haircut).",
                 PAGES["deps"], {"pos": "hero3"}, "sUSDe → Binance →"))
if (G / "hero1.json").exists():
    tvl = [t for t in m1.get("tvl_concentration", []) if t.get("flag")]
    rows.append(("c", "Protocol concentrating a chain's TVL",
                 (", ".join(f"{t['name']} {ui.pct(t['share_of_chain'])}" for t in tvl[:2]) + " of Ethereum DeFi TVL "
                  "(DefiLlama): flagged as chain-level liquidity events.") if tvl else "TVL share per protocol node.",
                 PAGES["deps"], {"pos": "hero1"}, "Dependencies →"))
if (G / "hero2.json").exists():
    m2 = json.loads((G / "hero2.json").read_text())["meta"]
    basis = m2["oracle_quality"].get("per_market", {})
    stuck = [x for x in m2["q1"]["markets"]
             if basis.get(x["collateral_symbol"], {}).get("price_basis") == "issuer_reported"]
    rows.append(("d", "Asset priced by a single feed",
                 f"{ui.pct(sum(x['allocation_pct'] for x in stuck))} of the Belem vault is lent against collateral "
                 f"priced by one issuer-reported feed each ({', '.join(x['collateral_symbol'] for x in stuck)}).",
                 PAGES["vault"], None, "Belem vault, Q1 →"))
for letter, name, line, page, qp, where in rows:
    a, b = st.columns([5, 1.4])
    a.markdown(f"<div style='font-size:16px;margin-top:6px'><b>({letter}) {name}</b>: {line}</div>",
               unsafe_allow_html=True)
    with b:
        st.page_link(page, label=where, query_params=qp)

with st.expander("How it works"):
    st.markdown(
        "- **Discover**: execute each position's value / exit / liquidation transactions on an anvil fork and trace "
        "them (callTracer + prestateTracer), then resolve proxies, admins, multisigs and timelocks.\n"
        "- **Break**: shock each critical node on the fork (oracle, depeg, liquidity, NAV, utilization, governance) "
        "and re-execute the exit and the liquidation.\n"
        "- **Decide**: Monte Carlo on base rates computed from data, race the other holders to the exit, and output "
        "one number: net value of exiting now = risk-adjusted loss avoided − yield given up − measured exit cost.\n\n"
        f"bps are of the assumed {ui.usd(c['mandate']['mandate_usd'])} mandate (Assumptions §1). Everything runs from "
        "the cached fork results, so the demo works offline.")
