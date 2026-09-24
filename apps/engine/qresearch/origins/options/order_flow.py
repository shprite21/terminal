"""Randomized customer order flow for a simplified options exchange."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional, Protocol

import numpy as np

CustomerSide = Literal["buy", "sell"]


class QuoteLike(Protocol):
    bid: float
    ask: float
    mid: float


@dataclass(frozen=True)
class Order:
    """Customer order generated against the market maker's displayed quote."""

    step: int
    time_years: float
    side: CustomerSide
    quantity: int
    limit_price: float
    fair_value: float


@dataclass(frozen=True)
class OrderFlowConfig:
    """Stochastic order-arrival and sizing parameters."""

    base_arrival_probability: float = 0.62
    mean_quantity: float = 4.0
    max_quantity: int = 25
    adverse_selection_strength: float = 0.25
    value_sensitivity: float = 7.5
    seed: int = 7


class OrderFlowSimulator:
    """Generate randomized buy/sell orders from customer perspective."""

    def __init__(self, config: OrderFlowConfig):
        if not 0.0 <= config.base_arrival_probability <= 1.0:
            raise ValueError("base_arrival_probability must be in [0, 1]")
        if config.mean_quantity <= 0.0:
            raise ValueError("mean_quantity must be positive")
        if config.max_quantity <= 0:
            raise ValueError("max_quantity must be positive")
        self.config = config
        self.rng = np.random.default_rng(config.seed)

    def generate_order(
        self,
        step: int,
        time_years: float,
        quote: QuoteLike,
        fair_value: float,
        directional_signal: float = 0.0,
    ) -> Optional[Order]:
        """Generate a customer order or return None if no customer arrives."""

        if self.rng.random() > self.config.base_arrival_probability:
            return None

        mid_edge = (fair_value - quote.mid) / max(fair_value, 1.0e-8)
        signal = (
            self.config.value_sensitivity * mid_edge
            + self.config.adverse_selection_strength * directional_signal
        )
        buy_probability = float(np.clip(0.5 + 0.35 * np.tanh(signal), 0.05, 0.95))
        side: CustomerSide = "buy" if self.rng.random() < buy_probability else "sell"

        raw_quantity = int(self.rng.poisson(self.config.mean_quantity) + 1)
        quantity = max(1, min(self.config.max_quantity, raw_quantity))
        limit_price = quote.ask if side == "buy" else quote.bid

        return Order(
            step=step,
            time_years=time_years,
            side=side,
            quantity=quantity,
            limit_price=limit_price,
            fair_value=fair_value,
        )
