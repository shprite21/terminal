"""Q adaptations of quant-research project 03: European vanilla pricing.

No market data or broker access. Values are per underlying unit, theta per year,
vega/rho per absolute unit of volatility/rate. Non-differentiable boundary
sensitivities are explicitly unavailable, except the conventional half delta.
"""
from __future__ import annotations

from math import erfc, exp, isfinite, log, pi, sqrt
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class PricingConfig(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False, validate_default=True)
    spot: float = Field(100, ge=.01, le=1_000_000)
    strike: float = Field(100, ge=.01, le=1_000_000)
    maturity_years: float = Field(30/252, ge=0, le=10)
    rate: float = Field(.02, ge=-.2, le=1)
    volatility: float = Field(.22, ge=0, le=3)
    option_type: Literal['call', 'put'] = 'call'


def values(spot, strike, maturity, rate, volatility, option_type='call'):
    """Return price and Greeks; no epsilon cut-off of positive time/volatility."""
    if (not all(isfinite(x) for x in (spot, strike, maturity, rate, volatility))
            or spot <= 0 or strike <= 0 or maturity < 0 or volatility < 0
            or option_type not in {'call', 'put'}):
        raise ValueError('Finite positive spot/strike and nonnegative maturity/volatility required')
    sign = 1 if option_type == 'call' else -1
    discounted_strike = strike * exp(-rate * maturity)
    boundary = spot - discounted_strike
    if maturity == 0 or volatility == 0:
        # At expiry theta is undefined; at the deterministic forward strike
        # gamma and the volatility derivative are not ordinary smooth Greeks.
        active = 1. if sign * boundary > 0 else 0. if sign * boundary < 0 else .5
        kink = boundary == 0
        return dict(price=max(sign * boundary, 0.), delta=sign * active,
                    gamma=None if kink else 0., vega=None if kink else 0.,
                    theta=None if maturity == 0 or kink else -sign * active * rate * discounted_strike,
                    rho=None if kink and maturity > 0 else sign * active * maturity * discounted_strike)
    root = sqrt(maturity)
    d1 = (log(spot / strike) + (rate + .5 * volatility ** 2) * maturity) / (volatility * root)
    d2 = d1 - volatility * root
    cdf = lambda z: .5 * erfc(-z / sqrt(2))
    density = exp(-.5*d1*d1) / sqrt(2*pi)
    result = dict(
        price=max(0., sign * (spot * cdf(sign*d1) - discounted_strike * cdf(sign*d2))),
        delta=sign*cdf(sign*d1), gamma=density/(spot*volatility*root),
        vega=spot*density*root,
        theta=-spot*density*volatility/(2*root)-sign*rate*discounted_strike*cdf(sign*d2),
        rho=sign*maturity*discounted_strike*cdf(sign*d2))
    if not all(isfinite(v) for v in result.values()):
        raise ValueError('Pricing inputs exceed numerical range')
    return result


def pricing(config: PricingConfig, cancel=lambda: False, progress=lambda *_: None):
    if cancel():
        raise InterruptedError()
    def at(spot):
        return values(spot, config.strike, config.maturity_years, config.rate,
                      config.volatility, config.option_type)
    surface = [{'spot': config.spot*(.5+i*.01), **at(config.spot*(.5+i*.01))} for i in range(101)]
    progress(1, 1)
    return dict(name='European option pricing', synthetic=False,
                results={'Pricing': {'metrics': at(config.spot), 'sensitivities': surface}},
                charts=[dict(table='sensitivities', section='Pricing', keys=['price'], x='spot',
                             label='Theoretical option price versus spot'),
                        dict(table='sensitivities', section='Pricing', keys=['delta'], x='spot',
                             label='Delta versus spot')],
                limitations=['Black–Scholes theoretical values: European exercise, constant volatility/rate, no dividends or transaction costs. These are not observed quotes.',
                             'Per underlying unit. Vega and rho are per 1.00 change; theta is per year. Null denotes an undefined boundary Greek. Half delta is a convention at the payoff kink.'])
