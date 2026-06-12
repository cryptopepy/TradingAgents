"""Mathematical strategy backtesting (no LLM)."""

from .engine import (
    BacktestResult,
    LookbackWindow,
    TradeRecord,
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
from .schemas import OptimizationResult, StrategyMetrics, WinningStrategySummary
from .strategies import DEFAULT_STRATEGIES

__all__ = [
    "BacktestResult",
    "DEFAULT_STRATEGIES",
    "LookbackWindow",
    "OptimizationResult",
    "StrategyMetrics",
    "TradeRecord",
    "WinningStrategySummary",
    "deploy_winning_strategy",
    "fetch_historical_crypto",
    "fetch_historical_price_slice",
    "fetch_live_price",
    "format_optimization_summary",
    "is_live_mode",
    "optimize_strategies",
    "run_strategy_backtest",
    "run_strategy_on_frame",
]
