"""Append-only activity log for paper trading and backtest CLI displays."""

from __future__ import annotations

import sys
from collections import deque
from datetime import datetime
from typing import Callable, Iterable, Optional

from rich.panel import Panel
from rich.table import Table
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
    "clip_activity_message",
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


def clip_activity_message(message: str, max_width: int) -> str:
    """Force one terminal row per log entry (no Rich soft-wrap)."""
    if max_width < 8 or len(message) <= max_width:
        return message
    return message[: max_width - 1] + "…"


def is_live_display_tty() -> bool:
    """True when stdout is a TTY and live Rich panels are safe."""
    return sys.stdout.isatty()


def _scrollbar_thumb_row(visible_lines: int, *, start: int, total: int) -> list[int]:
    """Row indices (0-based) that should show the thumb block."""
    if total <= visible_lines or visible_lines <= 0:
        return []
    max_start = total - visible_lines
    thumb_h = max(1, round(visible_lines * visible_lines / total))
    thumb_h = min(thumb_h, visible_lines)
    if max_start <= 0:
        return list(range(thumb_h))
    thumb_top = round((start / max_start) * (visible_lines - thumb_h))
    thumb_top = max(0, min(thumb_top, visible_lines - thumb_h))
    return list(range(thumb_top, thumb_top + thumb_h))


class ActivityLog:
    """Timestamped log with scrollable viewport for Rich live displays."""

    def __init__(
        self,
        *,
        max_lines: int = 200,
        enabled: bool = True,
        echo: Optional[Callable[[str], None]] = None,
        on_change: Optional[Callable[[], None]] = None,
    ) -> None:
        self._lines: deque[tuple[str, str]] = deque(maxlen=max_lines)
        self.enabled = enabled
        self._echo = echo
        self._on_change = on_change
        self._scroll_offset = 0  # lines up from the bottom (0 = newest)
        self._follow_tail = True

    def append(self, message: str) -> None:
        if not self.enabled or not message:
            return
        timestamp = datetime.now().strftime("%H:%M:%S")
        self._lines.append((timestamp, message))
        if self._follow_tail:
            self._scroll_offset = 0
        if self._echo is not None:
            self._echo(message)
        if self._on_change is not None:
            self._on_change()

    def extend(self, messages: Iterable[str]) -> None:
        for message in messages:
            self.append(message)

    @property
    def line_count(self) -> int:
        return len(self._lines)

    @property
    def scroll_offset(self) -> int:
        return self._scroll_offset

    @property
    def following_tail(self) -> bool:
        return self._follow_tail

    def set_max_lines(self, max_lines: int) -> None:
        """Resize stored history (visible viewport unchanged)."""
        cap = max(10, int(max_lines))
        self._lines = deque(self._lines, maxlen=cap)

    def scroll_up(self, lines: int = 1) -> None:
        """Scroll toward older messages."""
        if not self._lines:
            return
        self._follow_tail = False
        max_offset = max(0, len(self._lines) - 1)
        self._scroll_offset = min(self._scroll_offset + max(1, lines), max_offset)

    def scroll_down(self, lines: int = 1) -> None:
        """Scroll toward newer messages."""
        self._scroll_offset = max(0, self._scroll_offset - max(1, lines))
        if self._scroll_offset == 0:
            self._follow_tail = True

    def scroll_to_bottom(self) -> None:
        self._scroll_offset = 0
        self._follow_tail = True

    def _visible_window(self, visible_lines: int) -> tuple[list[tuple[str, str]], int]:
        total = len(self._lines)
        if total == 0:
            return [], 0
        end = total - self._scroll_offset
        start = max(0, end - visible_lines)
        return list(self._lines)[start:end], start

    def render_panel(
        self,
        *,
        title: str = "Activity",
        visible_lines: Optional[int] = None,
        height: Optional[int] = None,
        max_width: Optional[int] = None,
    ) -> Panel:
        if visible_lines is None:
            visible_lines = 11
        text_width = max(20, (max_width or 72) - 2)
        window, start = self._visible_window(visible_lines)
        total = len(self._lines)
        thumb_rows = _scrollbar_thumb_row(
            visible_lines, start=start, total=total
        )
        scrollable = total > visible_lines

        if not self._lines:
            body: Table | Text = Text("Waiting for events…", style="dim italic")
        else:
            table = Table(
                show_header=False,
                box=None,
                pad_edge=False,
                expand=True,
                show_edge=False,
            )
            table.add_column("log", ratio=1, no_wrap=True, overflow="ellipsis")
            table.add_column("bar", width=1, justify="center", no_wrap=True)

            for row_idx in range(visible_lines):
                data_idx = row_idx - (visible_lines - len(window))
                if 0 <= data_idx < len(window):
                    ts, line = window[data_idx]
                    clipped = clip_activity_message(line, text_width)
                    log_cell = Text()
                    log_cell.append(f"{ts} ", style="dim cyan")
                    log_cell.append(clipped)
                else:
                    log_cell = Text("")
                if scrollable:
                    if row_idx in thumb_rows:
                        bar_cell = Text("█", style="cyan")
                    else:
                        bar_cell = Text("│", style="dim")
                else:
                    bar_cell = Text(" ", style="dim")
                table.add_row(log_cell, bar_cell)
            body = table

        panel_title = title
        if self._scroll_offset > 0:
            panel_title = f"{title} ↑{self._scroll_offset}"

        panel_kwargs: dict = {"title": panel_title, "border_style": "blue"}
        if height is not None:
            panel_kwargs["height"] = height
        return Panel(body, **panel_kwargs)


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
