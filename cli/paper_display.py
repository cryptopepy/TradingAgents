"""Extra panels for paper trading live display."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from rich.panel import Panel
from rich.table import Table

from tradingagents.simulator.paper_engine import PaperTradingState


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
) -> Panel:
    """Compact market / timing strip between portfolio and price ticks."""
    table = Table(show_header=True, header_style="bold yellow", expand=True, pad_edge=False)
    table.add_column("Metric", style="dim", min_width=14)
    table.add_column("Value", justify="right", min_width=18)

    table.add_row("Spot", f"${state.price:,.4f}" if state.price else "—")
    table.add_row("Feed", state.price_source or "—")
    if state.price_endpoint:
        table.add_row("Endpoint", state.price_endpoint)
    if session_high is not None and session_low is not None:
        table.add_row("Session H/L", f"${session_high:,.2f} / ${session_low:,.2f}")
    table.add_row("Tick every", f"{ctx.tick_interval:.0f}s")
    if ctx.seconds_until_next is not None:
        table.add_row("Next tick", f"{max(0.0, ctx.seconds_until_next):.1f}s")
    table.add_row("Signal", state.signal)
    if state.open_position:
        table.add_row("Position", state.open_position)
    if ctx.kraken_status:
        table.add_row("Kraken", ctx.kraken_status)
    if ctx.fee_bps is not None:
        table.add_row("Fee (side)", f"{ctx.fee_bps:.1f} bps")

    return Panel(table, title="Market", border_style="yellow", expand=True)
