"""Black-Scholes Greeks for European vanilla options."""

from __future__ import annotations

from dataclasses import dataclass
from math import exp, pi, sqrt

try:
    from .black_scholes import OptionType, d1, d2, normal_cdf
except ImportError:  # pragma: no cover - supports direct script execution.
    from black_scholes import OptionType, d1, d2, normal_cdf

_INV_SQRT_2PI = 1.0 / sqrt(2.0 * pi)
_EPSILON = 1.0e-12


@dataclass(frozen=True)
class Greeks:
    """Option sensitivities under Black-Scholes."""

    delta: float
    gamma: float
    vega: float
    theta: float
    rho: float


def normal_pdf(x: float) -> float:
    """Standard normal density."""

    return _INV_SQRT_2PI * exp(-0.5 * x * x)


def black_scholes_greeks(
    spot: float,
    strike: float,
    time_to_maturity: float,
    risk_free_rate: float,
    volatility: float,
    option_type: OptionType = "call",
) -> Greeks:
    """Return delta, gamma, vega, theta, and rho.

    Vega is expressed per 1.00 volatility point, not per 1 percentage point.
    Theta is annualized.
    """

    if time_to_maturity <= _EPSILON or volatility <= _EPSILON:
        if option_type == "call":
            delta = 1.0 if spot > strike else 0.0 if spot < strike else 0.5
        elif option_type == "put":
            delta = -1.0 if spot < strike else 0.0 if spot > strike else -0.5
        else:
            raise ValueError(f"Unsupported option type: {option_type!r}")
        return Greeks(delta=delta, gamma=0.0, vega=0.0, theta=0.0, rho=0.0)

    d_1 = d1(spot, strike, time_to_maturity, risk_free_rate, volatility)
    d_2 = d2(spot, strike, time_to_maturity, risk_free_rate, volatility)
    pdf_d1 = normal_pdf(d_1)
    discount_factor = exp(-risk_free_rate * time_to_maturity)
    sqrt_t = sqrt(time_to_maturity)

    gamma = pdf_d1 / (spot * volatility * sqrt_t)
    vega = spot * pdf_d1 * sqrt_t

    carry_term = risk_free_rate * strike * discount_factor
    decay_term = -(spot * pdf_d1 * volatility) / (2.0 * sqrt_t)

    if option_type == "call":
        delta = normal_cdf(d_1)
        theta = decay_term - carry_term * normal_cdf(d_2)
        rho = strike * time_to_maturity * discount_factor * normal_cdf(d_2)
    elif option_type == "put":
        delta = normal_cdf(d_1) - 1.0
        theta = decay_term + carry_term * normal_cdf(-d_2)
        rho = -strike * time_to_maturity * discount_factor * normal_cdf(-d_2)
    else:
        raise ValueError(f"Unsupported option type: {option_type!r}")

    return Greeks(delta=delta, gamma=gamma, vega=vega, theta=theta, rho=rho)


def portfolio_delta(option_inventory: int, option_delta: float, multiplier: int = 100) -> float:
    """Convert contract inventory and per-option delta into share-equivalent delta."""

    return option_inventory * option_delta * multiplier
