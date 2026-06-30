"""Run visual backtests against a single cached OHLCV frame."""

from __future__ import annotations

import threading
import time
from typing import Callable, List, Optional

import pandas as pd

from cli.activity_log import ActivityLog
from cli.tui.visual_backtest.display import VisualBacktestDisplayContext, append_trade_to_log
from cli.tui.visual_backtest.setup import VisualBacktestParams
from tradingagents.backtest.engine import BacktestResult, fetch_ohlcv_range, run_strategy_on_frame
from tradingagents.backtest.strategies import DEFAULT_STRATEGIES, build_strategy
from tradingagents.backtest.validation import BacktestDataError


class VisualBacktestRunner:
    """Fetches OHLCV once and runs strategies with live callbacks."""

    def __init__(
        self,
        params: VisualBacktestParams,
        config: dict,
        log: ActivityLog,
        display_ctx: VisualBacktestDisplayContext,
        *,
        on_refresh: Callable[[], None],
        poll_key: Callable[[float], Optional[str]],
    ) -> None:
        self.params = params
        self.config = config
        self.log = log
        self.display_ctx = display_ctx
        self._on_refresh = on_refresh
        self._poll_key = poll_key
        self._df: Optional[pd.DataFrame] = None
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._dirty = False
        self._last_ui = 0.0
        self._ui_hz = float(config.get("visual_backtest_ui_hz", 8))

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="visual-backtest", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _maybe_refresh(self, force: bool = False) -> None:
        now = time.monotonic()
        min_interval = 1.0 / max(1.0, self._ui_hz)
        if force or (self._dirty and now - self._last_ui >= min_interval):
            self._dirty = False
            self._last_ui = now
            self._on_refresh()

    def _run(self) -> None:
        p = self.params
        self.display_ctx.state = "fetching"
        self.display_ctx.busy_label = "Fetching OHLCV…"
        self.display_ctx.error_message = None
        self.log.append(
            f"Fetching {p.ticker} {p.granularity_label} "
            f"{p.start_dt:%Y-%m-%d %H:%M} → {p.end_dt:%Y-%m-%d %H:%M}…"
        )
        self._maybe_refresh(force=True)

        def _on_provider(vendor: str, bars: int, ok: bool, detail: str) -> None:
            status = "ok" if ok else "skip"
            self.log.append(f"  {vendor}: {detail} ({status})")
            self._dirty = True
            self._maybe_refresh()

        def _on_fetch(name: str, bars: int, _cache_hit: bool) -> None:
            source_holder["name"] = name
            self.display_ctx.bar_count = bars

        source_holder: dict = {"name": ""}

        try:
            df = fetch_ohlcv_range(
                p.ticker,
                p.start_dt,
                p.end_dt,
                p.granularity_seconds,
                config=self.config,
                on_fetch=_on_fetch,
                on_provider_attempt=_on_provider,
            )
        except BacktestDataError as exc:
            self.display_ctx.state = "idle"
            self.display_ctx.busy_label = None
            self.display_ctx.error_message = str(exc)
            self.log.append(f"Fetch failed: {exc}")
            self._maybe_refresh(force=True)
            return

        self._df = df
        self.display_ctx.bar_count = len(df)
        self.display_ctx.fetch_source = source_holder["name"] or "vendor"
        self.display_ctx.busy_label = None
        self.log.append(f"Loaded {len(df):,} bars — running backtest(s)")
        self._maybe_refresh(force=True)

        if p.strategy_mode == "single" and p.strategy_name:
            strategies = [build_strategy(p.strategy_name)]
        else:
            strategies = list(DEFAULT_STRATEGIES)

        self.display_ctx.strategy_total = len(strategies)
        sample_lines = int(self.config.get("visual_backtest_price_sample_lines", 12))
        stride = max(1, len(df) // max(1, sample_lines))
        results: List[tuple[str, BacktestResult]] = []

        for idx, strategy in enumerate(strategies, start=1):
            if self._stop.is_set():
                break
            self.display_ctx.state = "running"
            self.display_ctx.strategy_index = idx
            self.display_ctx.strategy_name = strategy.name
            self.display_ctx.price_samples.clear()
            self.log.append(f"── {strategy.name} ({idx}/{len(strategies)}) ──")
            self._maybe_refresh(force=True)

            def _on_bar(_i: int, date_str: str, close: float, _equity: float) -> None:
                self.display_ctx.price_samples.append(f"{date_str}  ${close:,.4f}")
                if len(self.display_ctx.price_samples) > sample_lines:
                    self.display_ctx.price_samples.pop(0)
                self._dirty = True
                self._maybe_refresh()

            def _on_entry(date_str: str, side: str, price: float) -> None:
                append_trade_to_log(self.log, (side, price, date_str), kind="entry")
                self._dirty = True
                self._maybe_refresh()

            def _on_trade(record, _kind: str) -> None:
                append_trade_to_log(self.log, record)
                self._dirty = True
                self._maybe_refresh()

            result = run_strategy_on_frame(
                df,
                strategy,
                symbol=p.ticker,
                stop_loss_pct=p.stop_loss_pct,
                take_profit_pct=p.take_profit_pct,
                transaction_cost_pct=p.transaction_cost_pct,
                config=self.config,
                leverage=p.leverage,
                on_bar=_on_bar,
                on_entry=_on_entry,
                on_trade=_on_trade,
                bar_sample_stride=stride,
            )
            self.display_ctx.current_result = result
            results.append((strategy.name, result))
            self.log.append(
                f"Done {strategy.name}: {result.total_return_pct:+.2f}% "
                f"({result.num_trades} trades, win {result.win_rate:.1f}%)"
            )
            self._maybe_refresh(force=True)

            if (
                p.pause_between_strategies
                and p.strategy_mode == "all"
                and idx < len(strategies)
            ):
                self.display_ctx.state = "waiting_next"
                self.display_ctx.waiting_prompt = (
                    "Press Enter for next strategy (q to skip remaining)"
                )
                self._maybe_refresh(force=True)
                while not self._stop.is_set():
                    key = self._poll_key(0.25)
                    if key in ("\r", "\n", " "):
                        self.display_ctx.waiting_prompt = None
                        break
                    if key == "q":
                        self._stop.set()
                        break
                if self._stop.is_set():
                    break

        self.display_ctx.summary_rows = [
            (name, res.total_return_pct, res.win_rate, res.num_trades)
            for name, res in results
        ]
        self.display_ctx.state = "complete"
        self.display_ctx.waiting_prompt = None
        self.display_ctx.status_message = "Backtest complete — (r) reconfigure"
        self.log.append("Visual backtest complete.")
        self._maybe_refresh(force=True)
