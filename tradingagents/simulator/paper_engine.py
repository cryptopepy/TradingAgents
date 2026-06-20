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
from tradingagents.backtest.engine import _last_closed_bar_dt
from tradingagents.backtest.matcher import SimulatedMatcher
from tradingagents.backtest.portfolio import Direction, TransactionIntent, VirtualPortfolio
from tradingagents.dataflows.config import get_config
from tradingagents.resilience import DEFAULT_API_RETRY_DELAYS, retry_with_backoff_optional
from tradingagents.dataflows.dummy_feed import DummyPriceFeed
from tradingagents.dataflows.live_prices import LivePrice, PriceSource, fetch_live_spot_price, get_live_feed_router
from tradingagents.simulator.adaptive import AdaptiveStrategyMonitor, format_last_drawdown_review
from tradingagents.simulator.volatility_spike import (
    VolatilitySpikeMonitor,
    format_last_spike_review,
)
from tradingagents.simulator.core import (
    PaperTradingSession,
    StrategySignal,
    TickEvaluationResult,
    _sleep_until_stopped_or_key,
    evaluate_live_market_tick,
)
from tradingagents.simulator.persistence import (
    delete_paper_session,
    load_paper_session,
    restore_portfolio,
    save_paper_session,
)
from tradingagents.logging_setup import PAPER_RUNTIME_LOGGER
from tradingagents.simulator.paper_journal import journal_trade

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
    price_endpoint: str = ""
    vendor_failures: str = ""
    last_drawdown_review: str = "Never"
    effective_drawdown_window_minutes: float = 0.0
    spike_review_enabled: bool = False
    spike_intelligent_tuning: bool = False
    spike_status_line: str = "off"
    spike_watch_display: str = "off"
    last_spike_review: str = "Never"
    spike_review_count: int = 0
    activity_status: str = "Watching"
    adaptive_enabled: bool = False
    max_drawdown_pct: float = 5.0
    stop_loss_pct: float = 0.02
    take_profit_pct: Optional[float] = None
    open_position: Optional[str] = None
    position_entry_price: Optional[float] = None
    position_side: Optional[str] = None
    leverage: float = 1.0
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
        on_activity: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.session = session
        self.config = config or get_config()
        self.adaptive_enabled = adaptive_enabled
        self.on_state_change = on_state_change
        self.on_strategy_switch = on_strategy_switch
        self.on_activity = on_activity

        equity = session.initial_equity or float(self.config.get("paper_initial_equity", 10_000.0))
        fee_bps = float(session.slippage_bps)
        self._pending_last_drawdown_review_at: Optional[datetime] = None
        self.portfolio = VirtualPortfolio(initial_equity=equity, fee_bps=fee_bps)
        self._restore_persisted_session()
        lev = float(
            self.session.leverage
            if getattr(self.session, "leverage", None)
            else self.config.get("paper_leverage", 1.0)
        )
        self.session.leverage = lev
        self.portfolio.default_leverage = lev
        self.matcher = SimulatedMatcher(slippage_bps=0.0, portfolio=self.portfolio)
        self._dummy_feed: Optional[DummyPriceFeed] = None
        self._tick_history: List[TickEvaluationResult] = []
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._operation_lock = threading.RLock()
        self._last_signal_bar: Optional[datetime] = None
        self._bg_action_running = False
        self._signals_halted = False
        self._feed_unavailable = False
        self._last_good_quote: Optional[LivePrice] = None
        self._last_feed_warning_at: float = 0.0
        self._last_logged_price_source: Optional[str] = None
        self._price_feed_logged = False
        self._last_logged_spike_tuning: str = ""
        self._last_heartbeat_at: float = 0.0

        review_minutes = float(
            self.config.get(
                "drawdown_time_window_minutes",
                self.config.get("paper_loss_review_minutes", 60),
            )
        )
        max_lookback = float(
            self.config.get(
                "drawdown_max_lookback_minutes",
                review_minutes,
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
            max_lookback_minutes=max_lookback,
            initial_equity=self.portfolio.initial_equity,
        )
        if self._pending_last_drawdown_review_at is not None:
            self._adaptive.note_drawdown_review(self._pending_last_drawdown_review_at)
            self._pending_last_drawdown_review_at = None

        spike_on = adaptive_enabled and bool(
            self.config.get("paper_spike_review_enabled", True)
        )
        self._spike_monitor = VolatilitySpikeMonitor.from_config(
            self.config,
            lookback=self.session.lookback,
            enabled=spike_on,
            initial_equity=self.portfolio.initial_equity,
            stop_loss_pct=float(self.session.stop_loss_pct),
        )
        if spike_on:
            self._log_spike_session_start()
        if self.session.symbol in self.portfolio.positions:
            self._log_open_position_if_any(self._last_good_quote)
        PAPER_RUNTIME_LOGGER.info(
            "Engine ready symbol=%s strategy=%s equity=$%.2f cash=$%.2f positions=%d leverage=%gx",
            self.session.symbol,
            self.session.strategy_name,
            self.portfolio.equity,
            self.portfolio.cash,
            len(self.portfolio.positions),
            float(self.session.leverage or 1.0),
        )

    @property
    def tick_history(self) -> List[TickEvaluationResult]:
        return list(self._tick_history)

    def _ensure_dummy_feed(self, anchor: float) -> None:
        if self._dummy_feed is None:
            self._dummy_feed = DummyPriceFeed(anchor_price=anchor, symbol=self.session.symbol)

    def _fetch_price(self) -> Optional[LivePrice]:
        """Return a live quote, or None when all vendors failed (no mock trading)."""
        started = time.monotonic()
        delays = DEFAULT_API_RETRY_DELAYS

        def _attempt() -> LivePrice:
            quote = fetch_live_spot_price(self.session.symbol, self.config)
            if quote.source == PriceSource.PLACEHOLDER:
                raise RuntimeError("all live price vendors failed")
            return quote

        def _on_retry(attempt: int, wait: float, exc: Exception) -> None:
            PAPER_RUNTIME_LOGGER.warning(
                "Price API retry %d in %.0fs (%s)",
                attempt,
                wait,
                exc,
            )
            self._emit_activity(
                f"Price API error — retry {attempt} in {wait:.0f}s ({exc})"
            )

        quote = retry_with_backoff_optional(
            _attempt,
            delays=delays,
            on_retry=_on_retry,
            label=f"live price ({self.session.symbol})",
        )
        elapsed = time.monotonic() - started
        if quote is None:
            self._feed_unavailable = True
            PAPER_RUNTIME_LOGGER.warning(
                "Price fetch failed after %.2fs symbol=%s",
                elapsed,
                self.session.symbol,
            )
            self._log_feed_unavailable()
            return None
        self._feed_unavailable = False
        self._last_good_quote = quote
        if elapsed >= 10.0:
            PAPER_RUNTIME_LOGGER.warning(
                "Slow price fetch %.2fs source=%s price=$%.4f",
                elapsed,
                quote.source.value,
                quote.price,
            )
        else:
            PAPER_RUNTIME_LOGGER.debug(
                "Price fetch %.2fs source=%s price=$%.4f",
                elapsed,
                quote.source.value,
                quote.price,
            )
        return quote

    def _log_feed_unavailable(self, *, force: bool = False) -> None:
        now = time.monotonic()
        if not force and (now - self._last_feed_warning_at) < 60.0:
            return
        self._last_feed_warning_at = now
        detail = self._vendor_failure_summary()
        msg = "Price feed unavailable — holding position, retrying next tick"
        if detail:
            msg = f"{msg} ({detail})"
        self._emit_activity(msg)

    def _quote_for_display(self, quote: Optional[LivePrice]) -> LivePrice:
        if quote is not None:
            return quote
        if self._last_good_quote is not None:
            return self._last_good_quote
        return LivePrice(
            symbol=self.session.symbol,
            price=0.0,
            source=PriceSource.PLACEHOLDER,
            timestamp=datetime.now(timezone.utc),
            endpoint="unavailable",
        )

    def _tick_busy_skipped(self) -> TickEvaluationResult:
        """Hold the session steady while a manual action runs in the background."""
        now = datetime.now(timezone.utc)
        display = self._quote_for_display(None)
        if display.price > 0 and self.session.symbol in self.portfolio.positions:
            self.portfolio.mark_to_market({self.session.symbol: display.price})

        result = TickEvaluationResult(
            timestamp=now,
            price=display.price,
            signal=StrategySignal.FLAT,
            action_taken="busy",
            portfolio_equity=self.portfolio.equity,
        )
        self._tick_history.append(result)
        self._record_equity_samples(result.portfolio_equity, now)
        state = self.get_state(display)
        if self.on_state_change:
            self.on_state_change(state)
        return result

    def _tick_feed_unavailable(self) -> TickEvaluationResult:
        """Skip trading when vendors fail; keep session alive for the next tick."""
        now = datetime.now(timezone.utc)
        display = self._quote_for_display(None)
        if display.price > 0 and self.session.symbol in self.portfolio.positions:
            self.portfolio.mark_to_market({self.session.symbol: display.price})

        result = TickEvaluationResult(
            timestamp=now,
            price=display.price,
            signal=StrategySignal.FLAT,
            action_taken="feed_unavailable",
            portfolio_equity=self.portfolio.equity,
        )
        self._tick_history.append(result)
        self._record_equity_samples(result.portfolio_equity, now)
        state = self.get_state(display)
        if self.on_state_change:
            self.on_state_change(state)
        return result

    def refresh_signal(self, *, force: bool = False) -> StrategySignal:
        """Recompute strategy signal when a new OHLCV bar has closed."""
        lb = (
            self.session.lookback
            if isinstance(self.session.lookback, LookbackWindow)
            else LookbackWindow(str(self.session.lookback))
        )
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        bar_open = _last_closed_bar_dt(now, lb.granularity_seconds())
        if not force and self._last_signal_bar == bar_open:
            return self.session.signal
        self._last_signal_bar = bar_open
        prior_signal = self.session.signal

        delays = DEFAULT_API_RETRY_DELAYS

        def _load_signal() -> str:
            return compute_strategy_signal(
                self.session.symbol,
                self.session.strategy_name,
                self.session.parameters,
                self.session.lookback,
                config=self.config,
            )

        def _on_retry(attempt: int, wait: float, exc: Exception) -> None:
            self._emit_activity(
                f"Signal data API error — retry {attempt} in {wait:.0f}s ({exc})"
            )

        try:
            raw = retry_with_backoff_optional(
                _load_signal,
                delays=delays,
                on_retry=_on_retry,
                label=f"strategy signal ({self.session.symbol})",
            )
        except Exception as exc:
            self._emit_activity(f"Signal refresh failed — keeping last signal ({exc})")
            return self.session.signal

        if raw is None:
            self._emit_activity("Signal refresh failed after retries — keeping last signal")
            return self.session.signal

        signal = StrategySignal.from_string(raw)
        if signal != prior_signal:
            self._emit_activity(
                f"Signal updated on new bar: {prior_signal.value} → {signal.value}"
            )
        self.session.signal = signal
        return signal

    def _restore_persisted_session(self) -> None:
        self._resumed_session = False
        if not self.config.get("paper_state_persistence", True):
            return
        if self.config.get("paper_fresh_start"):
            delete_paper_session(self.session.symbol, self.config)
            return
        saved = load_paper_session(self.session.symbol, self.config)
        if not saved:
            return
        self._resumed_session = True
        self.portfolio = restore_portfolio(saved)
        self.session.strategy_name = saved.get("strategy_name", self.session.strategy_name)
        self.session.lookback = saved.get("lookback", self.session.lookback)
        self.session.parameters = dict(saved.get("parameters") or self.session.parameters)
        self.session.signal = StrategySignal.from_string(saved.get("signal", self.session.signal.value))
        extra = saved.get("extra") or {}
        last_review = extra.get("last_drawdown_review_at")
        if last_review:
            try:
                parsed = datetime.fromisoformat(str(last_review).replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                self._pending_last_drawdown_review_at = parsed
            except ValueError:
                logger.warning("Ignoring invalid last_drawdown_review_at: %s", last_review)

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
            extra={
                "price": quote.price,
                "price_source": quote.source.value,
                "last_drawdown_review_at": (
                    self._adaptive.last_drawdown_review_at.isoformat()
                    if self._adaptive.last_drawdown_review_at is not None
                    else None
                ),
            },
            config=self.config,
        )

    def _emit_activity(self, message: str) -> None:
        if self.on_activity and message:
            self.on_activity(message)

    def _vendor_failure_summary(self) -> str:
        router = get_live_feed_router(self.config)
        from tradingagents.simulator.activity_messages import format_vendor_failures

        failures = format_vendor_failures(router.last_spot_attempts)
        return "; ".join(failures[:4])

    def _log_price_feed(self, quote: LivePrice) -> None:
        source = quote.source.value
        failures = self._vendor_failure_summary()
        source_key = f"{source}|{quote.endpoint or ''}|{failures}"
        if self._price_feed_logged and source_key == getattr(self, "_last_price_feed_key", ""):
            return
        from tradingagents.simulator.activity_messages import format_price_feed, format_vendor_failures

        router = get_live_feed_router(self.config)
        fail_lines = format_vendor_failures(router.last_spot_attempts)
        self._emit_activity(
            format_price_feed(
                source,
                quote.price,
                endpoint=quote.endpoint,
                failures=fail_lines or None,
                first=not self._price_feed_logged,
            )
        )
        self._last_logged_price_source = source
        self._last_price_feed_key = source_key
        self._price_feed_logged = True

    def _log_tick_action(self, result: TickEvaluationResult) -> None:
        if result.action_taken == "hold":
            return
        from tradingagents.simulator.activity_messages import format_tick_action

        lev = float(self.session.leverage or 1.0)
        message = format_tick_action(
            result.action_taken,
            result.price,
            result.portfolio_equity,
            leverage=lev,
        )
        PAPER_RUNTIME_LOGGER.info(
            "Trade action=%s equity=$%.2f price=$%.4f leverage=%gx",
            result.action_taken,
            result.portfolio_equity,
            result.price,
            lev,
        )
        journal_trade(message)
        self._emit_activity(message)

    def _log_open_position_if_any(self, quote: Optional[LivePrice] = None) -> None:
        if self.session.symbol not in self.portfolio.positions:
            return
        from tradingagents.simulator.activity_messages import format_open_position_line

        pos = self.portfolio.positions[self.session.symbol]
        side = "long" if pos["side"] > 0 else "short"
        price = quote.price if quote else float(pos.get("entry_price", 0.0))
        lev = float(pos.get("leverage", self.session.leverage or 1.0))
        message = format_open_position_line(
            side=side,
            price=price,
            equity=self.portfolio.equity,
            leverage=lev,
            entry_price=float(pos.get("entry_price", 0.0)),
        )
        journal_trade(message)
        self._emit_activity(message)

    def _log_backtest_activity(self, message: str) -> None:
        self._emit_activity(message)

    def _log_autonomous_rotation(self, old_name: str, new_name: str) -> None:
        from tradingagents.simulator.activity_messages import format_strategy_switch

        message = format_strategy_switch(old_name, new_name)
        logger.warning("[AUTONOMOUS ROTATION]: %s", message)
        self._emit_activity(message)
        log_dir = self.config.get("results_dir")
        if log_dir:
            from pathlib import Path

            path = Path(log_dir) / "paper_rotation.log"
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(
                    f"{datetime.now(timezone.utc).isoformat()} [AUTONOMOUS ROTATION] {message}\n"
                )

    def tick(self) -> TickEvaluationResult:
        """Execute one paper-trading tick: price fetch, signal refresh, fill."""
        if not self._operation_lock.acquire(blocking=False):
            PAPER_RUNTIME_LOGGER.debug("Tick skipped — background operation in progress")
            return self._tick_busy_skipped()
        started = time.monotonic()
        try:
            result = self._tick_locked()
            elapsed = time.monotonic() - started
            if elapsed >= 30.0:
                PAPER_RUNTIME_LOGGER.warning(
                    "Slow tick %.1fs action=%s equity=$%.2f",
                    elapsed,
                    result.action_taken,
                    result.portfolio_equity,
                )
            elif elapsed >= 5.0:
                PAPER_RUNTIME_LOGGER.info(
                    "Tick took %.1fs action=%s equity=$%.2f",
                    elapsed,
                    result.action_taken,
                    result.portfolio_equity,
                )
            return result
        finally:
            self._operation_lock.release()

    def _tick_locked(self) -> TickEvaluationResult:
        try:
            quote = self._fetch_price()
            if quote is None:
                return self._tick_feed_unavailable()
            self._log_price_feed(quote)
            signal = (
                self.refresh_signal()
                if not self._signals_halted and not self._feed_unavailable
                else StrategySignal.FLAT
            )
            result = evaluate_live_market_tick(
                self.portfolio,
                quote.price,
                signal,
                asset=self.session.symbol,
                matcher=self.matcher,
                stop_loss_pct=self.session.stop_loss_pct,
                take_profit_pct=self.session.take_profit_pct,
                slippage_bps=self.session.slippage_bps,
                sizing_pct=float(
                    self.session.position_size_pct
                    if self.session.position_size_pct != 1.0
                    else self.config.get("position_size_pct", 1.0)
                ),
                leverage=float(self.session.leverage or 1.0),
            )
            self._tick_history.append(result)
            self._log_tick_action(result)
            self._record_equity_samples(result.portfolio_equity, result.timestamp)

            if self.adaptive_enabled:
                spike = self._spike_monitor.check(result.timestamp)
                if spike is not None:
                    self._schedule_spike_rebacktest(result.timestamp, spike.reason)
                elif self._adaptive.should_rebacktest(result.timestamp):
                    self._schedule_adaptive_rebacktest(result.timestamp)

            state = self.get_state(quote)
            self._persist_session(quote)
            if self.on_state_change:
                self.on_state_change(state)
            return result
        except Exception as exc:
            logger.warning("Paper tick error — continuing next interval: %s", exc, exc_info=True)
            self._emit_activity(f"Tick error — continuing next interval ({exc})")
            return self._tick_error_skipped(exc)

    def _tick_error_skipped(self, exc: Exception) -> TickEvaluationResult:
        now = datetime.now(timezone.utc)
        display = self._quote_for_display(None)
        result = TickEvaluationResult(
            timestamp=now,
            price=display.price,
            signal=StrategySignal.FLAT,
            action_taken="error",
            portfolio_equity=self.portfolio.equity,
        )
        self._tick_history.append(result)
        self._record_equity_samples(result.portfolio_equity, now)
        state = self.get_state(display)
        if self.on_state_change:
            self.on_state_change(state)
        return result

    def _log_spike_session_start(self) -> None:
        from tradingagents.simulator.activity_messages import format_spike_session_line

        monitor = self._spike_monitor
        self._emit_activity(
            format_spike_session_line(
                enabled=monitor.enabled,
                intelligent_tuning=monitor.intelligent_tuning,
                windows=monitor.windows,
                cooldown_minutes=monitor.cooldown_minutes,
            )
        )
        self._last_logged_spike_tuning = monitor.tuning_note

    def _maybe_log_spike_activity(self, timestamp: datetime) -> None:
        if not self._spike_monitor.enabled:
            if self.adaptive_enabled:
                warning = self._adaptive.check_drawdown_warning(timestamp)
                if warning:
                    self._emit_activity(warning)
            self._maybe_log_heartbeat(timestamp)
            return
        warning = self._spike_monitor.check_proximity_warning(timestamp)
        if warning:
            self._emit_activity(warning)
        elif self.adaptive_enabled:
            dd_warning = self._adaptive.check_drawdown_warning(timestamp)
            if dd_warning:
                self._emit_activity(dd_warning)
        if not self._spike_monitor.intelligent_tuning:
            self._maybe_log_heartbeat(timestamp)
            return
        note = self._spike_monitor.tuning_note
        if note and note != self._last_logged_spike_tuning:
            from tradingagents.simulator.activity_messages import format_spike_tuning_update

            self._last_logged_spike_tuning = note
            self._emit_activity(
                format_spike_tuning_update(note, self._spike_monitor.windows)
            )
        self._maybe_log_heartbeat(timestamp)

    def _maybe_log_heartbeat(self, timestamp: datetime) -> None:
        interval = float(self.config.get("paper_status_heartbeat_minutes", 10.0))
        if interval <= 0:
            return
        now_mono = time.monotonic()
        if self._last_heartbeat_at and (now_mono - self._last_heartbeat_at) < interval * 60.0:
            return
        self._last_heartbeat_at = now_mono
        from tradingagents.simulator.activity_messages import format_session_heartbeat

        state = self.get_state()
        self._emit_activity(format_session_heartbeat(state))

    def _activity_status(self) -> str:
        if self._signals_halted:
            return "Re-analyzing — signals paused"
        if self._bg_action_running:
            return "Background action running"
        if self._feed_unavailable:
            return "Waiting for price feed"
        if self.session.symbol in self.portfolio.positions:
            pos = self.portfolio.positions[self.session.symbol]
            side = "long" if pos["side"] > 0 else "short"
            return f"Holding {side}"
        if self.session.signal != StrategySignal.FLAT:
            return f"Signal {self.session.signal.value} — flat"
        return "Watching"

    def _record_equity_samples(self, equity: float, timestamp: datetime) -> None:
        self._adaptive.record_equity(equity, timestamp)
        self._spike_monitor.record_equity(equity, timestamp)
        self._maybe_log_spike_activity(timestamp)

    def _schedule_adaptive_rebacktest(self, now: datetime) -> None:
        if self._bg_action_running:
            return

        def _worker() -> None:
            self._bg_action_running = True
            try:
                with self._operation_lock:
                    self._run_adaptive_rebacktest(now)
            except Exception as exc:
                logger.warning("Adaptive re-backtest failed — continuing: %s", exc, exc_info=True)
                self._emit_activity(f"Adaptive re-backtest failed — continuing ({exc})")
            finally:
                self._bg_action_running = False
                self._signals_halted = False

        threading.Thread(
            target=_worker,
            name=f"paper-adaptive-{self.session.symbol}",
            daemon=True,
        ).start()

    def _schedule_spike_rebacktest(self, now: datetime, reason: str) -> None:
        if self._bg_action_running:
            return
        self._spike_monitor.note_review_started(now)
        self._adaptive.note_drawdown_review(now)

        def _worker() -> None:
            self._bg_action_running = True
            try:
                with self._operation_lock:
                    self._run_spike_rebacktest(now, reason)
            except Exception as exc:
                logger.warning("Fast-move review failed — continuing: %s", exc, exc_info=True)
                self._emit_activity(f"Fast-move review failed — continuing ({exc})")
            finally:
                self._bg_action_running = False
                self._signals_halted = False

        threading.Thread(
            target=_worker,
            name=f"paper-spike-{self.session.symbol}",
            daemon=True,
        ).start()

    def close_open_position(self, *, reoptimize: bool = True) -> bool:
        """Close the open position at the current mark price and optionally re-optimize."""
        PAPER_RUNTIME_LOGGER.info("Close position requested reoptimize=%s", reoptimize)
        with self._operation_lock:
            if self.session.symbol not in self.portfolio.positions:
                self._emit_activity("Close & retest skipped — no open position")
                return False

            quote = self._fetch_price() or self._last_good_quote
            if quote is None or quote.price <= 0:
                self._emit_activity("Cannot close position — live price unavailable")
                return False
            now = quote.timestamp
            if now.tzinfo is None:
                now = now.replace(tzinfo=timezone.utc)

            self.portfolio.mark_to_market({self.session.symbol: quote.price})
            self.matcher.submit_intent(
                TransactionIntent(
                    timestamp=now,
                    asset=self.session.symbol,
                    direction=Direction.EXIT,
                ),
                reference_price=quote.price,
            )
            self.portfolio.mark_to_market({self.session.symbol: quote.price})
            from tradingagents.simulator.activity_messages import format_tick_action

            close_message = format_tick_action(
                "manual_close",
                quote.price,
                self.portfolio.equity,
                leverage=float(self.session.leverage or 1.0),
            )
            journal_trade(close_message)
            self._emit_activity(close_message)
            self._record_equity_samples(self.portfolio.equity, now)

            if reoptimize:
                self._run_manual_rebacktest(now)

            state = self.get_state(quote)
            self._persist_session(quote)
            if self.on_state_change:
                self.on_state_change(state)
            PAPER_RUNTIME_LOGGER.info(
                "Close position complete equity=$%.2f reoptimize=%s",
                self.portfolio.equity,
                reoptimize,
            )
            return True

    def reanalyze(self) -> None:
        """Re-run strategy optimization without closing the open position."""
        PAPER_RUNTIME_LOGGER.info("Reanalyze requested")
        with self._operation_lock:
            quote = self._fetch_price() or self._last_good_quote
            now = datetime.now(timezone.utc)
            if now.tzinfo is None:
                now = now.replace(tzinfo=timezone.utc)
            from tradingagents.simulator.activity_messages import format_reanalyze_banner

            self._run_optimization_cycle(
                now,
                banner=format_reanalyze_banner(),
                winner_prefix="Reanalyze winner",
                adaptive_followup=False,
                fail_label="Reanalyze failed",
                not_deployable_label="Reanalyze complete — not deployable",
            )
            state = self.get_state(quote)
            self._persist_session(quote)
            if self.on_state_change:
                self.on_state_change(state)
            PAPER_RUNTIME_LOGGER.info(
                "Reanalyze complete strategy=%s equity=$%.2f",
                self.session.strategy_name,
                self.portfolio.equity,
            )

    def _run_manual_rebacktest(self, now: datetime) -> None:
        """Re-run optimization after a manual close (not an adaptive drawdown review)."""
        from tradingagents.simulator.activity_messages import format_close_retest_banner

        self._run_optimization_cycle(
            now,
            banner=format_close_retest_banner(),
            winner_prefix="Close & retest winner",
            adaptive_followup=False,
            fail_label="Close & retest failed",
            not_deployable_label="Close & retest complete — not deployable",
        )

    def _make_horizon_callbacks(self):
        from tradingagents.simulator.activity_messages import (
            format_horizon_complete,
            format_horizon_skipped,
            format_horizon_start,
            format_horizon_worst,
            format_provider_attempt,
        )

        def _on_horizon_start(lookback: LookbackWindow) -> None:
            self._log_backtest_activity(format_horizon_start(lookback.value))

        def _on_horizon_complete(
            lookback: LookbackWindow,
            provider: str,
            bar_count: int,
            cache_hit: bool,
            metrics: list,
        ) -> None:
            self._log_backtest_activity(
                format_horizon_complete(
                    lookback.value,
                    provider,
                    bar_count,
                    metrics,
                    cache_hit=cache_hit,
                )
            )
            worst_line = format_horizon_worst(lookback.value, metrics)
            if worst_line:
                self._log_backtest_activity(worst_line)

        def _on_horizon_skipped(lookback: LookbackWindow, reason: str) -> None:
            self._log_backtest_activity(format_horizon_skipped(lookback.value, reason))

        def _on_horizon_provider_attempt(
            lookback: LookbackWindow,
            vendor: str,
            bars: int,
            ok: bool,
            detail: str,
        ) -> None:
            self._log_backtest_activity(
                format_provider_attempt(lookback.value, vendor, bars, ok, detail)
            )

        return (
            _on_horizon_start,
            _on_horizon_complete,
            _on_horizon_skipped,
            _on_horizon_provider_attempt,
        )

    def _deploy_optimization_winner(self, optimization: OptimizationResult, end_date: str) -> None:
        if optimization.winner is None:
            return
        old_name = self.session.strategy_name
        old_lookback = self.session.lookback
        new_name = optimization.winner.strategy_name

        self.session.strategy_name = new_name
        self.session.parameters = {
            k: v
            for k, v in optimization.winner.parameters.items()
            if not str(k).startswith("_")
        }
        self.session.lookback = optimization.winner.lookback
        self.session.stop_loss_pct = optimization.winner.stop_loss_pct
        self.session.take_profit_pct = optimization.winner.take_profit_pct
        self.session.slippage_bps = optimization.winner.transaction_cost_pct * 10_000.0
        self.portfolio.fee_bps = self.session.slippage_bps
        self.matcher.slippage_bps = 0.0
        self._last_signal_bar = None
        try:
            raw = compute_strategy_signal(
                self.session.symbol,
                new_name,
                self.session.parameters,
                optimization.winner.lookback,
                end_date,
                config=self.config,
            )
        except Exception as exc:
            self._emit_activity(f"Deploy signal skipped — keeping prior signal ({exc})")
            raw = self.session.signal.value
        self.session.signal = StrategySignal.from_string(raw)

        if new_name != old_name:
            if self.on_strategy_switch:
                self.on_strategy_switch(old_name, new_name)
            self._log_autonomous_rotation(old_name, new_name)
        elif optimization.winner.lookback != old_lookback:
            self._emit_activity(
                f"Lookback refreshed: {old_lookback} → {optimization.winner.lookback}"
            )
        self._spike_monitor.update_lookback(self.session.lookback, self.config)

    def _should_switch_on_spike(self, optimization: OptimizationResult) -> bool:
        """Conservative gate — only switch when an alternative is materially better."""
        if optimization.winner is None or not optimization.deployable:
            return False
        winner = optimization.winner
        same_plan = (
            winner.strategy_name == self.session.strategy_name
            and winner.lookback == self.session.lookback
        )
        if same_plan:
            return False
        min_edge = float(self.config.get("paper_spike_switch_min_net_profit", 0.005))
        return winner.historical_profit_ratio >= min_edge

    def _run_optimization_cycle(
        self,
        now: datetime,
        *,
        banner: str,
        winner_prefix: str,
        adaptive_followup: bool,
        fail_label: str,
        not_deployable_label: str,
        conservative_switch: bool = False,
    ) -> None:
        """Re-run optimization, log horizon results, and deploy a winner when allowed."""
        end_date = now.strftime("%Y-%m-%d")
        from tradingagents.simulator.activity_messages import format_optimization_winner

        self._emit_activity(banner)
        self._signals_halted = True
        on_start, on_complete, on_skipped, on_provider = self._make_horizon_callbacks()
        delays = DEFAULT_API_RETRY_DELAYS

        try:
            from tradingagents.dataflows.trading_fees import paper_transaction_cost_pct

            def _on_retry(attempt: int, wait: float, exc: Exception) -> None:
                self._emit_activity(
                    f"{fail_label} — API error, retry {attempt} in {wait:.0f}s ({exc})"
                )

            optimization = retry_with_backoff_optional(
                lambda: optimize_strategies(
                    self.session.symbol,
                    end_date,
                    config=self.config,
                    stop_loss_pct=self.session.stop_loss_pct,
                    take_profit_pct=self.session.take_profit_pct,
                    transaction_cost_pct=paper_transaction_cost_pct(
                        self.session.symbol, self.config
                    ),
                    on_horizon_start=on_start,
                    on_horizon_complete=on_complete,
                    on_horizon_skipped=on_skipped,
                    on_horizon_provider_attempt=on_provider,
                ),
                delays=delays,
                on_retry=_on_retry,
                label=fail_label,
            )
            if optimization is None:
                self._emit_activity(f"{fail_label} — continuing after API retries")
                return

            if optimization.winner is None or not optimization.deployable:
                reason = (
                    "; ".join(optimization.gate_failures)
                    if optimization.gate_failures
                    else "no winning strategy found"
                )
                self._emit_activity(f"{not_deployable_label} ({reason})")
                on_fail = self.config.get("winner_on_gate_fail", "keep")
                if on_fail == "flat":
                    self.session.signal = StrategySignal.FLAT
                if adaptive_followup:
                    self._adaptive.mark_rebacktest_done(now)
                return

            self._emit_activity(
                format_optimization_winner(optimization.winner, prefix=winner_prefix)
            )
            if conservative_switch and not self._should_switch_on_spike(optimization):
                winner = optimization.winner
                self._emit_activity(
                    "Fast-move review — keeping "
                    f"{self.session.strategy_name} ({self.session.lookback}); "
                    f"alternative {winner.strategy_name} ({winner.lookback}) "
                    f"not materially better (net {winner.historical_profit_ratio:+.2%})"
                )
                if adaptive_followup:
                    self._adaptive.mark_rebacktest_done(now)
                return
            self._deploy_optimization_winner(optimization, end_date)
            if adaptive_followup:
                self._adaptive.mark_rebacktest_done(now)
        except Exception as exc:
            logger.warning("%s: %s", fail_label, exc, exc_info=True)
            self._emit_activity(f"{fail_label} — continuing ({exc})")
        finally:
            self._signals_halted = False

    def _run_adaptive_rebacktest(self, now: datetime) -> None:
        """Re-run optimization and switch strategy when a better one is found."""
        self._adaptive.note_drawdown_review(now)
        drawdown = self._adaptive.current_drawdown_pct()
        logger.info(
            "Adaptive re-backtest triggered for %s (drawdown %.2f%%)",
            self.session.symbol,
            drawdown,
        )
        from tradingagents.simulator.activity_messages import format_drawdown_rebacktest_banner

        self._run_optimization_cycle(
            now,
            banner=format_drawdown_rebacktest_banner(drawdown),
            winner_prefix="Re-backtest winner",
            adaptive_followup=True,
            fail_label="Re-backtest failed",
            not_deployable_label="Re-backtest complete — not deployable",
        )

    def _run_spike_rebacktest(self, now: datetime, reason: str) -> None:
        """Re-run optimization after a rapid equity drop; switch only if clearly better."""
        logger.info(
            "Fast-move review triggered for %s (%s)",
            self.session.symbol,
            reason,
        )
        from tradingagents.simulator.activity_messages import format_volatility_spike_banner

        self._run_optimization_cycle(
            now,
            banner=format_volatility_spike_banner(reason),
            winner_prefix="Fast-move review winner",
            adaptive_followup=True,
            conservative_switch=True,
            fail_label="Fast-move review failed",
            not_deployable_label="Fast-move review — not deployable",
        )

    def get_state(self, quote: Optional[LivePrice] = None) -> PaperTradingState:
        """Current portfolio and session snapshot."""
        if quote is None:
            quote = self._last_good_quote
        if quote is None:
            quote = self._quote_for_display(None)
        pos_desc = None
        pos_entry: Optional[float] = None
        pos_side: Optional[str] = None
        if self.session.symbol in self.portfolio.positions:
            pos = self.portfolio.positions[self.session.symbol]
            pos_desc = "long" if pos["side"] > 0 else "short"
            pos_entry = float(pos["entry_price"])
            pos_side = pos_desc
        pnl = self.portfolio.equity - self.portfolio.initial_equity
        pnl_pct = (pnl / self.portfolio.initial_equity * 100.0) if self.portfolio.initial_equity else 0.0
        now = quote.timestamp
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        spike_status = self._spike_monitor.status(now)
        take_profit = self.session.take_profit_pct
        if take_profit is None:
            take_profit = self.session.stop_loss_pct * 2.0
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
            price_endpoint=quote.endpoint or "",
            vendor_failures=self._vendor_failure_summary(),
            last_drawdown_review=format_last_drawdown_review(
                self._adaptive.minutes_since_last_drawdown_review(now)
            ),
            effective_drawdown_window_minutes=self._adaptive.effective_review_window_minutes(now),
            spike_review_enabled=self._spike_monitor.enabled,
            spike_intelligent_tuning=self._spike_monitor.intelligent_tuning,
            spike_status_line=self._spike_monitor.format_status_line(now),
            spike_watch_display=self._spike_monitor.format_status_line_compact(now),
            last_spike_review=format_last_spike_review(
                spike_status.minutes_since_last_review
            ),
            spike_review_count=spike_status.review_count,
            activity_status=self._activity_status(),
            adaptive_enabled=self.adaptive_enabled,
            max_drawdown_pct=float(
                self.config.get(
                    "max_allowed_drawdown_pct",
                    self.config.get("paper_loss_threshold_pct", 5.0),
                )
            ),
            stop_loss_pct=float(self.session.stop_loss_pct),
            take_profit_pct=take_profit,
            leverage=float(self.session.leverage or 1.0),
            open_position=pos_desc,
            position_entry_price=pos_entry,
            position_side=pos_side,
        )

    def run_loop(
        self,
        *,
        interval_seconds: Optional[float] = None,
        max_ticks: Optional[int] = None,
        on_tick: Optional[Callable[[TickEvaluationResult], None]] = None,
        poll_key: Optional[Callable[[float], Optional[str]]] = None,
    ) -> None:
        """Blocking poll loop until ``max_ticks`` or stop requested."""
        interval = interval_seconds or float(self.config.get("paper_tick_interval_seconds", 10.0))
        ticks = 0
        PAPER_RUNTIME_LOGGER.info(
            "Run loop started symbol=%s interval=%.1fs adaptive=%s",
            self.session.symbol,
            interval,
            self.adaptive_enabled,
        )
        try:
            while not self._stop_event.is_set():
                try:
                    result = self.tick()
                except Exception as exc:
                    logger.exception("Paper tick crashed — continuing: %s", exc)
                    PAPER_RUNTIME_LOGGER.exception("Tick crashed — continuing next interval")
                    self._emit_activity(f"Tick crashed — continuing next interval ({exc})")
                    result = None
                if result is not None and on_tick:
                    on_tick(result)
                if result is not None:
                    ticks += 1
                if max_ticks is not None and ticks >= max_ticks:
                    break
                key = _sleep_until_stopped_or_key(self._stop_event, interval, poll_key)
                if key == "q":
                    self._stop_event.set()
                    break
                if key == "c":
                    self.close_open_position(reoptimize=True)
                if key == "r":
                    self.reanalyze()
        except KeyboardInterrupt:
            self._stop_event.set()
        PAPER_RUNTIME_LOGGER.info(
            "Run loop stopped symbol=%s ticks=%d equity=$%.2f",
            self.session.symbol,
            ticks,
            self.portfolio.equity,
        )

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
    stop_loss_pct = float(optimization.winner.stop_loss_pct)
    take_profit_pct = optimization.winner.take_profit_pct
    slippage_bps = float(optimization.winner.transaction_cost_pct * 10_000.0)
    clean_params = {
        k: v for k, v in optimization.winner.parameters.items() if not str(k).startswith("_")
    }
    return PaperTradingSession(
        symbol=optimization.symbol,
        strategy_name=optimization.winner.strategy_name,
        signal=StrategySignal.from_string(signal),
        parameters=clean_params,
        lookback=optimization.winner.lookback,
        initial_equity=float(cfg.get("paper_initial_equity", 10_000.0)),
        stop_loss_pct=stop_loss_pct,
        take_profit_pct=take_profit_pct,
        slippage_bps=slippage_bps,
        leverage=float(cfg.get("paper_leverage", 1.0)),
    )
