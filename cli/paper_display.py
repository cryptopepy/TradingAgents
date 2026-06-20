"""Extra panels for paper trading live display."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from typing import Optional

from rich.console import Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from tradingagents.dataflows.config import get_config
from tradingagents.simulator.liquidation import (
    format_liquidation_cell,
    leverage_display_tiers,
)
from tradingagents.simulator.paper_engine import PaperTradingState


def terminal_size() -> tuple[int, int]:
    """Return (columns, lines) for layout calculations."""
    size = shutil.get_terminal_size(fallback=(120, 40))
    return size.columns, size.lines


# Defaults; override via paper_activity_visible_lines / paper_activity_max_lines.
ACTIVITY_PANEL_CHROME_LINES = 2


def clip_activity_message(message: str, max_width: int) -> str:
    """Re-export for layout helpers (implementation lives in activity_log)."""
    from cli.activity_log import clip_activity_message as _clip

    return _clip(message, max_width)


def paper_live_reserved_lines(
    *,
    show_movers: bool = False,
    leverage_on: bool = False,
) -> int:
    """Estimate fixed rows below the activity panel."""
    price_ticks = 12  # header + 8 rows + summary + border
    paper_rows = 18  # strategy/status block with spike + adaptive rows
    market_rows = 14 + (6 if leverage_on else 0)  # leverage subsection
    side_panels = max(paper_rows, market_rows) + 2  # panel title/border
    footer = 2
    movers = 8 if show_movers else 0
    return price_ticks + side_panels + footer + movers


def activity_log_layout(
    *,
    reserved_lines: Optional[int] = None,
    leverage_on: bool = False,
    show_movers: bool = False,
    config: Optional[dict] = None,
) -> tuple[int, int]:
    """Return (visible_entry_count, panel_height_lines)."""
    cfg = config or get_config()
    visible_cap = int(cfg.get("paper_activity_visible_lines", 11))
    reserved = reserved_lines if reserved_lines is not None else paper_live_reserved_lines(
        show_movers=show_movers,
        leverage_on=leverage_on,
    )
    _, term_h = terminal_size()
    available = max(6, term_h - reserved)
    visible = min(
        visible_cap,
        max(4, available - ACTIVITY_PANEL_CHROME_LINES),
    )
    panel_h = visible + ACTIVITY_PANEL_CHROME_LINES
    return visible, panel_h


def activity_panel_height(*, reserved_lines: int = 34) -> int:
    """Lines available for the activity log panel after fixed rows."""
    _, panel_h = activity_log_layout(reserved_lines=reserved_lines)
    return panel_h


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


def _centered_divider(label: str, width: int) -> Text:
    """Horizontal rule with centered label for subsection headers."""
    inner = max(8, width)
    title = f" {label} "
    if len(title) >= inner:
        return Text(title.strip(), style="dim", justify="center")
    pad = inner - len(title)
    left = pad // 2
    right = pad - left
    return Text("─" * left + title + "─" * right, style="dim")


def _render_leverage_liquidation_block(
    state: PaperTradingState,
    *,
    panel_width: Optional[int] = None,
) -> Optional[Group]:
    """Leverage tiers with estimated liquidation prices (market panel only)."""
    session_lev = getattr(state, "leverage", 1.0) or 1.0
    if session_lev <= 1.0:
        return None

    inner = panel_inner_width(panel_width)
    ref_price = state.position_entry_price or state.price
    if ref_price <= 0:
        return None

    side = state.position_side if state.position_side in ("long", "short") else None
    ref_note = (
        f"from entry ${state.position_entry_price:,.0f}"
        if state.position_entry_price
        else "from spot (if opened now)"
    )

    lev_table, value_w = make_kv_table(
        panel_width,
        header_style="bold yellow",
        label_header="Lev",
        value_header="Liq est.",
    )
    for lev in leverage_display_tiers(session_lev):
        lev_table.add_row(
            f"{lev:g}x",
            clip_cell(
                format_liquidation_cell(ref_price, lev, position_side=side),
                value_w,
            ),
        )

    parts: list = [_centered_divider("Leverage", inner), lev_table]
    if side is None:
        parts.append(
            Text(f"↓long / ↑short · {ref_note}", style="dim italic", justify="right")
        )
    else:
        parts.append(Text(ref_note, style="dim italic", justify="right"))
    return Group(*parts)


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

    body: list = [table]
    lev_block = _render_leverage_liquidation_block(state, panel_width=width)
    if lev_block is not None:
        body.append(lev_block)

    return Panel(
        Group(*body),
        title="Market",
        border_style="yellow",
        expand=True,
        width=width,
    )
