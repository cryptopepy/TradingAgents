"""Rolling spot-price history for paper trading live display."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime
from typing import Deque, Optional

from rich.console import Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text


@dataclass(frozen=True)
class PriceSample:
    timestamp: datetime
    price: float
    source: str
    delta: float
    delta_pct: float


class PriceHistoryLog:
    """Recent tick prices with change vs previous sample."""

    def __init__(self, *, max_samples: int = 12) -> None:
        self._samples: Deque[PriceSample] = deque(maxlen=max_samples)
        self._last_price: Optional[float] = None
        self._session_high: Optional[float] = None
        self._session_low: Optional[float] = None

    def record(self, price: float, source: str, timestamp: Optional[datetime] = None) -> None:
        if price <= 0:
            return
        # Only log when the displayed dollar price changes (2 decimal places).
        if self._samples and round(self._samples[-1].price, 2) == round(price, 2):
            return
        ts = timestamp or datetime.now()
        delta = 0.0
        delta_pct = 0.0
        if self._last_price is not None and self._last_price > 0:
            delta = price - self._last_price
            delta_pct = (delta / self._last_price) * 100.0
        self._last_price = price
        self._session_high = price if self._session_high is None else max(self._session_high, price)
        self._session_low = price if self._session_low is None else min(self._session_low, price)
        self._samples.append(
            PriceSample(
                timestamp=ts,
                price=price,
                source=source,
                delta=delta,
                delta_pct=delta_pct,
            )
        )

    @property
    def latest(self) -> Optional[PriceSample]:
        return self._samples[-1] if self._samples else None

    @property
    def sample_count(self) -> int:
        return len(self._samples)

    @property
    def session_high(self) -> Optional[float]:
        return self._session_high

    @property
    def session_low(self) -> Optional[float]:
        return self._session_low

    def reset(self) -> None:
        """Clear samples when switching symbols."""
        self._samples.clear()
        self._last_price = None
        self._session_high = None
        self._session_low = None

    def render_panel(self, *, title: str = "Price ticks") -> Panel:
        if not self._samples:
            body = Text("Waiting for ticks…", style="dim italic")
            return Panel(body, title=title, border_style="magenta", expand=True)

        table = Table(show_header=True, header_style="bold magenta", expand=True, pad_edge=False)
        table.add_column("Time", style="dim", min_width=10, no_wrap=True)
        table.add_column("Price", justify="right", min_width=14, no_wrap=True)
        table.add_column("Δ", justify="right", min_width=16, no_wrap=True)
        table.add_column("Source", min_width=10, no_wrap=True)

        for sample in reversed(self._samples):
            if sample.delta > 0:
                delta_style = "green"
                delta_text = f"+{sample.delta:,.2f}"
            elif sample.delta < 0:
                delta_style = "red"
                delta_text = f"{sample.delta:,.2f}"
            else:
                delta_style = "dim"
                delta_text = "—"
            pct_suffix = ""
            if sample.delta_pct != 0:
                pct_suffix = f" ({sample.delta_pct:+.3f}%)"
            table.add_row(
                sample.timestamp.strftime("%H:%M:%S"),
                f"${sample.price:,.2f}",
                f"[{delta_style}]{delta_text}{pct_suffix}[/{delta_style}]",
                sample.source,
            )

        latest = self._samples[-1]
        summary = Text()
        summary.append(f"Last: ${latest.price:,.4f} ", style="bold")
        summary.append(f"({latest.source})", style="dim")
        if self._session_high is not None and self._session_low is not None:
            summary.append("\n")
            summary.append(
                f"Session H/L: ${self._session_high:,.2f} / ${self._session_low:,.2f}",
                style="cyan",
            )
        if len(self._samples) > 1:
            first = self._samples[0]
            session_delta = latest.price - first.price
            session_pct = (session_delta / first.price * 100.0) if first.price else 0.0
            style = "green" if session_delta >= 0 else "red"
            summary.append("\n")
            summary.append(
                f"Window Δ: {session_delta:+,.2f} ({session_pct:+.3f}%)",
                style=style,
            )

        body = Group(table, Text(""), summary)
        return Panel(body, title=title, border_style="magenta", expand=True)
