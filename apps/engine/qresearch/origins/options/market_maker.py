"""End-to-end market making simulation for a simplified options exchange."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from math import ceil, floor, sqrt
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

try:
    from .black_scholes import OptionType, black_scholes_price
    from .delta_hedger import DeltaHedger, DeltaHedgerConfig, HedgeTrade
    from .gbm_simulator import GBMConfig, GBMSimulator
    from .greeks import Greeks, black_scholes_greeks
    from .order_flow import Order, OrderFlowConfig, OrderFlowSimulator
    from .pnl_analysis import compute_performance_metrics, plot_market_making_dashboard, save_results
except ImportError:  # pragma: no cover - supports direct script execution.
    from black_scholes import OptionType, black_scholes_price
    from delta_hedger import DeltaHedger, DeltaHedgerConfig, HedgeTrade
    from gbm_simulator import GBMConfig, GBMSimulator
    from greeks import Greeks, black_scholes_greeks
    from order_flow import Order, OrderFlowConfig, OrderFlowSimulator
    from pnl_analysis import compute_performance_metrics, plot_market_making_dashboard, save_results


@dataclass(frozen=True)
class Quote:
    """Displayed option quote."""

    step: int
    time_years: float
    bid: float
    ask: float
    mid: float
    fair_value: float
    spread: float
    inventory_skew: float


@dataclass(frozen=True)
class OptionTrade:
    """Executed option trade from the market maker's perspective."""

    step: int
    time_years: float
    customer_side: str
    quantity: int
    price: float
    fair_value: float
    cash_flow: float
    option_inventory_after: int


@dataclass(frozen=True)
class MarketMakerConfig:
    """Quote construction, inventory control, and fee parameters."""

    base_spread_bps: float = 35.0
    min_spread: float = 0.03
    tick_size: float = 0.01
    inventory_skew: float = 0.12
    inventory_spread_penalty: float = 0.10
    max_inventory: int = 250
    exchange_fee_per_contract: float = 0.02
    multiplier: int = 100


@dataclass(frozen=True)
class SimulationConfig:
    """High-level settings for the market making experiment."""

    seed: int = 42
    initial_spot: float = 100.0
    strike: float = 100.0
    option_type: OptionType = "call"
    risk_free_rate: float = 0.02
    volatility: float = 0.22
    drift: float = 0.04
    maturity_years: float = 30.0 / 252.0
    trading_days: int = 10
    steps_per_day: int = 78

    @property
    def dt(self) -> float:
        return 1.0 / (252.0 * self.steps_per_day)

    @property
    def n_steps(self) -> int:
        return self.trading_days * self.steps_per_day


class MarketMaker:
    """Continuously quote an option and manage the resulting inventory."""

    def __init__(self, config: MarketMakerConfig):
        if config.tick_size <= 0.0:
            raise ValueError("tick_size must be positive")
        if config.max_inventory <= 0:
            raise ValueError("max_inventory must be positive")
        self.config = config
        self.option_inventory = 0
        self.cash = 0.0

    def make_quote(
        self,
        step: int,
        time_years: float,
        fair_value: float,
    ) -> Quote:
        """Create a bid/ask quote around fair value with inventory-aware skew."""

        inventory_ratio = max(
            -1.5,
            min(1.5, self.option_inventory / max(1.0, float(self.config.max_inventory))),
        )
        inventory_skew = -self.config.inventory_skew * inventory_ratio * max(fair_value, 1.0)
        raw_spread = max(
            self.config.min_spread,
            fair_value * self.config.base_spread_bps / 10_000.0
            + abs(inventory_ratio) * self.config.inventory_spread_penalty * max(fair_value, 1.0),
        )

        raw_mid = max(self.config.tick_size, fair_value + inventory_skew)
        raw_bid = max(self.config.tick_size, raw_mid - 0.5 * raw_spread)
        raw_ask = max(raw_bid + self.config.tick_size, raw_mid + 0.5 * raw_spread)
        bid = self._floor_to_tick(raw_bid)
        ask = self._ceil_to_tick(raw_ask)
        if ask <= bid:
            ask = bid + self.config.tick_size
        mid = 0.5 * (bid + ask)

        return Quote(
            step=step,
            time_years=time_years,
            bid=bid,
            ask=ask,
            mid=mid,
            fair_value=fair_value,
            spread=ask - bid,
            inventory_skew=inventory_skew,
        )

    def execute_order(self, order: Order, quote: Quote) -> Optional[OptionTrade]:
        """Execute a customer order if the hard inventory limit allows it."""

        inventory_change = -order.quantity if order.side == "buy" else order.quantity
        projected_inventory = self.option_inventory + inventory_change
        if abs(projected_inventory) > self.config.max_inventory:
            return None

        price = quote.ask if order.side == "buy" else quote.bid
        signed_cash_flow = (
            price * order.quantity * self.config.multiplier
            if order.side == "buy"
            else -price * order.quantity * self.config.multiplier
        )
        fees = order.quantity * self.config.exchange_fee_per_contract
        self.cash += signed_cash_flow - fees
        self.option_inventory = projected_inventory

        return OptionTrade(
            step=order.step,
            time_years=order.time_years,
            customer_side=order.side,
            quantity=order.quantity,
            price=price,
            fair_value=order.fair_value,
            cash_flow=signed_cash_flow - fees,
            option_inventory_after=self.option_inventory,
        )

    def _floor_to_tick(self, price: float) -> float:
        return floor(price / self.config.tick_size) * self.config.tick_size

    def _ceil_to_tick(self, price: float) -> float:
        return ceil(price / self.config.tick_size) * self.config.tick_size


@dataclass(frozen=True)
class SimulationResult:
    """Container returned by the simulation runner."""

    state: pd.DataFrame
    trades: pd.DataFrame
    hedges: pd.DataFrame
    metrics: Dict[str, float]
    plot_paths: List[Path]


def run_market_making_simulation(
    simulation_config: Optional[SimulationConfig] = None,
    market_maker_config: Optional[MarketMakerConfig] = None,
    order_flow_config: Optional[OrderFlowConfig] = None,
    hedger_config: Optional[DeltaHedgerConfig] = None,
    results_dir: Optional[Path] = None,
    plots_dir: Optional[Path] = None,
    persist_outputs: bool = True,
) -> SimulationResult:
    """Run the full stock, option quoting, order flow, hedging, and PnL loop."""

    sim_cfg = simulation_config or SimulationConfig()
    mm_cfg = market_maker_config or MarketMakerConfig()
    flow_cfg = order_flow_config or OrderFlowConfig(seed=sim_cfg.seed + 101)
    hedge_cfg = hedger_config or DeltaHedgerConfig()

    repo_root = Path(__file__).resolve().parents[1]
    results_dir = results_dir or repo_root / "results"
    plots_dir = plots_dir or repo_root / "plots"

    gbm_config = GBMConfig(
        initial_price=sim_cfg.initial_spot,
        drift=sim_cfg.drift,
        volatility=sim_cfg.volatility,
        dt=sim_cfg.dt,
        n_steps=sim_cfg.n_steps,
        seed=sim_cfg.seed,
        realized_vol_window=max(5, sim_cfg.steps_per_day // 2),
    )
    stock_path = GBMSimulator(gbm_config).simulate_path()
    market_maker = MarketMaker(mm_cfg)
    order_flow = OrderFlowSimulator(flow_cfg)
    hedger = DeltaHedger(hedge_cfg)

    state_rows: list[dict] = []
    trade_rows: list[dict] = []
    hedge_rows: list[dict] = []

    for row in stock_path.itertuples(index=False):
        step = int(row.step)
        spot = float(row.spot)
        time_years = float(row.time_years)
        time_to_maturity = max(sim_cfg.maturity_years - time_years, 0.0)
        fair_value = black_scholes_price(
            spot=spot,
            strike=sim_cfg.strike,
            time_to_maturity=time_to_maturity,
            risk_free_rate=sim_cfg.risk_free_rate,
            volatility=sim_cfg.volatility,
            option_type=sim_cfg.option_type,
        )
        greeks = black_scholes_greeks(
            spot=spot,
            strike=sim_cfg.strike,
            time_to_maturity=time_to_maturity,
            risk_free_rate=sim_cfg.risk_free_rate,
            volatility=sim_cfg.volatility,
            option_type=sim_cfg.option_type,
        )

        quote = market_maker.make_quote(
            step=step,
            time_years=time_years,
            fair_value=fair_value,
        )
        directional_signal = float(row.log_return) / max(sim_cfg.volatility * sqrt(sim_cfg.dt), 1.0e-12)
        order = order_flow.generate_order(
            step=step,
            time_years=time_years,
            quote=quote,
            fair_value=fair_value,
            directional_signal=directional_signal,
        )
        if order is not None:
            trade = market_maker.execute_order(order, quote)
            if trade is not None:
                trade_rows.append(asdict(trade))

        hedge_trade = hedger.rebalance(
            step=step,
            time_years=time_years,
            spot=spot,
            option_inventory=market_maker.option_inventory,
            option_delta=greeks.delta,
            multiplier=mm_cfg.multiplier,
        )
        if hedge_trade is not None:
            hedge_rows.append(_hedge_trade_to_dict(hedge_trade))

        option_market_value = market_maker.option_inventory * fair_value * mm_cfg.multiplier
        stock_market_value = hedger.stock_position * spot
        cash = market_maker.cash + hedger.cash
        portfolio_value = cash + option_market_value + stock_market_value
        net_delta = DeltaHedger.net_delta(
            option_inventory=market_maker.option_inventory,
            option_delta=greeks.delta,
            stock_position=hedger.stock_position,
            multiplier=mm_cfg.multiplier,
        )

        state_rows.append(
            {
                "step": step,
                "time_years": time_years,
                "spot": spot,
                "log_return": float(row.log_return),
                "realized_volatility": float(row.realized_volatility),
                "time_to_maturity": time_to_maturity,
                "option_fair_value": fair_value,
                "option_bid": quote.bid,
                "option_ask": quote.ask,
                "option_mid": quote.mid,
                "option_spread": quote.spread,
                "option_delta": greeks.delta,
                "option_gamma": greeks.gamma,
                "option_vega": greeks.vega,
                "option_theta": greeks.theta,
                "option_rho": greeks.rho,
                "option_inventory": market_maker.option_inventory,
                "stock_position": hedger.stock_position,
                "net_delta": net_delta,
                "hedge_error": net_delta,
                "option_cash": market_maker.cash,
                "hedge_cash": hedger.cash,
                "cash": cash,
                "option_market_value": option_market_value,
                "stock_market_value": stock_market_value,
                "gross_exposure": abs(option_market_value) + abs(stock_market_value),
                "portfolio_value": portfolio_value,
            }
        )

    state = pd.DataFrame(state_rows)
    trades = pd.DataFrame(trade_rows)
    hedges = pd.DataFrame(hedge_rows)
    metrics = compute_performance_metrics(state, sim_cfg.dt)
    plot_paths: list[Path] = []

    if persist_outputs:
        save_results(state, trades, hedges, metrics, results_dir)
        stock_path.to_csv(results_dir / "gbm_stock_path.csv", index=False)
        plot_paths = list(plot_market_making_dashboard(state, trades, plots_dir))

    return SimulationResult(
        state=state,
        trades=trades,
        hedges=hedges,
        metrics=metrics,
        plot_paths=plot_paths,
    )


def _hedge_trade_to_dict(hedge_trade: HedgeTrade) -> dict:
    return {
        "step": hedge_trade.step,
        "time_years": hedge_trade.time_years,
        "spot": hedge_trade.spot,
        "shares": hedge_trade.shares,
        "transaction_cost": hedge_trade.transaction_cost,
        "stock_position_after": hedge_trade.stock_position_after,
        "cash_after": hedge_trade.cash_after,
        "pre_trade_delta": hedge_trade.pre_trade_delta,
        "post_trade_delta": hedge_trade.post_trade_delta,
    }


def main() -> None:
    """CLI entry point."""

    result = run_market_making_simulation()
    print("Simulation complete")
    print(f"Steps: {len(result.state):,}")
    print(f"Option trades: {len(result.trades):,}")
    print(f"Hedge trades: {len(result.hedges):,}")
    print(f"Total PnL: {result.metrics['total_pnl']:.2f}")
    print(f"Sharpe ratio: {result.metrics['sharpe_ratio']:.2f}")
    print("Outputs written to results/ and plots/")


if __name__ == "__main__":
    main()
