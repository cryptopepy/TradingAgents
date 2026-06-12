"""Mathematical strategy backtesting (no LLM)."""

from .engine import (
    BacktestResult,
    LookbackWindow,
    TradeRecord,
    compute_strategy_signal,
    deploy_winning_strategy,
    fetch_historical_crypto,
    fetch_historical_price_slice,
    fetch_live_price,
    format_optimization_summary,
    is_live_mode,
    optimize_strategies,
    run_strategy_backtest,
    run_strategy_on_frame,
)
from .matcher import SimulatedMatcher, build_price_feed
from .portfolio import (
    Direction,
    PortfolioSnapshot,
    TransactionIntent,
    VirtualPortfolio,
    signals_to_intents,
)
from .schemas import OptimizationResult, StrategyMetrics, WinningStrategySummary
from .strategies import DEFAULT_STRATEGIES, STRATEGY_REGISTRY, build_strategy
from .validation import (
    BacktestDataError,
    BacktestValidationError,
    require_optimization_results,
    validate_end_date,
    validate_ticker,
)

__all__ = [
    "BacktestResult",
    "BacktestDataError",
    "BacktestValidationError",
    "DEFAULT_STRATEGIES",
    "Direction",
    "LookbackWindow",
    "OptimizationResult",
    "PortfolioSnapshot",
    "STRATEGY_REGISTRY",
    "SimulatedMatcher",
    "StrategyMetrics",
    "TradeRecord",
    "TransactionIntent",
    "VirtualPortfolio",
    "WinningStrategySummary",
    "build_price_feed",
    "build_strategy",
    "compute_strategy_signal",
    "deploy_winning_strategy",
    "fetch_historical_crypto",
    "fetch_historical_price_slice",
    "fetch_live_price",
    "format_optimization_summary",
    "is_live_mode",
    "optimize_strategies",
    "require_optimization_results",
    "run_strategy_backtest",
    "run_strategy_on_frame",
    "signals_to_intents",
    "validate_end_date",
    "validate_ticker",
]
