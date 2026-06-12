"""Mathematical strategy backtesting (no LLM)."""

from .engine import (
    BacktestResult,
    LookbackWindow,
    fetch_historical_price_slice,
    run_strategy_backtest,
)

__all__ = [
    "BacktestResult",
    "LookbackWindow",
    "fetch_historical_price_slice",
    "run_strategy_backtest",
]
