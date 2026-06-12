"""CLI helpers for paper trading simulation and status display."""

from __future__ import annotations

import signal
import sys
from typing import Optional

from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from cli.keyboard_input import cbreak_stdin, poll_stdin_key

from tradingagents.backtest import (
    deploy_winning_strategy,
    optimize_strategies,
    require_optimization_results,
)
from tradingagents.simulator import PaperTradingEngine, PaperTradingState, session_from_optimization

console = Console()

PAPER_CONTROLS_TEXT = "Controls: (c) close position · (q) quit"


def render_paper_state_table(state: PaperTradingState) -> Table:
    """Rich table for portfolio balance, strategy, and PnL."""
    table = Table(title=f"Paper Trading — {state.symbol}", show_header=True, header_style="bold cyan")
    table.add_column("Field", style="dim")
    table.add_column("Value", justify="right")
    table.add_row("Strategy", f"{state.strategy_name} ({state.lookback})")
    table.add_row("Signal", state.signal)
    table.add_row("Price", f"${state.price:,.4f} ({state.price_source})")
    table.add_row("Equity", f"${state.equity:,.2f}")
    table.add_row("Cash", f"${state.cash:,.2f}")
    pnl_style = "green" if state.pnl >= 0 else "red"
    table.add_row("PnL", f"[{pnl_style}]${state.pnl:,.2f} ({state.pnl_pct:+.2f}%)[/{pnl_style}]")
    table.add_row("Drawdown", f"{state.drawdown_pct:.2f}%")
    table.add_row("Last DD review", state.last_drawdown_review)
    table.add_row(
        "DD review window",
        f"{state.effective_drawdown_window_minutes:.0f}m",
    )
    table.add_row("Position", state.open_position or "flat")
    table.add_row("Adaptive re-tests", str(state.rebacktest_count))
    return table


def render_paper_live_display(state: PaperTradingState) -> Group:
    """Rich live view: status table plus keyboard controls footer."""
    controls = Text(PAPER_CONTROLS_TEXT, style="dim")
    return Group(render_paper_state_table(state), controls)


def run_paper_session(
    ticker: str,
    config: dict,
    *,
    ticks: Optional[int] = None,
    adaptive: Optional[bool] = None,
    strategy_name: Optional[str] = None,
    lookback: str = "24h",
) -> None:
    """Run interactive paper trading with live Rich status updates."""
    cfg = dict(config)
    adaptive_on = adaptive if adaptive is not None else bool(cfg.get("paper_adaptive_enabled", True))

    if strategy_name:
        from tradingagents.simulator import PaperTradingSession, StrategySignal

        take_profit_raw = cfg.get("paper_take_profit_pct")
        session = PaperTradingSession(
            symbol=ticker,
            strategy_name=strategy_name,
            lookback=lookback,
            signal=StrategySignal.FLAT,
            initial_equity=float(cfg.get("paper_initial_equity", 10_000.0)),
            stop_loss_pct=float(cfg.get("paper_stop_loss_pct", 0.02)),
            take_profit_pct=float(take_profit_raw) if take_profit_raw is not None else None,
        )
    else:
        console.print(f"[cyan]Running backtest to select strategy for {ticker}…[/cyan]")
        end_date = __import__("datetime").datetime.now().strftime("%Y-%m-%d")
        optimization = require_optimization_results(optimize_strategies(ticker, end_date))
        optimization = deploy_winning_strategy(optimization, cfg)
        if optimization.winner is None:
            console.print("[red]No winning strategy found — cannot start paper trading.[/red]")
            return
        session = session_from_optimization(optimization, cfg)
        console.print(
            f"[green]Recommended strategy:[/green] {session.strategy_name} ({session.lookback})"
        )

    engine = PaperTradingEngine(session, cfg, adaptive_enabled=adaptive_on)
    interval = float(cfg.get("paper_tick_interval_seconds", 10.0))
    stop_requested = False
    quit_requested = False
    previous_sigint = signal.getsignal(signal.SIGINT)

    def _handle_sigint(_signum, _frame) -> None:
        nonlocal stop_requested
        stop_requested = True
        engine.stop()

    console.print(
        Panel(
            f"Paper simulation for [bold]{ticker}[/bold]\n"
            f"Strategy: {session.strategy_name} | Adaptive: {'on' if adaptive_on else 'off'}\n"
            f"Interval: {interval}s\n"
            f"{PAPER_CONTROLS_TEXT}",
            title="Paper Trading Simulation",
            border_style="green",
        )
    )

    tick_count = 0
    latest_state: Optional[PaperTradingState] = None

    def _on_switch(old: str, new: str) -> None:
        console.print(
            f"[yellow][AUTONOMOUS ROTATION]:[/yellow] Strategy changed from [{old}] to [{new}] "
            "due to threshold violation."
        )

    engine.on_strategy_switch = _on_switch

    signal.signal(signal.SIGINT, _handle_sigint)
    try:
        with cbreak_stdin():
            with Live(console=console, refresh_per_second=4, transient=False) as live:
                def _on_state(state: PaperTradingState) -> None:
                    nonlocal latest_state
                    latest_state = state
                    live.update(render_paper_live_display(state))

                engine.on_state_change = _on_state

                def _on_tick(_result) -> None:
                    nonlocal tick_count
                    tick_count += 1
                    if latest_state is not None:
                        live.update(render_paper_live_display(latest_state))

                def _poll_key(timeout: float) -> Optional[str]:
                    return poll_stdin_key(timeout)

                try:
                    engine.run_loop(
                        interval_seconds=interval,
                        max_ticks=ticks,
                        on_tick=_on_tick,
                        poll_key=_poll_key,
                    )
                except KeyboardInterrupt:
                    stop_requested = True
                    engine.stop()
                if not stop_requested and engine._stop_event.is_set():
                    quit_requested = True
    finally:
        signal.signal(signal.SIGINT, previous_sigint)

    if latest_state is not None:
        console.print()
        console.print(render_paper_live_display(latest_state))
    if quit_requested:
        console.print("[yellow]Paper trading stopped (q). State saved.[/yellow]")
    elif stop_requested:
        console.print("[yellow]Paper trading stopped. State saved.[/yellow]")
    console.print(f"[dim]Paper session ended after {tick_count} tick(s).[/dim]")


def prompt_paper_options(config: dict, *, ticker: str) -> dict:
    """Interactive paper-trading options (post-analysis deploy flow)."""
    from cli.paper_interactive import (
        _prompt_adaptive_settings,
        _prompt_ticks,
        _resolve_equity_and_session,
    )

    equity, _, start_fresh = _resolve_equity_and_session(
        ticker=ticker,
        config=config,
        interactive=True,
    )
    config["paper_initial_equity"] = equity
    config["paper_fresh_start"] = start_fresh

    adaptive, window, threshold = _prompt_adaptive_settings(config)
    config["drawdown_time_window_minutes"] = window
    config["paper_loss_review_minutes"] = window
    config["max_allowed_drawdown_pct"] = threshold
    config["paper_loss_threshold_pct"] = threshold
    config["paper_adaptive_enabled"] = adaptive
    ticks = _prompt_ticks()
    return {"adaptive": adaptive, "ticks": ticks}
