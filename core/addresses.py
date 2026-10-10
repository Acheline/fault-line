"""Hero position addresses. Every entry was verified on the anvil fork (block FORK_BLOCK) on 2026-10-10:
see the comment next to each for the on-chain read that verified it."""

FORK_BLOCK = 26161499          # anvil fork head when verified (mainnet, 2026-10-10)

# ---- shared ----
USDC = "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"
MORPHO_BLUE = "0xBBBBBbbBBb9cC5e90e3b3Af64bdAF62C37EEFFCb"
PENDLE_ROUTER_V4 = "0x888888888889758F76e7103c6CbF23ABbF58F946"     # tx.to returned by Pendle SDK convert
CHAINLINK_USDC_USD = "0x8fFfFfd4AfB6115b954Bd326cbe7B4BA576818f6"   # EAC proxy, description "USDC / USD"
CURVE_USDE_USDC = "0x02950460E2b9529D0E00284A5fA2d7bDF3fA4d72"      # coins(0)=USDe, coins(1)=USDC; ~$490k deep
PENDLE_PY_LP_ORACLE = "0x9a9Fa8338dd5E5B2188006f1Cd2Ef26d921650C2"  # TransparentUpgradeableProxy (Etherscan); getOracleState ok

# ---- hero #1: PT-sUSDe-26NOV2026, outright + Morpho collateral borrowing USDC ----
HERO1 = dict(
    position_id="hero1_pt_susde_26nov2026",
    pt="0xB195B618EA52b77CB2a58846F452f59f8dFa9390",           # symbol PT-sUSDE-26NOV2026, expiry 1795651200
    yt="0x89E6e5f7c3A60e7D6347F054051A29a272F4cE44",           # PT.YT()
    sy="0xBF98480425A29197e5d99D003017f63a1e595D02",           # PT.SY(), symbol SY-sUSDE
    pendle_market="0x47ad2cd1dd15739a7a035b9d3b7828d916fef77e",  # readTokens() == (SY, PT, YT)
    susde="0x9D39A5DE30e57443BfF2A8307A4256c8797A3497",        # SY.yieldToken()
    usde="0x4c9EDD5852cd905f086C759E8383e09bff1E68B3",         # SY.getTokensIn()[0]
    morpho_market_id="0x5613b170ded221c588b6e9637b910f49e5508680ceede207f44aa72e5c46cb05",
    # idToMarketParams(id) == (USDC, PT, oracle, irm, 0.915e18)
    morpho_oracle="0xF8b29e7E9c00CE531434775f7923CC9fbCa01b08",   # MetaOracleDeviationTimelock proxy
    morpho_irm="0x870aC11D48B15DB9a138Cf899d20F13F79Ba00BC",
    lltv=915_000_000_000_000_000,
    usde_usd_feed="0xa569d910839Ae8865Da8F8e70FfFb0cBA869F961",  # EACAggregatorProxy, description "USDe / USD"
    # assumption: position size for the exit trace (no real Belem position given). Source: team to replace.
    exit_size_pt=1_000_000 * 10**18,
    # Real borrower used for the liquidation trace: #2 borrower by size, HF 1.0098 per Morpho API (2026-10-10)
    liq_borrower="0x5C430FF6F374da12218b380d2040299Ae5B6d40E",
)

# ---- hero #2 candidates (RockawayX, Morpho Vault V2; NOT Belem's book) ----
FIGURE_USDC_MAIN = "0xd65d6E8dbC3Cd3D12418199E6f4014dB3aaa0097"   # VaultV2, totalAssets 11.36 USDC: wound down
ROCKAWAYX_USDC_YIELD = "0xE0181090c22579B6A217f1522cbf8c9f1F0C1965"  # VaultV2, ~$18.5M (Morpho API)
ROCKAWAYX_CONF_RWA_USDC = "0xc207d3f66537D7F66456808379A0E560cF20Da36"  # VaultV2, ~$26.4M (Morpho API)
ROCKAWAYX_OWNER_CURATOR = "0xbBacDCFB9691DFA1066aB29edfcc4A73f6DEf918"
PRIME_USDC_MARKET_ID = "0x755f954513d31d5f24aaf3d0cdc5e913a28383f8ea8ff85be9ffffa7371fb64d"  # LLTV 86%
PRIME = "0x19ebb35279A16207Ec4ba82799CC64715065F7F6"
