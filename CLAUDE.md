# MISSION
We are competing in Belem Capital's "DeFi Risk Dependency Challenge" (EPFL Hackathon 2026).
Judging: dependency discovery 30%, defensible impact estimation 30%, stay/exit decision
usefulness 25%, working demo on real data 15%. Belem: ~$400M market-neutral yield book
(stablecoin/ETH/BTC/SOL) run through a fund, managed accounts and CURATED VAULTS; Pendle PTs,
lending loops, vaults routing into perp venues.

You are our lead engineer and DeFi risk quant. Build "FAULT LINE": a system that discovers a
position's dependencies by EXECUTING its critical transactions on a mainnet fork, measures
impact by BREAKING those dependencies on the fork, and recommends STAY / REDUCE / EXIT by
modelling the race to exit against other holders.

Core thesis to keep in every design choice: "Other tools guess the dependency graph and guess
the losses. We read them from the protocols' own code, executed on a fork of real state."

# WHAT THE BRIEF ASKS, VERBATIM INTENT (re-read before every milestone)
- Tagline: turn the dependency web into ONE NUMBER a portfolio manager can act on: stay, or get out.
  → Every position and the whole book get a single HEADLINE NUMBER: "Net value of exiting now",
  in bps of the book and in $ = (risk-adjusted expected loss avoided) − (measured exit cost).
  Positive = exit, negative = stay. Everything else in the UI explains that number.
- The hard part "is not noticing the incident. It is working out what it does to your book, and
  how fast." → every result carries time-to-impact, and the decision is time-dependent.
- Incident families named in the brief: security incident, market disruption, technical failure.
  Every shock in Module 2 is tagged with one of these three families. Belem's own track-record KPIs
  are "security incidents, counterparty defaults, liquidations": report results under those labels.
- Scenarios named in the brief that MUST each be demonstrable:
  (a) the Pendle PT 5-layer stack (hero #1),
  (b) a vault routing capital into an external venue, e.g. a perp exchange,
  (c) a protocol concentrating a large share of a chain's TVL,
  (d) an asset priced by a single feed.
- The brief's 10-pockets × 10% / 11% slippage example is a built-in test case (Module 3).
- Belem deploys only on protocols that clear a pre-selection scorecard and monitors every position
  in real time → Fault Line must also run in WATCH mode (see Module 6).
- Belem offers mentoring, office hours and "the portfolio structures we actually run as reference
  cases" → keep a `book.yaml` input format so we can load Belem's real reference portfolio the
  moment mentors share it. List the questions to ask them at office hours in QUESTIONS.md.
- Ecosystems allowed: Solana, EVM chains, newer settlement layers (Canton, Tempo). We go deep on
  Ethereum (+ Solana stretch); the README states how the method extends to other settlement layers.
- "Not a slide deck of an architecture": it must run on real data and produce an output a manager
  could act on.

Constraints: [N] people, [X] hours left. Keys: [archive RPC: Alchemy free tier works; anvil
does the tracing locally], [Etherscan], [Helius for Solana, optional]. No Dune API key.
Stack: Python + Foundry (anvil/cast) + web3.py + NetworkX + Streamlit. One command runs the demo.

Environment already verified: anvil fork running on 127.0.0.1:8545, debug_traceCall works with
BOTH callTracer and prestateTracer on anvil, anvil_setBalance works. Keys are in .env.

# REFERENCE BOOK: THE CHALLENGE SETTER'S OWN CURATED VAULTS (real data to build on)
Dashboard: https://dune.com/rockawayxvault/rockawayx-dashboard
The team confirms RockawayX and Belem are the same group: these vaults ARE the challenge setter's
curated-vault book ("the portfolio structures we actually run"). In the UI and README, call it
"Belem / RockawayX vaults". This is the most important real data in the project.

VAULT REGISTRY: books/belem_vaults.csv (exported from the dashboard; loaded by core/vaults.py): 25 vaults with
TVL, $293.63M, matching the dashboard's $293.56M (the other 8 of the 33 listed vaults are empty).
Dashboard headline KPIs (screenshot from the team): total TVL ≈ $293.56M, 2,434 unique holders, 33 active vaults,
average deposit per holder ≈ $120.6k, 8 chains (incl. Ethereum, Solana, Plume, Etherlink, 0G),
9 protocols hosting vaults (incl. Morpho, Kamino, Midas).

What RockawayX has published about this book (mid-2026 snapshot, from rockawayx.com/insights;
MUST be re-verified live before use, numbers and allocations change):
- Morpho (Ethereum): four active vaults, curator page app.morpho.org/curator/rockawayx.
  * "Figure USDC Main" vault: 0xd65d6E8dbC3Cd3D12418199E6f4014dB3aaa0097, reported as the sole
    lender in the PRIME/USDC market
    0x755f954513d31d5f24aaf3d0cdc5e913a28383f8ea8ff85be9ffffa7371fb64d (utilization reported ~93%).
  * Also announced: USDC Prime (conservative) and wETH (rxWETH; collateral wstETH, weETH, WBTC...).
- Kamino (Solana): "RockawayX RWA USDC" vault, allocating to three RWA-collateral reserves:
  OnRe (ONyc, reinsurance), Prime (PRIME by Hastra/Figure, HELOC warehouse), Huma (PST, PayFi).
  Reported as heavily concentrated in the OnRe market (~74% of deposits) at that date.
- Also active on Upshift, Feather, Ember, Lista; a Pareto credit facility; Midas strategies
  (mROX, mMEV). Out of scope unless time allows.
- Their PUBLISHED risk framework: 4 layers (strategy, asset, protocol, chain) rated AA→D, final
  rating = weakest layer; AA markets max 15% of a vault; concentration caps: single protocol 25%,
  single oracle 40%, correlated assets 40%, single chain 60%.

Data access for this book (in order of preference):
1. On-chain reads on the fork (vault contracts, Morpho Blue, oracles): the source of truth.
2. Morpho GraphQL API (https://api.morpho.org/graphql) for vault allocations, caps, depositors,
   market state; Kamino public API for vault/reserve allocations.
3. books/belem_vaults.csv for the vault list and dashboard TVL snapshot. No Dune API is used.
   Cache every response.

# HERO POSITIONS (build #1 end-to-end before anything else)
1. Pendle PT-sUSDe on Ethereum: held outright, AND posted as collateral on a Morpho Blue market,
   borrowing USDC. Mirrors the brief's 5-layer worked example. Look up and verify on-chain the
   current addresses (PT, Pendle market, SY, Morpho market id, oracle). Pick a PT that is liquid
   today, or the most recent liquid maturity.
2. HERO #2: RockawayX USDC Yield vault (Morpho, Ethereum, ~$18.5M). The setter's own vault.
   Scenario: a depositor puts USDC into a vault that allocates it to lending markets. Fault Line
   must answer THREE questions, each with measured numbers and a block number:
   Q1. WHERE DOES THE MONEY GO? Verify on-chain that RockawayX curates it (owner/curator/
       guardian/allocators, timelock). List every market in the supply and withdraw queues with
       allocation $ and %, supply cap, collateral token, LLTV, oracle (and what feeds it: market
       price, exchange rate, or issuer-reported NAV), IRM, and the collateral's issuer and
       off-chain originator where relevant. Group exposure by collateral, issuer, oracle and
       protocol.
   Q2. CAN BORROWERS REPAY? Per market: borrower health-factor distribution (largest borrowers
       first), how close they are to LLTV, how liquid the collateral is at liquidation size
       (measured exit quotes on the fork), and on-fork shocks (collateral price/NAV down, oracle
       frozen, redemption gate) re-running liquidate() to measure what is recovered and what
       becomes BAD DEBT socialized to vault depositors (loss per vault share).
   Q3. CAN DEPOSITORS WITHDRAW? Withdrawable now = vault idle + unborrowed liquidity along the
       withdraw queue (measured by simulating redeem() on the fork as the top depositors,
       impersonated). Utilization per market, depositor concentration (top holders of vault
       shares), and a run simulation: depositor rank vs % recovered and time to full exit.
   Previous candidate "Figure USDC Main" (0xd65d…0097) now holds ~$11: keep only as a footnote
   (its TVL collapse is a possible time-machine story).
   This is the lender-side case: the depositor's risk is bad debt in the markets and being UNABLE
   to withdraw, not AMM slippage.
3. A vault that deploys into an EXTERNAL VENUE (explicitly named in the brief), e.g. a vault or
   yield token routing capital into a perp exchange (Hyperliquid HLP-style vault, or Ethena's
   USDe whose backing sits on CEX perps). The on-chain part is traced; the venue itself is an
   OFFCHAIN/VENUE node whose failure modes (venue halt, auto-deleveraging, withdrawal freeze,
   bridge to the venue) are modelled with disclosed data. A light version is acceptable, but this
   scenario must appear in the demo.
4. Stretch: the Kamino "RockawayX RWA USDC" vault on Solana (discover accounts touched via
   simulateTransaction of a withdraw).

# MODULE 1: TRACE-BASED DEPENDENCY DISCOVERY (30%)
1. Start `anvil --fork-url $ETH_RPC_URL --fork-block-number <N>` (fixed block = cached state).
2. For each position, build and simulate its "critical path" calls:
   a. VALUE: the oracle read the lending market uses (Morpho market oracle.price()) and the
      asset's fair-value path. For a vault: totalAssets() / convertToAssets() (walks every
      market the vault is in).
   b. EXIT: PT → underlying → USDC through the Pendle router (and aggregator if needed), sized
      to the real position. For a vault: redeem()/withdraw() of a realistic share amount, as a
      top depositor (impersonate), which walks the withdraw queue market by market.
   c. LIQUIDATION: Morpho liquidate() on a borrower at the LLTV boundary (impersonate via
      anvil_impersonateAccount and set up a position if needed). For a vault: liquidation path
      of the largest borrower in each market the vault supplies to.
3. Run debug_traceCall with BOTH callTracer (contracts called, call tree) and prestateTracer
   (storage slots read → reveals oracle and state dependencies that aren't obvious calls).
4. Resolve each touched address recursively: EIP-1967/1822 proxy → implementation + admin;
   admin → Safe owners/threshold or timelock delay; names via Sourcify/Etherscan.
   For Morpho vaults (MetaMorpho V1): read owner(), curator(), guardian(), isAllocator(),
   timelock(), supplyQueue/withdrawQueue (length + entries), config(id) caps, and the market
   params of each id. For Vaults V2: owner, curator, sentinels, allocators, adapters, caps.
5. Classify nodes automatically by interface probing (function selectors / ERC-165 / known
   signatures): Chainlink-style aggregator (latestRoundData), Pyth, Redstone, ERC-4626 vault,
   MetaMorpho vault, Pendle market/SY, Morpho, Uniswap/Curve pool, ERC-20, Safe, timelock.
   Node types: CHAIN, CONTRACT, ASSET, ORACLE, LIQUIDITY_VENUE, LENDING_MARKET, VAULT, GOVERNANCE,
   ISSUER (RWA issuer / stablecoin issuer), OFFCHAIN (custodian, CEX, originator).
6. Off-chain layers that no trace can see (Ethena's CEX hedges and custodians; Figure's HELOC
   warehouse; OnRe reinsurance contracts; Huma PayFi receivables) are added from public sources
   ONLY, tagged `offchain_disclosed` with a link. Every node/edge carries provenance:
   {source: trace|storage|api|registry|disclosure, block, tx/call, confidence}.
   Flag explicitly when an oracle is ISSUER-REPORTED (NAV pushed by the issuer or a fixed price)
   rather than market-derived: then the issuer is both the asset and its price, which is a
   single point of failure the market cannot signal.
7. Edges are typed by WHICH critical path touched them: `prices`, `exit_route`,
   `liquidation_route`, `governs`, `wraps`, `backs`, `allocates_to`, `issued_by`.
   One node on several paths = a critical node.
   Output: graph JSON + depth per layer, compared with the brief's 5-layer Pendle example
   (settlement chain / yield source & issuer / oracle / PT AMM / lending market). Map every
   discovered node onto those 5 layers so judges see their own picture, then show the extra
   layers we found beyond it (proxy admins, multisigs, timelocks, feed sources, custodians).
8. ORACLE FEED-QUALITY ANALYSIS (named in the brief's scope). For every oracle node, score:
   number of independent sources, provider, heartbeat and deviation threshold, observed staleness
   and update history over the last 30 days (from on-chain events), deviation from DEX/CEX spot
   at current block, whether it is market-derived, exchange-rate based, hardcoded or
   issuer-reported, and who can change it (admin + timelock). Flag "asset priced by a single
   feed" explicitly.
9. TVL CONCENTRATION (named in the brief's scope). For every protocol node, fetch its TVL and its
   share of its chain's DeFi TVL (DefiLlama). Flag protocols that concentrate a large share of a
   chain's TVL: their failure is also a chain-level liquidity event that hits every other position
   on that chain (wider spreads, frozen collateral, congested exits). Feed this into the
   correlation structure of Module 2.

# MODULE 2: FORK-AND-BREAK IMPACT ENGINE (30%)
For each critical node, define shocks applied directly to fork state:
- Oracle: overwrite the answer/storage (anvil_setStorageAt) or mock the call: −2/−5/−8/−15%,
  stale (advance time beyond heartbeat), frozen.
- Underlying depeg: move sUSDe/USDe prices via pool state and oracle together (correlated).
- Liquidity shock: remove X% of Pendle AMM liquidity (impersonate the top LPs and withdraw).
- RWA collateral shocks (vault positions): NAV markdown of PRIME/ONyc/PST (−5/−10/−25/−50%),
  NAV oracle frozen while the real value falls (no liquidations triggered = silent bad debt),
  redemption gate by the issuer (collateral cannot be sold, liquidators have no exit), issuer
  default. Re-run liquidations: with thin secondary liquidity, measure how much is actually
  recoverable and how much becomes bad debt socialized to vault depositors.
- Utilization shock: borrowers stop repaying / depositors rush; push utilization to 100% and
  measure what a depositor can still withdraw.
- Governance: simulate the admin/curator calling a malicious upgrade or a harmful reallocation
  (impersonate), to show WHO can move funds and how fast (timelock delay = time-to-impact).
- Venue/counterparty failure (off-chain nodes): parametric haircut from historical incidents
  (USDe Binance dislocation 10 Oct 2025, USDC/SVB Mar 2023, stETH Jun 2022, xUSD Nov 2025).
After each shock, RE-EXECUTE the exit and liquidation on the fork and record real outcomes:
mark-to-market change, exit proceeds, withdrawable amount, liquidation yes/no, penalty, bad debt,
loss per vault share.
Then:
- Fit a response surface (loss as a function of shock size) per node from the fork runs.
- Monte Carlo (10k paths) over correlated shock scenarios. Probabilities come from base rates
  (DefiLlama hacks dataset by protocol type/age/TVL, historical depeg frequency, RWA/private
  credit default and impairment history). Output E[L], VaR95, CVaR95, and time-to-impact.
- Attribution: share of expected loss per dependency path.
- Every parameter goes in an assumptions table with a source and a slider. Numbers come from code,
  never from an LLM.

# MODULE 3: THE EXIT RACE (25%)
1. Fetch the real holder distribution: top PT holders, Pendle LPs, Morpho market suppliers/
   borrowers, the vaults allocating to each market, and the TOP DEPOSITORS of each curated vault
   (vault share Transfer logs, Morpho API).
2. Agent-based run model: when shock S hits, each large holder exits with a probability and
   delay drawn from their type (vault curator, fund, EOA whale, looper near LLTV). Loopers near
   liquidation are forced sellers. Simulate the sequence ON THE FORK so each exit really drains
   liquidity for the next one.
3. Two kinds of exit cost, measured, not assumed:
   - Trader side (PT, tokens): slippage curve vs size and time, C_exit(x, t).
   - Lender side (vault deposits): withdrawable liquidity = vault idle + unborrowed liquidity in
     each market of the withdraw queue. At ~93% utilization only a small slice is instantly
     withdrawable; the rest waits for repayments or for the IRM to push rates high enough to
     pull liquidity in. Model "time to full exit" and the loss accrued while locked. Being first
     out of the vault is the whole game: show depositor rank vs recovered %.
4. Output the exit-cost curve over time: exiting now, after 15 min, 1 h, 6 h, 24 h.
   Compare with the expected-loss curve E[L](t).
5. Decision rule shown in the UI:
   EXIT x% at t* where  E[L_stay] + λ·(CVaR95 − E[L]) − C_exit(x, t*)  is maximized.
   Show the BREAKEVEN BELIEF: "Exiting is justified if P(full depeg) > 14%. Our estimate: 9%
   → REDUCE 40% now, hold the rest, re-check on trigger T."
6. Built-in test: the brief's own case (10 pockets × 10%, one affected, 11% slippage). Show the
   P×LGD threshold, and how it moves once the exit race is modelled (11% now vs 19% in 1 h).

# MODULE 4: PORTFOLIO X-RAY + HIDDEN CONCENTRATION CHECK
Accept a book of several positions (Belem-style mandates + the curated vault book above).
Merge their graphs and find SHARED ANCESTORS (same oracle, same collateral, same issuer, same
originator, same admin multisig, same CEX).
Output the "effective number of independent bets" and the worst single point of failure for the
book: "These 10 pockets are 3 bets: 46% of the book depends on one oracle."
Stretch (high value for this jury): run the X-ray across ALL of the setter's vaults (33 vaults,
8 chains, 9 protocols per the dashboard), using books/belem_vaults.csv for the vault list and on-chain/API reads for
allocations, to find shared collateral, issuers and oracles across their whole curated book.
Then run the curator's OWN published concentration limits (single protocol 25%, single oracle 40%,
correlated assets 40%, single chain 60%, max 15% per AA market) against the TRUE discovered
dependencies, not the labels: two "different" markets sharing one oracle, one issuer, or one
off-chain originator count as one exposure. Report "compliant on paper / exposure found by Fault
Line" side by side. Report what the data shows; do not assert a breach without the live numbers.

# MODULE 5: TIME MACHINE (demo killer)
Fork at the block just before a real incident (10 Oct 2025 USDe dislocation, or Stream/xUSD
Nov 2025, where lending curators discovered a hidden dependency chain after the fact). Run the
full pipeline on THAT state and show what Fault Line would have recommended, next to what
actually happened afterwards (later blocks). If an archive replay is too slow, pre-compute it
and cache the results.

# MODULE 6: WATCH MODE ("three in the morning")
Belem monitors every position in real time. Add a simple loop that, every N blocks, re-reads the
critical nodes (oracle answers and freshness, pool depth, market utilization, vault allocations,
admin/timelock pending actions, peg of key stables). When a threshold trips, it automatically runs
the relevant shock from Module 2 at the observed size and pushes an alert with the headline
number: "USDe −3.1% on CEX. PT-sUSDe pocket: net value of exiting now = +42 bps of book → REDUCE
60%. Exit window closing: est. cost +8% in 1 h." Demo it by replaying the time-machine blocks.

# UI (Streamlit)
- HEADLINE NUMBER at the top, large: net value of exiting now (bps of book and $), with
  STAY / REDUCE x% / EXIT next to it.
- Recommendation card: $ impact, breakeven belief, #1 driver, time-to-impact,
  3-line plain-English reason that names the propagation path.
- Graph (pyvis/cytoscape), colored by risk contribution. Click a node → its provenance
  (the trace/call it came from) and its "break it" button.
- "Break it" → runs the shock on the fork live → graph lights up → card updates.
- Charts: loss distribution, exit-race curves with their crossover (slippage for tokens,
  withdrawable liquidity over time for vaults), tornado sensitivity.
- Assumptions page, Portfolio X-ray page, and a "Vault view": allocations by market, by issuer,
  by oracle, against the curator's own limits.

# RULES
- Real state only. Verify every address on-chain before use (including the RockawayX addresses
  above). Never invent numbers; anything not measured is tagged `assumption` with a source.
- Cache fork results and API responses. The demo must run offline if the RPC dies on stage.
- Deterministic seeds. Tests: discovery on hero #1 must find the Pendle market, SY, sUSDe/USDe,
  the Morpho market's oracle and its underlying feeds, and the proxy admins. Discovery on hero #2
  must find every market in the vault's withdraw queue, each market's oracle and collateral, and
  the vault's owner/curator/guardian/timelock.
- Ship working increments. One complete hero position beats five half-done ones.

# MILESTONES
M1 (25%): anvil fork + critical-path traces + recursive resolver → graph with provenance (hero #1),
          then the vault resolver (hero #2: queues, markets, roles).
M2 (50%): fork-and-break for oracle, depeg, liquidity, RWA NAV and utilization shocks → measured
          losses + Monte Carlo.
M3 (70%): holder/depositor fetch + exit race (trader side and lender side) + decision rule +
          breakeven.
M4 (85%): Streamlit UI with headline number, live "Break it", the Vault view and oracle
          feed-quality table.
M5 (rest): time machine replay + watch mode, perp-venue vault scenario, portfolio X-ray with
           hidden concentration check, README, cached demo, 3-minute script.
Before submitting, check off each item of "WHAT THE BRIEF ASKS" and each judging criterion in a
README section titled "How Fault Line answers the brief".

# START NOW
1. Propose the repo layout and the pydantic schemas for Node, Edge, Shock and Result, plus the
   `book.yaml` portfolio input format. Write QUESTIONS.md for Belem's office hours (their
   reference portfolio, the incident families they care most about, their risk-aversion λ,
   typical position sizes, their own exit-cost assumptions).
2. Find and verify the hero positions' addresses (PT-sUSDe stack; RockawayX USDC Yield vault,
   its roles and its markets), and list them with block numbers.
3. Write the M1 trace script for hero #1 and run it. Show the discovered graph before moving on.
4. Tell us immediately what keys or access you need from us (e.g. RPC limits, Helius for Solana).
