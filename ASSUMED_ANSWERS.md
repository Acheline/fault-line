# Assumed answers to QUESTIONS.md (pending Belem confirmation)

Every value below is a team ASSUMPTION, not something Belem told us. In code, tag each one
`source: "assumed_answers.md (pending Belem confirmation)"`, show it in the Assumptions page with a
slider where numeric, and replace it as soon as Belem answers at office hours.

Guiding principle: Belem reports 0 security incidents, 0 counterparty defaults and 0 liquidations
over 71 months. That record implies a CONSERVATIVE manager: wide liquidation buffers, small share of
any venue, fast reaction. Every assumption below leans conservative for that reason.

---

## 1. Reference portfolio [books/belem_assumed_book.yaml]

**Real reference data:** the Belem / RockawayX curated vaults on
https://dune.com/rockawayxvault/rockawayx-dashboard (≈ $293.56M TVL, 33 vaults, 8 chains,
9 protocols, 2,434 holders). These are the setter's actual vaults, so they are measured data, not
assumptions. The 10-pocket mandate below is the ASSUMED part: how one fund mandate might combine
those vaults with other positions.

**Assumed mandate:** one stablecoin market-neutral mandate of **$50M** (about 12.5% of Belem's ~$400M AUM),
split into the brief's own structure: **10 pockets × 10% ($5M each)**. We use 10 × 10% because the
brief uses it; the code must accept any number of pockets and weights.

| # | Pocket | Chain | Why it is in the book |
|---|---|---|---|
| P1 | Pendle PT-sUSDe, held outright | Ethereum | The brief's worked example (hero #1, part a) |
| P2 | PT-sUSDe as collateral on Morpho Blue, borrowing USDC (loop) | Ethereum | Hero #1, part b: liquidation path |
| P3 | sUSDe (Ethena staked USDe) | Ethereum | Common yield leg; creates a hidden shared ancestor with P1/P2 |
| P4 | Morpho curated USDC vault (a large, established curator) | Ethereum | Lender-side vault, diversified |
| P5 | RockawayX USDC Yield vault deposit | Ethereum | Hero #2: the setter's own curated vault (Belem / RockawayX) |
| P6 | Aave v3 USDC supply | Ethereum | Blue-chip lending benchmark, low risk |
| P7 | sUSDS (Sky savings) | Ethereum | Different issuer and yield source |
| P8 | syrupUSDC (Maple) | Ethereum | Institutional credit exposure |
| P9 | Kamino USDC lending | Solana | Second chain, chain-concentration test |
| P10 | Hyperliquid HLP vault (USDC) | Hyperliquid | Brief scenario (b): vault deploying into a perp venue (hero #3) |

Claude Code must verify every protocol and address on-chain or via its official API before use, and
replace any pocket that no longer exists or is too small with the closest live equivalent, logging why.

**Position size cap:** size = min($5M, cap from section 4). Any amount that does not fit under the cap
is parked in P6 (Aave USDC) and the X-ray reports it as "capacity-constrained".

**PT + Morpho loop (P2):**
- Target LTV = **0.80 × LLTV** (e.g. 73% LTV on a 91.5% LLTV market).
- Deleverage trigger at **0.90 × LLTV**; emergency full unwind at **0.95 × LLTV**.
- Loop leverage derived from target LTV (about 3.7× gross at 73% LTV). Show it.
- Why: a manager with zero liquidations in 71 months keeps a large buffer.

**Intentional design:** P1, P2 and P3 all depend on Ethena/USDe. The book looks like 10 independent
pockets but is not. The Portfolio X-ray must find this on its own; do not hard-code it.

---

## 2. Incident families [Module 2 shock tags, Module 3 priors]

**Which families matter most (for ordering the demo, NOT for the probabilities):**
1. Market disruption (depegs, oracle/price dislocations, liquidity crunches): most frequent.
2. Technical failure (oracle staleness, misconfiguration, chain halt, venue outage).
3. Security incident (exploit, key compromise): rarest, most severe.
Probabilities still come from base rates (section 7), never from this ranking.

**Counting rules for Belem's KPIs:**
- `liquidations` = a protocol-enforced liquidation of our position only.
- A forced exit at a loss (we exit because a limit tripped) is NOT a liquidation; report it as
  `forced_exit` with its realized cost, so the KPI stays honest.
- A `near_miss` = health factor came within 5% of liquidation, or a shock simulation shows a
  liquidation would have happened within 1 hour without action. Report near-misses separately.
- `counterparty_defaults` = an issuer, custodian, borrower or venue fails to honour redemption/repayment.
- `security_incidents` = exploit or admin/key compromise on any node in our dependency graph.

**Benchmark incidents used for calibration and the time machine:**
USDe/Binance dislocation (10 Oct 2025), Stream Finance xUSD (Nov 2025), USDC/SVB (Mar 2023),
stETH discount (Jun 2022), Euler exploit (Mar 2023), Curve/Vyper (Jul 2023).
Claude Code must source the observed depth and duration of each from data, not from memory.

---

## 3. Risk aversion [Book.risk_aversion_lambda]

- **λ = 0.5** by default (slider 0 to 1). Rationale: halfway between risk-neutral and tail-only; a
  conservative manager weights tail loss meaningfully but still respects expected value.
  Show how the decision changes at λ = 0, 0.5, 1.
- **Hard loss budgets (override the optimizer):**
  - Pocket: if **VaR95 of the pocket > 20% of the pocket**, recommend at least REDUCE 50%,
    whatever the optimizer says.
  - Book: if **CVaR95 of a single incident > 100 bps of the book**, the recommendation is EXIT for
    the pockets driving it, ranked by loss avoided per $ of exit cost.
  - Both thresholds are sliders and appear in the UI when they bind ("hard budget hit").

---

## 4. Position sizes [Book.positions[].size_usd, exit trace sizes]

- Typical ticket: **$5M** per pocket (10% of the $50M mandate).
- Maximum share of any venue (whichever binds first):
  - ≤ **10%** of a Pendle pool's liquidity,
  - ≤ **10%** of a Morpho market's total supply,
  - ≤ **15%** of a curated vault's TVL,
  - ≤ **5%** of a perp venue vault's TVL (HLP).
- Exit traces are run at **0.25×, 0.5×, 1× and 2×** the position size to build the slippage curve.
  The 2× point answers "what if another holder our size exits first".

---

## 5. Exit-cost assumptions [Module 3 C_exit(x, t)]

- **Method today:** on-chain measured quotes only: Pendle router quote for PT, DEX aggregator quote
  for the next hop, plus gas. Measured on the fork at the position size.
- **OTC/block liquidity:** assume **none** in the base case (conservative). Optional toggle
  "OTC desk available": PT sold at a **1.5% discount** to fair value, settles in **24 h**.
  Off by default; show both if time allows.
- **Reaction time:** **15 minutes** from alert to first transaction (24/7 on-call); a full decision
  for a large unwind within **1 hour**.
- **Exit splitting:** up to **4 tranches over 6 hours**. The optimizer compares exit-now,
  tranches at {0, 15 min, 1 h, 6 h}, and stay.
- **Lender side (vaults, lending):** exit cost = loss accrued while locked by utilization, plus the
  probability-weighted bad debt socialized before we get out. Withdrawable now = vault idle +
  unborrowed liquidity along the withdraw queue, measured on the fork.

---

## 6. Pre-selection scorecard and monitoring [Module 6 watch mode]

**Scorecard items Fault Line fills in automatically per protocol/asset:**
oracle type and feed quality (sources, heartbeat, staleness, issuer-reported or not), admin and
timelock (who can change what, how fast), upgradeability, TVL and share of chain TVL, protocol age,
audit count (DefiLlama), exit liquidity at position size, issuer concentration.

**TVL concentration flag threshold:** **5%** of the chain's DeFi TVL (keep the current value).

**Watch-mode signals and thresholds:**

| Signal | Warn | Act (run shock + recompute headline) |
|---|---|---|
| Stablecoin/LST peg deviation (on-chain or CEX) | > 0.5% | > 2% |
| Oracle staleness | > 1.0× heartbeat | > 1.5× heartbeat |
| Oracle vs spot deviation | > 0.5% | > 1% |
| Pool depth drop (1 h) | > 20% | > 30% |
| Lending market utilization | > 92% | > 95% |
| Health factor of our loop | < 1.15 | < 1.08 |
| Vault / protocol TVL outflow (24 h) | > 10% | > 20% |
| Pending admin or timelock action on a node we depend on | any | any upgrade or parameter change touching our markets |

**Alert channel:** console + Streamlit banner by default; optional Telegram bot via a webhook URL
in `.env` (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`). Do not block on it.

---

## 7. Data access and base rates

- **RPC:** no paid access assumed. Keep Alchemy free tier + anvil for traces, Etherscan for event
  history (getLogs is capped at 10 blocks on Alchemy free), DefiLlama for TVL and hacks, protocol
  APIs (Pendle, Morpho, Kamino). No Dune API (vault list from books/belem_vaults.csv). Cache everything.
- **Base rates must be COMPUTED, not typed:**
  - Exploit probability per protocol-year from the DefiLlama hacks dataset, bucketed by protocol
    category, age and TVL; loss-given-exploit as a share of TVL from the same data.
  - Depeg frequency and depth for stablecoins/LSTs from historical daily prices (DefiLlama coins API
    or CoinGecko), counting episodes below 0.99 / 0.97 / 0.90 and their duration.
  - Oracle failure rates from the observed staleness/deviation history in Module 1.8.
- **Fallback only if the data fetch fails** (tag `placeholder_prior`, show a red badge in the UI):
  annual exploit probability 1% for blue-chip lending/AMM protocols and 3% for protocols under 2
  years old; annual probability of a >3% stablecoin depeg lasting over 24 h of 2% for fiat-backed,
  5% for synthetic/delta-neutral; loss-given-exploit 30% of exposure. These are deliberately rough
  and must be replaced by computed values before the demo.

---

## Machine-readable version (load into core/config or book.yaml)

```yaml
assumed_answers:
  source: "ASSUMED_ANSWERS.md (pending Belem confirmation)"
  mandate:
    aum_usd: 400_000_000
    mandate_usd: 50_000_000
    pockets: 10
    pocket_weight: 0.10
  loop:
    target_ltv_over_lltv: 0.80
    deleverage_trigger_over_lltv: 0.90
    emergency_unwind_over_lltv: 0.95
  risk:
    lambda: 0.5
    pocket_var95_hard_limit: 0.20        # share of pocket
    book_cvar95_single_incident_bps: 100
  sizing:
    ticket_usd: 5_000_000
    max_share_pendle_pool: 0.10
    max_share_morpho_market_supply: 0.10
    max_share_curated_vault_tvl: 0.15
    max_share_perp_vault_tvl: 0.05
    exit_trace_multiples: [0.25, 0.5, 1.0, 2.0]
  exit:
    otc_available: false
    otc_discount: 0.015
    otc_settlement_hours: 24
    reaction_minutes: 15
    tranche_times_minutes: [0, 15, 60, 360]
    max_tranches: 4
  kpi_rules:
    near_miss_hf_buffer: 0.05
    near_miss_horizon_minutes: 60
    forced_exit_counts_as_liquidation: false
  monitoring:
    tvl_concentration_flag: 0.05
    peg_warn: 0.005
    peg_act: 0.02
    oracle_stale_warn_x_heartbeat: 1.0
    oracle_stale_act_x_heartbeat: 1.5
    oracle_spot_dev_warn: 0.005
    oracle_spot_dev_act: 0.01
    pool_depth_drop_1h_warn: 0.20
    pool_depth_drop_1h_act: 0.30
    utilization_warn: 0.92
    utilization_act: 0.95
    loop_hf_warn: 1.15
    loop_hf_act: 1.08
    tvl_outflow_24h_warn: 0.10
    tvl_outflow_24h_act: 0.20
    alert_channels: [console, streamlit, telegram_optional]
  fallback_priors:   # placeholder_prior: replace with computed base rates
    exploit_annual_bluechip: 0.01
    exploit_annual_young_protocol: 0.03
    depeg_3pct_24h_annual_fiat_backed: 0.02
    depeg_3pct_24h_annual_synthetic: 0.05
    loss_given_exploit: 0.30
```
