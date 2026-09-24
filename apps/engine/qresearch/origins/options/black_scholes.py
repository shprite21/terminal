"""Black-Scholes pricing utilities for European vanilla options."""

from __future__ import annotations

from dataclasses import dataclass
from math import erf, exp, log, sqrt
from typing import Literal

OptionType = Literal["call", "put"]

_INV_SQRT_2 = 1.0 / sqrt(2.0)
_EPSILON = 1.0e-12


@dataclass(frozen=True)
class OptionSpec:
    """Contract-level option metadata used throughout the simulation."""

    strike: float
    maturity_years: float
    option_type: OptionType = "call"
    risk_free_rate: float = 0.02
    volatility: float = 0.20
    multiplier: int = 100


def normal_cdf(x: float) -> float:
    """Standard normal cumulative distribution function."""

    return 0.5 * (1.0 + erf(x * _INV_SQRT_2))


def intrinsic_value(spot: float, strike: float, option_type: OptionType) -> float:
    """Intrinsic value at expiry."""

    if option_type == "call":
        return max(spot - strike, 0.0)
    if option_type == "put":
        return max(strike - spot, 0.0)
    raise ValueError(f"Unsupported option type: {option_type!r}")


def _validate_inputs(
    spot: float,
    strike: float,
    time_to_maturity: float,
    volatility: float,
    option_type: OptionType,
) -> None:
    if spot <= 0.0:
        raise ValueError("spot must be positive")
    if strike <= 0.0:
        raise ValueError("strike must be positive")
    if time_to_maturity < 0.0:
        raise ValueError("time_to_maturity cannot be negative")
    if volatility < 0.0:
        raise ValueError("volatility cannot be negative")
    if option_type not in {"call", "put"}:
        raise ValueError(f"Unsupported option type: {option_type!r}")


def d1(
    spot: float,
    strike: float,
    time_to_maturity: float,
    risk_free_rate: float,
    volatility: float,
) -> float:
    """Black-Scholes d1 term."""

    if time_to_maturity <= _EPSILON or volatility <= _EPSILON:
        raise ValueError("d1 is undefined at zero maturity or zero volatility")

    variance = volatility * volatility
    numerator = log(spot / strike) + (risk_free_rate + 0.5 * variance) * time_to_maturity
    denominator = volatility * sqrt(time_to_maturity)
    return numerator / denominator


def d2(
    spot: float,
    strike: float,
    time_to_maturity: float,
    risk_free_rate: float,
    volatility: float,
) -> float:
    """Black-Scholes d2 term."""

    return d1(spot, strike, time_to_maturity, risk_free_rate, volatility) - volatility * sqrt(
        time_to_maturity
    )


def black_scholes_price(
    spot: float,
    strike: float,
    time_to_maturity: float,
    risk_free_rate: float,
    volatility: float,
    option_type: OptionType = "call",
) -> float:
    """Price a European option with the Black-Scholes model.

    The zero-volatility branch discounts the deterministic payoff under the
    risk-neutral forward, which keeps pricing well behaved near expiry.
    """

    _validate_inputs(spot, strike, time_to_maturity, volatility, option_type)

    if time_to_maturity <= _EPSILON:
        return intrinsic_value(spot, strike, option_type)

    discount_factor = exp(-risk_free_rate * time_to_maturity)

    if volatility <= _EPSILON:
        forward = spot / discount_factor
        payoff = max(forward - strike, 0.0) if option_type == "call" else max(strike - forward, 0.0)
        return discount_factor * payoff

    d_1 = d1(spot, strike, time_to_maturity, risk_free_rate, volatility)
    d_2 = d_1 - volatility * sqrt(time_to_maturity)

    if option_type == "call":
        return spot * normal_cdf(d_1) - strike * discount_factor * normal_cdf(d_2)

    return strike * discount_factor * normal_cdf(-d_2) - spot * normal_cdf(-d_1)


def price_from_spec(spec: OptionSpec, spot: float, elapsed_years: float = 0.0) -> float:
    """Price an option spec at a given underlying spot and elapsed simulation time."""

    remaining_maturity = max(spec.maturity_years - elapsed_years, 0.0)
    return black_scholes_price(
        spot=spot,
        strike=spec.strike,
        time_to_maturity=remaining_maturity,
        risk_free_rate=spec.risk_free_rate,
        volatility=spec.volatility,
        option_type=spec.option_type,
    )
