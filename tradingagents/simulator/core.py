"""Paper-trading simulator — tick evaluation and optional polling loop."""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, Optional

from pydantic import BaseModel, Field

from tradingagents.backtest.engine import fetch_live_price, is_live_mode
from tradingagents.backtest.matcher import SimulatedMatcher
from tradingagents.backtest.portfolio import Direction, PortfolioSnapshot, VirtualPortfolio

# High-fidelity paper portfolio (cash, margin, fees) — shared with backtest matcher.
__all__ = [
    "AssetPosition",
    "PaperTradingSession",
    "PortfolioSnapshot",
    "StrategySignal",
    "TickEvaluationResult",
    "VirtualPortfolio",
    "evaluate_live_market_tick",
    "run_polling_loop",
    "start_paper_trading_scaffold",
]
from tradingagents.dataflows.config import get_config
from tradingagents.dataflows.dummy_feed import DummyPriceFeed

logger = logging.getLogger(__name__)


class StrategySignal(str, Enum):
    LONG = "long"
    SHORT = "short"
    FLAT = "flat"

    @classmethod
    def from_string(cls, value: str) -> "StrategySignal":
        normalized = (value or "flat").strip().lower()
        for member in cls:
            if member.value == normalized:
                return member
        return cls.FLAT


class AssetPosition(BaseModel):
    """Open position snapshot for the paper simulator."""

    asset: str
    side: StrategySignal
    size: float
    entry_price: float
    stop_loss_pct: float = 0.02
    unrealized_pnl: float = 0.0


class TickEvaluationResult(BaseModel):
    """Outcome of a single live tick evaluation."""

    timestamp: datetime
    price: float
    signal: StrategySignal
    action_taken: str
    portfolio_equity: float
    position: Optional[AssetPosition] = None
    stop_loss_triggered: bool = False


class PaperTradingSession(BaseModel):
    """Configuration for a paper-trading run."""

    symbol: str
    strategy_name: str
    signal: StrategySignal = StrategySignal.FLAT
    parameters: Dict[str, Any] = Field(default_factory=dict)
    lookback: str = "24h"
    stop_loss_pct: float = 0.02
    slippage_bps: float = 10.0
    initial_equity: float = 1.0


def _position_from_portfolio(
    portfolio: VirtualPortfolio,
    asset: str,
    price: float,
    stop_loss_pct: float,
) -> Optional[AssetPosition]:
    pos = portfolio.positions.get(asset)
    if not pos:
        return None
    side = StrategySignal.LONG if pos["side"] > 0 else StrategySignal.SHORT
    move = (price - pos["entry_price"]) / pos["entry_price"]
    if pos["side"] < 0:
        move = -move
    notional_base = portfolio.initial_equity * pos.get("sizing_pct", 1.0)
    upnl = notional_base * move * pos.get("leverage", 1.0)
    return AssetPosition(
        asset=asset,
        side=side,
        size=float(pos["size"]),
        entry_price=float(pos["entry_price"]),
        stop_loss_pct=stop_loss_pct,
        unrealized_pnl=upnl,
    )


def _stop_loss_breached(
    portfolio: VirtualPortfolio,
    asset: str,
    price: float,
    stop_loss_pct: float,
) -> bool:
    pos = portfolio.positions.get(asset)
    if not pos:
        return False
    move = (price - pos["entry_price"]) / pos["entry_price"]
    if pos["side"] < 0:
        move = -move
    return move <= -stop_loss_pct


def evaluate_live_market_tick(
    portfolio: VirtualPortfolio,
    current_tick_price: float,
    winning_strategy_signal: str | StrategySignal,
    *,
    asset: str,
    matcher: Optional[SimulatedMatcher] = None,
    stop_loss_pct: float = 0.02,
    slippage_bps: float = 10.0,
) -> TickEvaluationResult:
    """Apply one market tick: stop-loss, signal entry/exit, fees via matcher slippage."""
    signal = (
        winning_strategy_signal
        if isinstance(winning_strategy_signal, StrategySignal)
        else StrategySignal.from_string(winning_strategy_signal)
    )
    sim = matcher or SimulatedMatcher(
        slippage_bps=slippage_bps,
        portfolio=portfolio,
    )
    if sim.portfolio is not portfolio:
        sim.portfolio = portfolio

    now = datetime.now(timezone.utc)
    price = float(current_tick_price)
    action = "hold"
    stop_triggered = False

    portfolio.mark_to_market({asset: price})

    if _stop_loss_breached(portfolio, asset, price, stop_loss_pct):
        from tradingagents.backtest.portfolio import TransactionIntent

        sim.submit_intent(
            TransactionIntent(timestamp=now, asset=asset, direction=Direction.EXIT),
            reference_price=price,
        )
        action = "stop_loss_exit"
        stop_triggered = True
    else:
        open_side = None
        pos = portfolio.positions.get(asset)
        if pos:
            open_side = StrategySignal.LONG if pos["side"] > 0 else StrategySignal.SHORT

        from tradingagents.backtest.portfolio import TransactionIntent

        if signal == StrategySignal.FLAT and open_side is not None:
            sim.submit_intent(
                TransactionIntent(timestamp=now, asset=asset, direction=Direction.EXIT),
                reference_price=price,
            )
            action = "signal_exit"
        elif signal == StrategySignal.LONG and open_side != StrategySignal.LONG:
            if open_side is not None:
                sim.submit_intent(
                    TransactionIntent(timestamp=now, asset=asset, direction=Direction.EXIT),
                    reference_price=price,
                )
            sim.submit_intent(
                TransactionIntent(timestamp=now, asset=asset, direction=Direction.LONG),
                reference_price=price,
            )
            action = "enter_long"
        elif signal == StrategySignal.SHORT and open_side != StrategySignal.SHORT:
            if open_side is not None:
                sim.submit_intent(
                    TransactionIntent(timestamp=now, asset=asset, direction=Direction.EXIT),
                    reference_price=price,
                )
            sim.submit_intent(
                TransactionIntent(timestamp=now, asset=asset, direction=Direction.SHORT),
                reference_price=price,
            )
            action = "enter_short"
        else:
            action = "hold"

    portfolio.mark_to_market({asset: price})
    position = _position_from_portfolio(portfolio, asset, price, stop_loss_pct)

    return TickEvaluationResult(
        timestamp=now,
        price=price,
        signal=signal,
        action_taken=action,
        portfolio_equity=portfolio.equity,
        position=position,
        stop_loss_triggered=stop_triggered,
    )


def _fetch_tick_price(symbol: str, config: Optional[dict], dummy_feed: Optional[DummyPriceFeed]) -> float:
    cfg = config or get_config()
    if is_live_mode(cfg):
        return fetch_live_price(symbol, cfg)
    if dummy_feed is not None:
        return float(dummy_feed.fetch_ticker()["last"])
    return fetch_live_price(symbol, cfg)


def run_polling_loop(
    session: PaperTradingSession,
    *,
    config: Optional[dict] = None,
    interval_seconds: float = 5.0,
    max_ticks: Optional[int] = None,
    on_tick: Optional[Callable[[TickEvaluationResult], None]] = None,
    stop_event: Optional[threading.Event] = None,
) -> None:
    """Background polling hook — ccxt when LIVE_MODE, else dummy feed."""
    cfg = config or get_config()
    portfolio = VirtualPortfolio(initial_equity=session.initial_equity)
    matcher = SimulatedMatcher(slippage_bps=session.slippage_bps, portfolio=portfolio)
    dummy_feed: Optional[DummyPriceFeed] = None
    if not is_live_mode(cfg):
        anchor = fetch_live_price(session.symbol, cfg)
        dummy_feed = DummyPriceFeed(anchor_price=anchor, symbol=session.symbol)

    ticks = 0
    while stop_event is None or not stop_event.is_set():
        price = _fetch_tick_price(session.symbol, cfg, dummy_feed)
        result = evaluate_live_market_tick(
            portfolio,
            price,
            session.signal,
            asset=session.symbol,
            matcher=matcher,
            stop_loss_pct=session.stop_loss_pct,
            slippage_bps=session.slippage_bps,
        )
        if on_tick:
            on_tick(result)
        ticks += 1
        if max_ticks is not None and ticks >= max_ticks:
            break
        time.sleep(interval_seconds)


def start_paper_trading_scaffold(
    session: PaperTradingSession,
    *,
    config: Optional[dict] = None,
    interval_seconds: float = 5.0,
    max_ticks: int = 3,
    on_tick: Optional[Callable[[TickEvaluationResult], None]] = None,
) -> threading.Thread:
    """Start paper trading in a daemon thread (CLI deploy entry point)."""
    stop_event = threading.Event()

    def _runner() -> None:
        try:
            run_polling_loop(
                session,
                config=config,
                interval_seconds=interval_seconds,
                max_ticks=max_ticks,
                on_tick=on_tick,
                stop_event=stop_event,
            )
        except Exception as exc:
            logger.exception("Paper trading loop failed: %s", exc)

    thread = threading.Thread(target=_runner, name=f"paper-{session.symbol}", daemon=True)
    thread._stop_event = stop_event  # type: ignore[attr-defined]
    thread.start()
    return thread
