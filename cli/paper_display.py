"""Extra panels for paper trading live display."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from typing import Optional

from rich.panel import Panel
from rich.table import Table

from tradingagents.simulator.paper_engine import PaperTradingState


def terminal_size() -> tuple[int, int]:
    """Return (columns, lines) for layout calculations."""
    size = shutil.get_terminal_size(fallback=(120, 40))
    return size.columns, size.lines


def activity_panel_height(*, reserved_lines: int = 34) -> int:
    """Lines available for the activity log panel after fixed rows."""
    _, height = terminal_size()
    return max(8, height - reserved_lines)


def terminal_column_widths(count: int, *, minimum: int = 28) -> list[int]:
    """Divide terminal width so side-by-side panels stay horizontal."""
    total = shutil.get_terminal_size(fallback=(120, 40)).columns
    usable = max(total - (count + 1), minimum * count)
    each = usable // count
    return [max(minimum, each)] * count


def clip_cell(text: str, max_width: int) -> str:
    """Truncate display text so tables do not blow out column layout."""
    if max_width < 4 or len(text) <= max_width:
        return text
    return text[: max_width - 1] + "…"


def _value_column_width(panel_width: Optional[int], label_width: int = 14) -> int:
    if panel_width is None:
        return 24
    return max(12, panel_width - label_width - 6)


@dataclass
class PaperDisplayContext:
    """Live timing metadata for the status row."""

    tick_interval: float = 3.0
    seconds_until_next: Optional[float] = None
    kraken_status: str = ""
    fee_bps: Optional[float] = None
    show_movers: bool = False
    status_prompt: Optional[str] = None
    busy_label: Optional[str] = None


def render_market_panel(
    state: PaperTradingState,
    ctx: PaperDisplayContext,
    *,
    session_high: Optional[float] = None,
    session_low: Optional[float] = None,
    width: Optional[int] = None,
) -> Panel:
    """Compact market / timing strip between portfolio and price ticks."""
    value_max = _value_column_width(width)
    table = Table(
        show_header=True,
        header_style="bold yellow",
        expand=False,
        pad_edge=False,
        width=width,
    )
    table.add_column("Metric", style="dim", min_width=10, max_width=14, no_wrap=True)
    table.add_column(
        "Value",
        justify="right",
        min_width=12,
        max_width=value_max,
        overflow="ellipsis",
        no_wrap=True,
    )

    table.add_row("Spot", clip_cell(f"${state.price:,.4f}" if state.price else "—", value_max))
    table.add_row("Feed", clip_cell(state.price_source or "—", value_max))
    if state.price_endpoint:
        table.add_row("Endpoint", clip_cell(state.price_endpoint, value_max))
    if session_high is not None and session_low is not None:
        table.add_row(
            "Session H/L",
            clip_cell(f"${session_high:,.0f}/${session_low:,.0f}", value_max),
        )
    table.add_row("Tick every", f"{ctx.tick_interval:.0f}s")
    if ctx.seconds_until_next is not None:
        table.add_row("Next tick", f"{max(0.0, ctx.seconds_until_next):.1f}s")
    table.add_row("Status", clip_cell(state.activity_status, value_max))
    table.add_row("Signal", state.signal)
    if state.open_position:
        table.add_row("Position", state.open_position)
    if ctx.kraken_status:
        table.add_row("Kraken", clip_cell(ctx.kraken_status, value_max))
    if ctx.fee_bps is not None:
        table.add_row("Fee (side)", f"{ctx.fee_bps:.1f} bps")

    return Panel(
        table,
        title="Market",
        border_style="yellow",
        expand=False,
        width=width,
    )
