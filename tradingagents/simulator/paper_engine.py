"""Paper trading engine — portfolio tracking, live ticks, adaptive strategy switching."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from tradingagents.backtest import (
    LookbackWindow,
    OptimizationResult,
    compute_strategy_signal,
    optimize_strategies,
)
from tradingagents.backtest.matcher import SimulatedMatcher
from tradingagents.backtest.portfolio import VirtualPortfolio
from tradingagents.dataflows.config import get_config
from tradingagents.dataflows.dummy_feed import DummyPriceFeed
from tradingagents.dataflows.live_prices import LivePrice, PriceSource, fetch_live_spot_price
from tradingagents.simulator.adaptive import AdaptiveStrategyMonitor
from tradingagents.simulator.core import (
    PaperTradingSession,
    StrategySignal,
    TickEvaluationResult,
    evaluate_live_market_tick,
)
from tradingagents.simulator.persistence import (
    load_paper_session,
    restore_portfolio,
    save_paper_session,
)

logger = logging.getLogger(__name__)


@dataclass
class PaperTradingState:
    """Serializable snapshot of a running paper session."""

    symbol: str
    strategy_name: str
    lookback: str
    signal: str
    equity: float
    cash: float
    initial_equity: float
    pnl: float
    pnl_pct: float
    price: float
    price_source: str
    drawdown_pct: float
    rebacktest_count: int
    open_position: Optional[str] = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class PaperTradingEngine:
    """Runs simulated trades on live prices with optional adaptive re-backtest."""

    def __init__(
        self,
        session: PaperTradingSession,
        config: Optional[dict] = None,
        *,
        adaptive_enabled: bool = True,
        on_state_change: Optional[Callable[[PaperTradingState], None]] = None,
        on_strategy_switch: Optional[Callable[[str, str], None]] = None,
    ) -> None:
        self.session = session
        self.config = config or get_config()
        self.adaptive_enabled = adaptive_enabled
        self.on_state_change = on_state_change
        self.on_strategy_switch = on_strategy_switch

        equity = session.initial_equity or float(self.config.get("paper_initial_equity", 100_000.0))
        fee_bps = float(session.slippage_bps)
        self.portfolio = VirtualPortfolio(initial_equity=equity, fee_bps=fee_bps)
        self._restore_persisted_session()
        self.matcher = SimulatedMatcher(slippage_bps=session.slippage_bps, portfolio=self.portfolio)
        self._dummy_feed: Optional[DummyPriceFeed] = None
        self._tick_history: List[TickEvaluationResult] = []
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._signals_halted = False

        review_minutes = float(
            self.config.get(
                "drawdown_time_window_minutes",
                self.config.get("paper_loss_review_minutes", 60),
            )
        )
        threshold_pct = float(
            self.config.get(
                "max_allowed_drawdown_pct",
                self.config.get("paper_loss_threshold_pct", 5.0),
            )
        )
        self._adaptive = AdaptiveStrategyMonitor(
            loss_review_minutes=review_minutes,
            loss_threshold_pct=threshold_pct,
            initial_equity=self.portfolio.initial_equity,
        )

    @property
    def tick_history(self) -> List[TickEvaluationResult]:
        return list(self._tick_history)

    def _ensure_dummy_feed(self, anchor: float) -> None:
        if self._dummy_feed is None:
            self._dummy_feed = DummyPriceFeed(anchor_price=anchor, symbol=self.session.symbol)

    def _fetch_price(self) -> LivePrice:
        quote = fetch_live_spot_price(self.session.symbol, self.config)
        if quote.source == PriceSource.PLACEHOLDER:
            self._ensure_dummy_feed(quote.price)
            quote = LivePrice(
                symbol=quote.symbol,
                price=float(self._dummy_feed.fetch_ticker()["last"]),  # type: ignore[union-attr]
                source=PriceSource.PLACEHOLDER,
                timestamp=datetime.now(timezone.utc),
            )
        return quote

    def refresh_signal(self) -> StrategySignal:
        """Recompute strategy signal from latest historical candles."""
        raw = compute_strategy_signal(
            self.session.symbol,
            self.session.strategy_name,
            self.session.parameters,
            self.session.lookback,
        )
        signal = StrategySignal.from_string(raw)
        self.session.signal = signal
        return signal

    def _restore_persisted_session(self) -> None:
        if not self.config.get("paper_state_persistence", True):
            return
        saved = load_paper_session(self.session.symbol, self.config)
        if not saved:
            return
        self.portfolio = restore_portfolio(saved)
        self.session.strategy_name = saved.get("strategy_name", self.session.strategy_name)
        self.session.lookback = saved.get("lookback", self.session.lookback)
        self.session.parameters = dict(saved.get("parameters") or self.session.parameters)
        self.session.signal = StrategySignal.from_string(saved.get("signal", self.session.signal.value))

    def _persist_session(self, quote: LivePrice) -> None:
        if not self.config.get("paper_state_persistence", True):
            return
        save_paper_session(
            symbol=self.session.symbol,
            strategy_name=self.session.strategy_name,
            lookback=self.session.lookback,
            signal=self.session.signal.value,
            portfolio=self.portfolio,
            parameters=self.session.parameters,
            extra={"price": quote.price, "price_source": quote.source.value},
            config=self.config,
        )

    def _log_autonomous_rotation(self, old_name: str, new_name: str) -> None:
        message = (
            f"[AUTONOMOUS ROTATION]: Strategy changed from [{old_name}] to [{new_name}] "
            "due to threshold violation."
        )
        logger.warning(message)
        log_dir = self.config.get("results_dir")
        if log_dir:
            from pathlib import Path

            path = Path(log_dir) / "paper_rotation.log"
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(f"{datetime.now(timezone.utc).isoformat()} {message}\n")

    def tick(self) -> TickEvaluationResult:
        """Execute one paper-trading tick: price fetch, signal refresh, fill."""
        quote = self._fetch_price()
        signal = self.refresh_signal() if not self._signals_halted else StrategySignal.FLAT
        result = evaluate_live_market_tick(
            self.portfolio,
            quote.price,
            signal,
            asset=self.session.symbol,
            matcher=self.matcher,
            stop_loss_pct=self.session.stop_loss_pct,
            slippage_bps=self.session.slippage_bps,
        )
        self._tick_history.append(result)
        self._adaptive.record_equity(result.portfolio_equity, result.timestamp)

        if self.adaptive_enabled and self._adaptive.should_rebacktest(result.timestamp):
            self._run_adaptive_rebacktest(result.timestamp)

        state = self.get_state(quote)
        self._persist_session(quote)
        if self.on_state_change:
            self.on_state_change(state)
        return result

    def _run_adaptive_rebacktest(self, now: datetime) -> None:
        """Re-run optimization and switch strategy when a better one is found."""
        end_date = now.strftime("%Y-%m-%d")
        logger.info(
            "Adaptive re-backtest triggered for %s (drawdown %.2f%%)",
            self.session.symbol,
            self._adaptive.current_drawdown_pct(),
        )
        self._signals_halted = True
        try:
            optimization = optimize_strategies(self.session.symbol, end_date)
        except Exception as exc:
            logger.warning("Adaptive re-backtest failed: %s", exc)
            self._signals_halted = False
            return

        if optimization.winner is None:
            self._adaptive.mark_rebacktest_done()
            self._signals_halted = False
            return

        old_name = self.session.strategy_name
        new_name = optimization.winner.strategy_name
        if new_name != old_name:
            self.session.strategy_name = new_name
            self.session.parameters = dict(optimization.winner.parameters)
            self.session.lookback = optimization.winner.lookback
            self.session.signal = StrategySignal.from_string(
                compute_strategy_signal(
                    self.session.symbol,
                    new_name,
                    optimization.winner.parameters,
                    optimization.winner.lookback,
                    end_date,
                )
            )
            if self.on_strategy_switch:
                self.on_strategy_switch(old_name, new_name)
            self._log_autonomous_rotation(old_name, new_name)

        self._adaptive.mark_rebacktest_done()
        self._signals_halted = False

    def get_state(self, quote: Optional[LivePrice] = None) -> PaperTradingState:
        """Current portfolio and session snapshot."""
        if quote is None:
            quote = self._fetch_price()
        pos_desc = None
        if self.session.symbol in self.portfolio.positions:
            pos = self.portfolio.positions[self.session.symbol]
            pos_desc = "long" if pos["side"] > 0 else "short"
        pnl = self.portfolio.equity - self.portfolio.initial_equity
        pnl_pct = (pnl / self.portfolio.initial_equity * 100.0) if self.portfolio.initial_equity else 0.0
        return PaperTradingState(
            symbol=self.session.symbol,
            strategy_name=self.session.strategy_name,
            lookback=self.session.lookback,
            signal=self.session.signal.value,
            equity=self.portfolio.equity,
            cash=self.portfolio.cash,
            initial_equity=self.portfolio.initial_equity,
            pnl=pnl,
            pnl_pct=pnl_pct,
            price=quote.price,
            price_source=quote.source.value,
            drawdown_pct=self._adaptive.current_drawdown_pct(),
            rebacktest_count=self._adaptive.rebacktest_count,
            open_position=pos_desc,
        )

    def run_loop(
        self,
        *,
        interval_seconds: Optional[float] = None,
        max_ticks: Optional[int] = None,
        on_tick: Optional[Callable[[TickEvaluationResult], None]] = None,
    ) -> None:
        """Blocking poll loop until ``max_ticks`` or stop requested."""
        interval = interval_seconds or float(self.config.get("paper_tick_interval_seconds", 10.0))
        ticks = 0
        while not self._stop_event.is_set():
            result = self.tick()
            if on_tick:
                on_tick(result)
            ticks += 1
            if max_ticks is not None and ticks >= max_ticks:
                break
            time.sleep(interval)

    def start_background(
        self,
        *,
        interval_seconds: Optional[float] = None,
        max_ticks: Optional[int] = None,
        on_tick: Optional[Callable[[TickEvaluationResult], None]] = None,
    ) -> threading.Thread:
        """Start paper trading in a daemon thread."""
        self._stop_event.clear()

        def _runner() -> None:
            try:
                self.run_loop(
                    interval_seconds=interval_seconds,
                    max_ticks=max_ticks,
                    on_tick=on_tick,
                )
            except Exception as exc:
                logger.exception("Paper trading engine failed: %s", exc)

        self._thread = threading.Thread(
            target=_runner,
            name=f"paper-engine-{self.session.symbol}",
            daemon=True,
        )
        self._thread.start()
        return self._thread

    def stop(self) -> None:
        self._stop_event.set()


def session_from_optimization(
    optimization: OptimizationResult,
    config: Optional[dict] = None,
) -> PaperTradingSession:
    """Build a paper session from backtest optimization winner."""
    cfg = config or get_config()
    if optimization.winner is None:
        raise ValueError("No winning strategy to deploy")
    signal = compute_strategy_signal(
        optimization.symbol,
        optimization.winner.strategy_name,
        optimization.winner.parameters,
        optimization.winner.lookback,
        optimization.end_date,
    )
    return PaperTradingSession(
        symbol=optimization.symbol,
        strategy_name=optimization.winner.strategy_name,
        signal=StrategySignal.from_string(signal),
        parameters=dict(optimization.winner.parameters),
        lookback=optimization.winner.lookback,
        initial_equity=float(cfg.get("paper_initial_equity", 10_000.0)),
    )
