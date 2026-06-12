"""Paper-trading simulator (no real exchange orders)."""

from .adaptive import AdaptiveStrategyMonitor
from .core import (
    AssetPosition,
    PaperTradingSession,
    StrategySignal,
    TickEvaluationResult,
    evaluate_live_market_tick,
    run_polling_loop,
    start_paper_trading_scaffold,
)
from .paper_engine import PaperTradingEngine, PaperTradingState, session_from_optimization

__all__ = [
    "AdaptiveStrategyMonitor",
    "AssetPosition",
    "PaperTradingEngine",
    "PaperTradingSession",
    "PaperTradingState",
    "StrategySignal",
    "TickEvaluationResult",
    "evaluate_live_market_tick",
    "run_polling_loop",
    "session_from_optimization",
    "start_paper_trading_scaffold",
]
