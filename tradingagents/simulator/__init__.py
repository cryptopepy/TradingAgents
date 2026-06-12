"""Paper-trading simulator scaffold (no real exchange orders)."""

from .core import (
    AssetPosition,
    PaperTradingSession,
    StrategySignal,
    TickEvaluationResult,
    evaluate_live_market_tick,
    run_polling_loop,
    start_paper_trading_scaffold,
)

__all__ = [
    "AssetPosition",
    "PaperTradingSession",
    "StrategySignal",
    "TickEvaluationResult",
    "evaluate_live_market_tick",
    "run_polling_loop",
    "start_paper_trading_scaffold",
]
