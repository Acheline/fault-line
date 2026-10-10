"""Fork-and-break primitives for Morpho Blue lender positions (Module 2). Generic: any vault or supplier reuses them.

market_shock() applies ONE correlated event to several markets inside one fork snapshot:
  - the collateral's TRUE value moves by `true_move` (what it can be sold for),
  - the market oracle is pinned at (1 + oracle_move) x its price (oracle_move = 0: frozen while value falls),
  - liquidators act only on positions unhealthy AT THE ORACLE, and only up to `capacity_usd` of seized collateral:
    the size they can sell within the liquidation bonus, measured from executed exit routes (no assumed recovery),
  - afterwards every position is re-read from the fork: realized bad debt (Morpho supply drop) + the shortfall still
    hidden in unliquidated positions at the true value = the economic loss to lenders.
The vault's loss = its share of each market's loss, per vault share; "recognized" = the share-price drop the vault
itself reports on the fork (0 while the oracle is frozen: the loss is silent).
"""
from __future__ import annotations

from dataclasses import dataclass

from eth_abi import encode

from core import addresses as A
from core.fork import Fork, selector

WAD = 10**18
MP = "(address,address,address,address,uint256)"
LIQUIDATOR = "0xfa0171fa0171fa0171fa0171fa0171fa0171fa01"


def lif(lltv: int) -> int:
    """Morpho Blue liquidation incentive factor: min(1.15, 1 / (1 - 0.3 * (1 - lltv)))."""
    return min(115 * WAD // 100, WAD * WAD // (WAD - 3 * (WAD - lltv) // 10))


@dataclass
class MarketLeg:
    label: str
    market_id: str
    params: list            # (loan, collateral, oracle, irm, lltv)
    borrowers: list[dict]   # {"user", "borrow_shares", "collateral", ...} read on the fork
    vault_share: float      # vault supply / market supply
    true_move: float        # e.g. -0.10
    oracle_move: float      # 0.0 = frozen; == true_move = oracle tracks value
    capacity_usd: float     # seized collateral (USD at oracle) liquidators can sell within the bonus


def _market(fork: Fork, mid: bytes):
    return fork.call(A.MORPHO_BLUE, "market(bytes32)", ["bytes32"], [mid], ["uint128"] * 6)


def _position(fork: Fork, mid: bytes, user: str):
    return fork.call(A.MORPHO_BLUE, "position(bytes32,address)", ["bytes32", "address"], [mid, user],
                     ["uint256", "uint128", "uint128"])


def market_shock(fork: Fork, vault: str, legs: list[MarketLeg]) -> dict:
    out = {"legs": []}
    with fork.snapshot():
        pps0 = fork.call1(vault, "convertToAssets(uint256)", "uint256", ["uint256"], [WAD])
        ta0 = fork.call1(vault, "totalAssets()", "uint256") or 1
        fork.fund_erc20(A.USDC, LIQUIDATOR, 10**9 * 10**6)
        fork.send(LIQUIDATOR, A.USDC, selector("approve(address,uint256)") + encode(["address", "uint256"], [A.MORPHO_BLUE, 2**256 - 1]))
        pre = {}
        for lg in legs:     # pin every oracle first: one event, all markets at once
            mid = bytes.fromhex(lg.market_id[2:])
            p0 = fork.call1(lg.params[2], "price()", "uint256")
            pre[lg.market_id] = (p0, _market(fork, mid)[0])
            fork.pin_price(lg.params[2], int(p0 * (1 + lg.oracle_move)))
        for lg in legs:
            mid = bytes.fromhex(lg.market_id[2:])
            p0, sup0 = pre[lg.market_id]
            p_or, p_true = p0 * (1 + lg.oracle_move), p0 * (1 + lg.true_move)
            lltv = int(lg.params[4])
            L = lif(lltv)
            mk = _market(fork, mid)
            cap_left, n_liq, seized_usd, errors = lg.capacity_usd * 1e6, 0, 0.0, []
            rows = []
            for b in lg.borrowers:
                pos = _position(fork, mid, b["user"])
                if not pos or pos[1] == 0:
                    continue
                debt = -(-pos[1] * (mk[2] + 1) // (mk[3] + 10**6))
                rows.append((pos[2] * p_or / 1e36 * lltv / WAD / debt if debt else 9e9, b["user"], pos, debt))
            for hf, user, pos, debt in sorted(rows):
                if hf >= 1 or cap_left <= 1e6:
                    continue
                coll_val = pos[2] * p_or / 1e36                    # USDC units at the oracle
                need = debt * L / WAD                              # collateral value to seize for a full repay
                take_val = min(coll_val, need * 1.001, cap_left)
                seize = min(pos[2], int(take_val * 1e36 / p_or))
                if take_val >= need * 1.001 and need <= cap_left:  # full repay fits: repay by shares (exact)
                    args = [0, pos[1]]
                else:                                              # partial (capacity) or all collateral
                    args = [seize, 0]
                data = selector(f"liquidate({MP},address,uint256,uint256,bytes)") + encode(
                    [MP, "address", "uint256", "uint256", "bytes"], [tuple(lg.params), user, *args, b""])
                try:
                    fork.send(LIQUIDATOR, A.MORPHO_BLUE, data)
                    n_liq += 1
                    cap_left -= take_val
                    seized_usd += take_val / 1e6
                except RuntimeError as e:
                    errors.append(f"{user[:10]}: {str(e)[:60]}")
            # re-read every position: shortfall still hidden at the TRUE value
            mk1 = _market(fork, mid)
            hidden = 0.0
            for b in lg.borrowers:
                pos = _position(fork, mid, b["user"])
                if not pos or pos[1] == 0:
                    continue
                debt = -(-pos[1] * (mk1[2] + 1) // (mk1[3] + 10**6))
                hidden += max(0.0, debt - pos[2] * p_true / 1e36) / 1e6
            realized = max(0, sup0 - mk1[0]) / 1e6
            out["legs"].append({"market": lg.label, "true_move": lg.true_move, "oracle_move": lg.oracle_move,
                                "capacity_usd": lg.capacity_usd, "n_liquidated": n_liq, "seized_usd": seized_usd,
                                "realized_bad_debt_usd": realized, "hidden_shortfall_usd": hidden,
                                "vault_share": lg.vault_share,
                                "vault_loss_usd": lg.vault_share * (realized + hidden), "errors": errors})
        pps1 = fork.call1(vault, "convertToAssets(uint256)", "uint256", ["uint256"], [WAD])
    loss = sum(x["vault_loss_usd"] for x in out["legs"])
    out.update(vault_total_assets_usd=ta0 / 1e6, vault_loss_usd=loss, loss_per_share=loss / (ta0 / 1e6),
               recognized_loss_per_share=1 - pps1 / pps0 if pps0 and pps1 else None)
    return out
