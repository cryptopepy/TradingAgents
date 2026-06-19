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
    # Side-by-side status panels need enough room for label + value columns.
    side_minimum = 44 if count == 2 else minimum
    usable = max(total - (count + 1), side_minimum * count)
    each = usable // count
    return [max(side_minimum if count == 2 else minimum, each)] * count


def clip_cell(text: str, max_width: int) -> str:
    """Truncate display text so tables do not blow out column layout."""
    if max_width < 4 or len(text) <= max_width:
        return text
    return text[: max_width - 1] + "…"


def panel_inner_width(panel_width: Optional[int]) -> int:
    """Usable table width inside a bordered panel."""
    if panel_width is None:
        return 56
    return max(30, panel_width - 4)


def make_kv_table(
    panel_width: Optional[int],
    *,
    header_style: str,
    title: Optional[str] = None,
    label_header: str = "Field",
    value_header: str = "Value",
) -> tuple[Table, int]:
    """Two-column label/value table sized to fit a side panel."""
    inner = panel_inner_width(panel_width)
    label_w = max(14, (inner * 2) // 5)
    value_w = max(12, inner - label_w - 1)
    table = Table(
        title=title,
        show_header=True,
        header_style=header_style,
        expand=False,
        pad_edge=True,
        width=inner,
    )
    table.add_column(
        label_header,
        style="dim",
        width=label_w,
        no_wrap=True,
        overflow="ellipsis",
    )
    table.add_column(
        value_header,
        width=value_w,
        no_wrap=True,
        overflow="ellipsis",
    )
    return table, value_w


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
    table, value_w = make_kv_table(
        width,
        header_style="bold yellow",
        label_header="Metric",
    )
    table.add_row("Spot", f"${state.price:,.4f}" if state.price else "—")
    table.add_row("Feed", state.price_source or "—")
    if state.price_endpoint:
        table.add_row("Endpoint", clip_cell(state.price_endpoint, value_w))
    if session_high is not None and session_low is not None:
        table.add_row(
            "Session H/L",
            f"${session_high:,.0f} / ${session_low:,.0f}",
        )
    table.add_row("Tick every", f"{ctx.tick_interval:.0f}s")
    if ctx.seconds_until_next is not None:
        table.add_row("Next tick", f"{max(0.0, ctx.seconds_until_next):.1f}s")
    table.add_row("Status", clip_cell(state.activity_status, value_w))
    table.add_row("Signal", state.signal)
    if state.open_position:
        table.add_row("Position", state.open_position)
    if ctx.kraken_status:
        table.add_row("Kraken", clip_cell(ctx.kraken_status, value_w))
    if ctx.fee_bps is not None:
        table.add_row("Fee (side)", f"{ctx.fee_bps:.1f} bps")

    return Panel(
        table,
        title="Market",
        border_style="yellow",
        expand=True,
        width=width,
    )
