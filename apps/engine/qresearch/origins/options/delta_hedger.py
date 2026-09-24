"""Dynamic delta hedging for option inventory."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class HedgeTrade:
    """Stock trade used to rebalance option delta exposure."""

    step: int
    time_years: float
    spot: float
    shares: float
    transaction_cost: float
    stock_position_after: float
    cash_after: float
    pre_trade_delta: float
    post_trade_delta: float


@dataclass(frozen=True)
class DeltaHedgerConfig:
    """Controls for hedging frequency and execution cost."""

    hedge_threshold_shares: float = 15.0
    min_trade_size_shares: float = 1.0
    transaction_cost_bps: float = 0.5


class DeltaHedger:
    """Maintain a stock hedge against option inventory delta."""

    def __init__(self, config: DeltaHedgerConfig):
        if config.hedge_threshold_shares < 0.0:
            raise ValueError("hedge_threshold_shares cannot be negative")
        if config.min_trade_size_shares < 0.0:
            raise ValueError("min_trade_size_shares cannot be negative")
        if config.transaction_cost_bps < 0.0:
            raise ValueError("transaction_cost_bps cannot be negative")
        self.config = config
        self.stock_position = 0.0
        self.cash = 0.0

    @staticmethod
    def net_delta(
        option_inventory: int,
        option_delta: float,
        stock_position: float,
        multiplier: int = 100,
    ) -> float:
        """Share-equivalent delta after including the stock hedge."""

        return option_inventory * option_delta * multiplier + stock_position

    def rebalance(
        self,
        step: int,
        time_years: float,
        spot: float,
        option_inventory: int,
        option_delta: float,
        multiplier: int = 100,
    ) -> Optional[HedgeTrade]:
        """Trade stock when net delta breaches the hedge threshold."""

        pre_trade_delta = self.net_delta(
            option_inventory=option_inventory,
            option_delta=option_delta,
            stock_position=self.stock_position,
            multiplier=multiplier,
        )
        if abs(pre_trade_delta) <= self.config.hedge_threshold_shares:
            return None

        target_stock_position = -option_inventory * option_delta * multiplier
        shares_to_trade = target_stock_position - self.stock_position
        if abs(shares_to_trade) < self.config.min_trade_size_shares:
            return None

        notional = shares_to_trade * spot
        transaction_cost = abs(notional) * self.config.transaction_cost_bps / 10_000.0
        self.cash -= notional + transaction_cost
        self.stock_position += shares_to_trade

        post_trade_delta = self.net_delta(
            option_inventory=option_inventory,
            option_delta=option_delta,
            stock_position=self.stock_position,
            multiplier=multiplier,
        )
        return HedgeTrade(
            step=step,
            time_years=time_years,
            spot=spot,
            shares=shares_to_trade,
            transaction_cost=transaction_cost,
            stock_position_after=self.stock_position,
            cash_after=self.cash,
            pre_trade_delta=pre_trade_delta,
            post_trade_delta=post_trade_delta,
        )
