"""Whole-unit, cash-constrained synthetic options account; no broker services."""
from dataclasses import dataclass
from math import isfinite


@dataclass
class Account:
    cash: float
    multiplier: int
    strike: float
    option_type: str
    max_contracts: int
    contracts: int = 0
    shares: int = 0
    fees: float = 0.

    def reserve(self, spot, contracts=None, shares=None):
        contracts = self.contracts if contracts is None else contracts
        shares = self.shares if shares is None else shares
        # Simple conservative research collateral. No offsets between positions.
        return (max(-contracts, 0) * self.multiplier * (spot if self.option_type == 'call' else self.strike)
                + max(-shares, 0) * spot * 1.5)

    def transact(self, asset, quantity, price, fee, spot):
        if asset not in {'option', 'stock'} or not isinstance(quantity, int):
            raise ValueError('Whole-unit option or stock trade required')
        if not all(isfinite(v) for v in (price, fee, spot)) or price <= 0 or spot <= 0 or fee < 0:
            raise ValueError('Positive finite prices and nonnegative fees required')
        contracts = self.contracts + (quantity if asset == 'option' else 0)
        shares = self.shares + (quantity if asset == 'stock' else 0)
        cash_flow = -quantity * price * (self.multiplier if asset == 'option' else 1) - fee
        cash = self.cash + cash_flow
        reserve = self.reserve(spot, contracts, shares)
        free_before = self.cash - self.reserve(spot)
        gross_before = abs(self.contracts)*self.multiplier + abs(self.shares)
        gross_after = abs(contracts)*self.multiplier + abs(shares)
        reducing_breach = gross_after < gross_before and cash-reserve > free_before
        allowed = bool(cash >= 0 and abs(contracts) <= self.max_contracts
                       and (cash >= reserve or reducing_breach))
        if allowed:
            self.cash, self.contracts, self.shares = cash, contracts, shares
            self.fees += fee
        return dict(accepted=allowed, cash_flow=cash_flow if allowed else 0.,
                    reason='' if allowed else 'Cash, collateral or inventory limit')
