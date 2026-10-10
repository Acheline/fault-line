# Questions for Belem office hours

Each answer replaces a value tagged `assumption` in the code. Where it goes is shown in brackets.

## 1. Reference portfolio [books/*.yaml]
- Can you share one of "the portfolio structures we actually run" as a reference case? A redacted
  version is fine: position types, chains, rough weights, mandate (fund / managed account / curated vault).
- How many pockets is a typical mandate split into? Is 10 × 10% realistic?
- Do you run PT + Morpho loops (PT collateral, borrow stables)? If so, at what LTV relative to LLTV?

## 2. Incident families [Module 2 shock tags, Module 3 priors]
- Of the brief's three families (security incident, market disruption, technical failure), which have
  actually cost you money, and which do you lose sleep over?
- Your KPIs are security incidents, counterparty defaults and liquidations. How do you count a
  near-miss? Is a forced exit at a loss counted as a liquidation?
- Which past incidents do you use internally as benchmarks (USDe 10 Oct 2025, xUSD Nov 2025, SVB, stETH)?

## 3. Risk aversion [Book.risk_aversion_lambda]
- How do you trade expected loss against tail loss? Our rule is
  `E[L] + λ·(CVaR95 − E[L])`. Which λ matches your behaviour (0 = risk-neutral, 1 = act on the tail only)?
- Is there a hard loss budget per pocket or per book (bps) that forces an exit regardless?

## 4. Position sizes [Book.positions[].size_usd, exit trace sizes]
- Typical ticket per position, and maximum share of a pool or market you will hold
  (for example, never more than X% of a Pendle pool or Y% of a Morpho market's supply)?
- Typical size for a curated-vault deposit, relative to the vault's TVL?

## 5. Exit-cost assumptions [Module 3 C_exit(x, t)]
- How do you estimate exit cost today: quoted slippage, aggregator quote, OTC desk?
- Is OTC or block liquidity available to you (for example for PTs) that is not visible on-chain?
- What is your fastest realistic reaction time: alert to first transaction (minutes? hours)?
- Do you split exits over time? Over what horizon?

## 6. Pre-selection scorecard and monitoring [Module 6 watch mode]
- Which scorecard items would you want Fault Line to fill in automatically (oracle type, admin
  timelock, TVL concentration, audits)?
- Which real-time signals do you monitor today, and what thresholds trigger action?
- Where should alerts go (Telegram, Slack, PagerDuty)?

## 7. Data access
- Do you have paid RPC / archive access we could use? Alchemy free tier limits `eth_getLogs` to
  10 blocks, so we use Etherscan for event history.
- Any internal dataset of incidents / depegs / RWA impairments we may use for base rates?
