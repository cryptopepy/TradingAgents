"""Rich layout for the visual backtest pane."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from rich.console import Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from cli.activity_log import ActivityLog
from cli.paper_display import terminal_size
from cli.tui.visual_backtest.setup import VisualBacktestParams, format_params_summary
from tradingagents.backtest.engine import BacktestResult

VISUAL_CONTROLS_TEXT = "(r) reconfigure · (↑↓ scroll) · (q) quit session"


@dataclass
class VisualBacktestDisplayContext:
    """Mutable state for rendering the visual backtest pane."""

    params: Optional[VisualBacktestParams] = None
    state: str = "idle"  # idle | fetching | running | waiting_next | complete
    status_message: str = "Press Enter to configure visual backtest"
    error_message: Optional[str] = None
    fetch_source: str = ""
    bar_count: int = 0
    strategy_name: str = ""
    strategy_index: int = 0
    strategy_total: int = 0
    current_result: Optional[BacktestResult] = None
    price_samples: List[str] = field(default_factory=list)
    summary_rows: List[tuple[str, float, float, int]] = field(default_factory=list)
    waiting_prompt: Optional[str] = None
    busy_label: Optional[str] = None


def _format_trade_line(side: str, entry: float, exit_p: float, pnl_pct: float, reason: str) -> str:
    action = "BUY" if side == "long" else "SELL"
    style_sign = "+" if pnl_pct >= 0 else ""
    return (
        f"{action} entry ${entry:,.4f} → exit ${exit_p:,.4f} "
        f"PnL {style_sign}{pnl_pct:.2f}% ({reason})"
    )


def format_entry_line(side: str, price: float, when: str) -> str:
    action = "BUY" if side == "long" else "SHORT"
    return f"{action} @ ${price:,.4f} ({when})"


def append_trade_to_log(log: ActivityLog, record, *, kind: str = "exit") -> None:
    if kind == "entry":
        log.append(format_entry_line(record[0], record[1], record[2]))
        return
    line = _format_trade_line(
        record.side,
        record.entry_price,
        record.exit_price,
        record.pnl_pct,
        record.exit_reason,
    )
    log.append(line)


def render_visual_backtest_display(
    ctx: VisualBacktestDisplayContext,
    log: ActivityLog,
) -> Group:
    term_w, _ = terminal_size()
    full_width = max(60, term_w - 2)
    parts: list = []

    title = "Visual Backtest"
    if ctx.params is not None:
        title = f"Visual Backtest — {ctx.params.ticker}"
    header_lines = [title]
    if ctx.params is not None:
        header_lines.append(format_params_summary(ctx.params))
    if ctx.fetch_source:
        header_lines.append(f"Data: {ctx.fetch_source} ({ctx.bar_count:,} bars)")
    if ctx.strategy_name:
        prog = ""
        if ctx.strategy_total:
            prog = f" [{ctx.strategy_index}/{ctx.strategy_total}]"
        header_lines.append(f"Strategy: {ctx.strategy_name}{prog}")
    if ctx.busy_label:
        header_lines.append(f"⏳ {ctx.busy_label}")
    elif ctx.status_message:
        header_lines.append(ctx.status_message)
    if ctx.error_message:
        header_lines.append(f"[red]{ctx.error_message}[/red]")
    parts.append(Panel("\n".join(header_lines), border_style="cyan"))

    if ctx.price_samples:
        price_panel = Panel(
            "\n".join(ctx.price_samples[-12:]),
            title="Price (sampled)",
            border_style="blue",
        )
        parts.append(price_panel)

    visible = min(14, max(6, int(log.max_lines // 10) or 11))
    msg_width = max(40, full_width - 14)
    parts.append(
        log.render_panel(
            visible_lines=visible,
            height=visible + 2,
            max_width=msg_width,
        )
    )

    if ctx.current_result is not None and ctx.state in ("running", "waiting_next", "complete"):
        res = ctx.current_result
        summary = Table.grid(padding=(0, 2))
        summary.add_row(
            "Return",
            f"{res.total_return_pct:+.2f}%",
            "Trades",
            str(res.num_trades),
            "Win rate",
            f"{res.win_rate:.1f}%",
        )
        parts.append(Panel(summary, title="Current strategy", border_style="green"))

    if ctx.summary_rows and ctx.state == "complete":
        table = Table(title="All strategies", expand=True)
        table.add_column("Strategy")
        table.add_column("Return %", justify="right")
        table.add_column("Win %", justify="right")
        table.add_column("Trades", justify="right")
        for name, ret, win, n in sorted(ctx.summary_rows, key=lambda r: r[1], reverse=True):
            table.add_row(name, f"{ret:+.2f}", f"{win:.1f}", str(n))
        parts.append(table)

    if ctx.waiting_prompt:
        parts.append(Text(ctx.waiting_prompt, style="bold yellow"))
    parts.append(Text(VISUAL_CONTROLS_TEXT, style="dim"))
    return Group(*parts)
