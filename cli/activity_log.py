"""Append-only activity log for paper trading and backtest CLI displays."""

from __future__ import annotations

import sys
from collections import deque
from datetime import datetime
from typing import Callable, Iterable, Optional

from rich.panel import Panel
from rich.text import Text

from tradingagents.simulator.activity_messages import (
    format_drawdown_rebacktest_banner,
    format_horizon_complete,
    format_horizon_skipped,
    format_horizon_start,
    format_horizon_worst,
    format_optimization_winner,
    format_price_feed,
    format_provider_line,
    format_session_start,
    format_strategy_switch,
    format_tick_action,
)

__all__ = [
    "ActivityLog",
    "format_drawdown_rebacktest_banner",
    "format_horizon_complete",
    "format_horizon_skipped",
    "format_horizon_start",
    "format_optimization_winner",
    "format_price_feed",
    "format_provider_line",
    "format_session_start",
    "format_strategy_switch",
    "format_tick_action",
    "is_live_display_tty",
    "make_backtest_callbacks",
    "make_progress_logger",
]


def is_live_display_tty() -> bool:
    """True when stdout is a TTY and live Rich panels are safe."""
    return sys.stdout.isatty()


class ActivityLog:
    """Timestamped, capped append-only log for Rich live displays."""

    def __init__(
        self,
        *,
        max_lines: int = 75,
        enabled: bool = True,
        echo: Optional[Callable[[str], None]] = None,
        on_change: Optional[Callable[[], None]] = None,
    ) -> None:
        self._lines: deque[tuple[str, str]] = deque(maxlen=max_lines)
        self.enabled = enabled
        self._echo = echo
        self._on_change = on_change

    def append(self, message: str) -> None:
        if not self.enabled or not message:
            return
        timestamp = datetime.now().strftime("%H:%M:%S")
        self._lines.append((timestamp, message))
        if self._echo is not None:
            self._echo(message)
        if self._on_change is not None:
            self._on_change()

    def extend(self, messages: Iterable[str]) -> None:
        for message in messages:
            self.append(message)

    def render_panel(self, *, title: str = "Activity", visible_lines: int = 20) -> Panel:
        if not self._lines:
            body = Text("Waiting for events…", style="dim italic")
            panel_height = 3
        else:
            tail = list(self._lines)[-visible_lines:]
            body = Text()
            if len(self._lines) > visible_lines:
                body.append("… earlier events hidden", style="dim italic")
            for idx, (ts, line) in enumerate(tail):
                if idx or len(self._lines) > visible_lines:
                    body.append("\n")
                body.append(f"{ts} ", style="dim cyan")
                body.append(line)
            panel_height = len(tail) + (1 if len(self._lines) > visible_lines else 0) + 2
        return Panel(body, title=title, border_style="blue", height=panel_height)

    @property
    def line_count(self) -> int:
        return len(self._lines)


def make_progress_logger(progress) -> ActivityLog:
    """Activity log that prints above a Rich Progress bar."""

    def _echo(message: str) -> None:
        progress.console.print(f"[dim]{datetime.now().strftime('%H:%M:%S')}[/dim] {message}")

    return ActivityLog(enabled=True, echo=_echo)


def make_backtest_callbacks(log: ActivityLog):
    """Return optimize_strategies horizon callbacks wired to an activity log."""
    from tradingagents.backtest.engine import LookbackWindow
    from tradingagents.backtest.schemas import StrategyMetrics
    from tradingagents.simulator.activity_messages import format_provider_attempt

    def on_horizon_start(lookback: LookbackWindow) -> None:
        log.append(format_horizon_start(lookback.value))

    def on_horizon_provider_attempt(
        lookback: LookbackWindow,
        vendor: str,
        bars: int,
        ok: bool,
        detail: str,
    ) -> None:
        log.append(format_provider_attempt(lookback.value, vendor, bars, ok, detail))

    def on_horizon_complete(
        lookback: LookbackWindow,
        provider: str,
        bar_count: int,
        cache_hit: bool,
        metrics: list[StrategyMetrics],
    ) -> None:
        log.append(
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
            log.append(worst_line)

    def on_horizon_skipped(lookback: LookbackWindow, reason: str) -> None:
        log.append(format_horizon_skipped(lookback.value, reason))

    return on_horizon_start, on_horizon_complete, on_horizon_skipped, on_horizon_provider_attempt
