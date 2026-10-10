# Questions for Belem office hours

Each answer replaces a value tagged `assumption` in the code. Where it goes is shown in brackets.

## 1. Reference portfolio [books/*.yaml]
- Can you share one of "the portfolio structures we actually run" as a reference case? A redacted
  version is fine: position types, chains, rough weights, mandate (fund / managed account / curated vault).
  - *Assumed answer:* one $50M stablecoin market-neutral mandate (P1–P10), see `books/belem_assumed_book.yaml`. → [ASSUMED_ANSWERS.md §1](ASSUMED_ANSWERS.md#1-reference-portfolio-booksbelem_assumed_bookyaml)
- How many pockets is a typical mandate split into? Is 10 × 10% realistic?
  - *Assumed answer:* yes, 10 × 10% ($5M each), but the code accepts any number of pockets and weights. → [ASSUMED_ANSWERS.md §1](ASSUMED_ANSWERS.md#1-reference-portfolio-booksbelem_assumed_bookyaml)
- Do you run PT + Morpho loops (PT collateral, borrow stables)? If so, at what LTV relative to LLTV?
  - *Assumed answer:* yes (P2); target LTV 0.80 × LLTV, deleverage at 0.90 × LLTV, emergency unwind at 0.95 × LLTV. → [ASSUMED_ANSWERS.md §1](ASSUMED_ANSWERS.md#1-reference-portfolio-booksbelem_assumed_bookyaml)

## 2. Incident families [Module 2 shock tags, Module 3 priors]
- Of the brief's three families (security incident, market disruption, technical failure), which have
  actually cost you money, and which do you lose sleep over?
  - *Assumed answer:* ranking market disruption > technical failure > security incident (demo order only; probabilities come from base rates). → [ASSUMED_ANSWERS.md §2](ASSUMED_ANSWERS.md#2-incident-families-module-2-shock-tags-module-3-priors)
- Your KPIs are security incidents, counterparty defaults and liquidations. How do you count a
  near-miss? Is a forced exit at a loss counted as a liquidation?
  - *Assumed answer:* near-miss = HF within 5% of liquidation, or a simulated liquidation within 1 h; a forced exit is reported as `forced_exit`, not as a liquidation. → [ASSUMED_ANSWERS.md §2](ASSUMED_ANSWERS.md#2-incident-families-module-2-shock-tags-module-3-priors)
- Which past incidents do you use internally as benchmarks (USDe 10 Oct 2025, xUSD Nov 2025, SVB, stETH)?
  - *Assumed answer:* USDe/Binance 10 Oct 2025, Stream xUSD Nov 2025, USDC/SVB Mar 2023, stETH Jun 2022, Euler Mar 2023, Curve/Vyper Jul 2023 (depth and duration sourced from data). → [ASSUMED_ANSWERS.md §2](ASSUMED_ANSWERS.md#2-incident-families-module-2-shock-tags-module-3-priors)

## 3. Risk aversion [Book.risk_aversion_lambda]
- How do you trade expected loss against tail loss? Our rule is
  `E[L] + λ·(CVaR95 − E[L])`. Which λ matches your behaviour (0 = risk-neutral, 1 = act on the tail only)?
  - *Assumed answer:* λ = 0.5 (slider 0–1; decisions shown at λ = 0, 0.5, 1). → [ASSUMED_ANSWERS.md §3](ASSUMED_ANSWERS.md#3-risk-aversion-bookrisk_aversion_lambda)
- Is there a hard loss budget per pocket or per book (bps) that forces an exit regardless?
  - *Assumed answer:* yes: pocket VaR95 > 20% of pocket → at least REDUCE 50%; single-incident CVaR95 > 100 bps of book → EXIT the driving pockets. → [ASSUMED_ANSWERS.md §3](ASSUMED_ANSWERS.md#3-risk-aversion-bookrisk_aversion_lambda)

## 4. Position sizes [Book.positions[].size_usd, exit trace sizes]
- Typical ticket per position, and maximum share of a pool or market you will hold
  (for example, never more than X% of a Pendle pool or Y% of a Morpho market's supply)?
  - *Assumed answer:* $5M ticket; ≤10% of a Pendle pool, ≤10% of a Morpho market's supply, ≤5% of a perp vault's TVL; excess parked in Aave USDC (P6). → [ASSUMED_ANSWERS.md §4](ASSUMED_ANSWERS.md#4-position-sizes-bookpositionssize_usd-exit-trace-sizes)
- Typical size for a curated-vault deposit, relative to the vault's TVL?
  - *Assumed answer:* ≤15% of the curated vault's TVL. → [ASSUMED_ANSWERS.md §4](ASSUMED_ANSWERS.md#4-position-sizes-bookpositionssize_usd-exit-trace-sizes)

## 5. Exit-cost assumptions [Module 3 C_exit(x, t)]
- How do you estimate exit cost today: quoted slippage, aggregator quote, OTC desk?
  - *Assumed answer:* on-chain measured quotes only (Pendle router + DEX aggregator + gas), at position size, on the fork. → [ASSUMED_ANSWERS.md §5](ASSUMED_ANSWERS.md#5-exit-cost-assumptions-module-3-c_exitx-t)
- Is OTC or block liquidity available to you (for example for PTs) that is not visible on-chain?
  - *Assumed answer:* none in the base case; optional toggle: OTC at a 1.5% discount, 24 h settlement. → [ASSUMED_ANSWERS.md §5](ASSUMED_ANSWERS.md#5-exit-cost-assumptions-module-3-c_exitx-t)
- What is your fastest realistic reaction time: alert to first transaction (minutes? hours)?
  - *Assumed answer:* 15 min alert → first transaction; full decision on a large unwind within 1 h. → [ASSUMED_ANSWERS.md §5](ASSUMED_ANSWERS.md#5-exit-cost-assumptions-module-3-c_exitx-t)
- Do you split exits over time? Over what horizon?
  - *Assumed answer:* up to 4 tranches over 6 h, at {0, 15 min, 1 h, 6 h}. → [ASSUMED_ANSWERS.md §5](ASSUMED_ANSWERS.md#5-exit-cost-assumptions-module-3-c_exitx-t)

## 6. Pre-selection scorecard and monitoring [Module 6 watch mode]
- Which scorecard items would you want Fault Line to fill in automatically (oracle type, admin
  timelock, TVL concentration, audits)?
  - *Assumed answer:* oracle type & feed quality, admin & timelock, upgradeability, TVL & share of chain TVL, age, audits, exit liquidity at size, issuer concentration. → [ASSUMED_ANSWERS.md §6](ASSUMED_ANSWERS.md#6-pre-selection-scorecard-and-monitoring-module-6-watch-mode)
- Which real-time signals do you monitor today, and what thresholds trigger action?
  - *Assumed answer:* peg, oracle staleness and deviation, pool depth, utilization, loop HF, TVL outflow, pending admin actions; warn/act thresholds in the section's table. → [ASSUMED_ANSWERS.md §6](ASSUMED_ANSWERS.md#6-pre-selection-scorecard-and-monitoring-module-6-watch-mode)
- Where should alerts go (Telegram, Slack, PagerDuty)?
  - *Assumed answer:* console + Streamlit banner; optional Telegram via `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID`. → [ASSUMED_ANSWERS.md §6](ASSUMED_ANSWERS.md#6-pre-selection-scorecard-and-monitoring-module-6-watch-mode)

## 7. Data access
- Do you have paid RPC / archive access we could use? Alchemy free tier limits `eth_getLogs` to
  10 blocks, so we use Etherscan for event history.
  - *Assumed answer:* no paid access: Alchemy free + anvil, Etherscan for events, DefiLlama, protocol APIs; Dune optional. → [ASSUMED_ANSWERS.md §7](ASSUMED_ANSWERS.md#7-data-access-and-base-rates)
- Any internal dataset of incidents / depegs / RWA impairments we may use for base rates?
  - *Assumed answer:* none: base rates are computed from DefiLlama hacks + historical prices; fallback priors are used only if a fetch fails (red `placeholder_prior` badge). → [ASSUMED_ANSWERS.md §7](ASSUMED_ANSWERS.md#7-data-access-and-base-rates)
