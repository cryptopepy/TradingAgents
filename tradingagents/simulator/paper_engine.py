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
from tradingagents.backtest.portfolio import Direction, TransactionIntent, VirtualPortfolio
from tradingagents.dataflows.config import get_config
from tradingagents.dataflows.dummy_feed import DummyPriceFeed
from tradingagents.dataflows.live_prices import LivePrice, PriceSource, fetch_live_spot_price, get_live_feed_router
from tradingagents.simulator.adaptive import AdaptiveStrategyMonitor, format_last_drawdown_review
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
        self.matcher = SimulatedMatcher(slippage_bps=session.slippage_bps, portfolio=self.portfolio)
        self._dummy_feed: Optional[DummyPriceFeed] = None
        self._tick_history: List[TickEvaluationResult] = []
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._signals_halted = False
        self._feed_unavailable = False
        self._last_good_quote: Optional[LivePrice] = None
        self._last_feed_warning_at: float = 0.0
        self._last_logged_price_source: Optional[str] = None
        self._price_feed_logged = False

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

    @property
    def tick_history(self) -> List[TickEvaluationResult]:
        return list(self._tick_history)

    def _ensure_dummy_feed(self, anchor: float) -> None:
        if self._dummy_feed is None:
            self._dummy_feed = DummyPriceFeed(anchor_price=anchor, symbol=self.session.symbol)

    def _fetch_price(self) -> Optional[LivePrice]:
        """Return a live quote, or None when all vendors failed (no mock trading)."""
        quote = fetch_live_spot_price(self.session.symbol, self.config)
        if quote.source == PriceSource.PLACEHOLDER:
            self._feed_unavailable = True
            self._log_feed_unavailable()
            return None
        self._feed_unavailable = False
        self._last_good_quote = quote
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
        self._adaptive.record_equity(result.portfolio_equity, now)
        state = self.get_state(display)
        if self.on_state_change:
            self.on_state_change(state)
        return result

    def refresh_signal(self) -> StrategySignal:
        """Recompute strategy signal from latest historical candles."""
        raw = compute_strategy_signal(
            self.session.symbol,
            self.session.strategy_name,
            self.session.parameters,
            self.session.lookback,
            config=self.config,
        )
        signal = StrategySignal.from_string(raw)
        self.session.signal = signal
        return signal

    def _restore_persisted_session(self) -> None:
        if not self.config.get("paper_state_persistence", True):
            return
        if self.config.get("paper_fresh_start"):
            delete_paper_session(self.session.symbol, self.config)
            return
        saved = load_paper_session(self.session.symbol, self.config)
        if not saved:
            return
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

        self._emit_activity(
            format_tick_action(
                result.action_taken,
                result.price,
                result.portfolio_equity,
            )
        )

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
        )
        self._tick_history.append(result)
        self._log_tick_action(result)
        self._adaptive.record_equity(result.portfolio_equity, result.timestamp)

        if self.adaptive_enabled and self._adaptive.should_rebacktest(result.timestamp):
            self._run_adaptive_rebacktest(result.timestamp)

        state = self.get_state(quote)
        self._persist_session(quote)
        if self.on_state_change:
            self.on_state_change(state)
        return result

    def close_open_position(self, *, reoptimize: bool = True) -> bool:
        """Close the open position at the current mark price and optionally re-optimize."""
        if self.session.symbol not in self.portfolio.positions:
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

        self._emit_activity(
            format_tick_action("manual_close", quote.price, self.portfolio.equity)
        )
        self._adaptive.record_equity(self.portfolio.equity, now)

        if reoptimize:
            self._run_adaptive_rebacktest(now)

        state = self.get_state(quote)
        self._persist_session(quote)
        if self.on_state_change:
            self.on_state_change(state)
        return True

    def reanalyze(self) -> None:
        """Re-run strategy optimization without closing the open position."""
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
        self.matcher.slippage_bps = self.session.slippage_bps
        self.session.signal = StrategySignal.from_string(
            compute_strategy_signal(
                self.session.symbol,
                new_name,
                self.session.parameters,
                optimization.winner.lookback,
                end_date,
            )
        )

        if new_name != old_name:
            if self.on_strategy_switch:
                self.on_strategy_switch(old_name, new_name)
            self._log_autonomous_rotation(old_name, new_name)
        elif optimization.winner.lookback != old_lookback:
            self._emit_activity(
                f"Lookback refreshed: {old_lookback} → {optimization.winner.lookback}"
            )

    def _run_optimization_cycle(
        self,
        now: datetime,
        *,
        banner: str,
        winner_prefix: str,
        adaptive_followup: bool,
        fail_label: str,
        not_deployable_label: str,
    ) -> None:
        """Re-run optimization, log horizon results, and deploy a winner when allowed."""
        end_date = now.strftime("%Y-%m-%d")
        from tradingagents.simulator.activity_messages import format_optimization_winner

        self._emit_activity(banner)
        self._signals_halted = True
        on_start, on_complete, on_skipped, on_provider = self._make_horizon_callbacks()

        try:
            from tradingagents.dataflows.trading_fees import paper_transaction_cost_pct

            optimization = optimize_strategies(
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
            )
        except Exception as exc:
            logger.warning("%s: %s", fail_label, exc)
            self._emit_activity(f"{fail_label} — {exc}")
            self._signals_halted = False
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
            self._signals_halted = False
            return

        self._emit_activity(
            format_optimization_winner(optimization.winner, prefix=winner_prefix)
        )
        self._deploy_optimization_winner(optimization, end_date)
        if adaptive_followup:
            self._adaptive.mark_rebacktest_done(now)
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

    def get_state(self, quote: Optional[LivePrice] = None) -> PaperTradingState:
        """Current portfolio and session snapshot."""
        if quote is None:
            quote = self._last_good_quote
        if quote is None:
            quote = self._quote_for_display(None)
        pos_desc = None
        if self.session.symbol in self.portfolio.positions:
            pos = self.portfolio.positions[self.session.symbol]
            pos_desc = "long" if pos["side"] > 0 else "short"
        pnl = self.portfolio.equity - self.portfolio.initial_equity
        pnl_pct = (pnl / self.portfolio.initial_equity * 100.0) if self.portfolio.initial_equity else 0.0
        now = quote.timestamp
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
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
            open_position=pos_desc,
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
        try:
            while not self._stop_event.is_set():
                result = self.tick()
                if on_tick:
                    on_tick(result)
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
    )
