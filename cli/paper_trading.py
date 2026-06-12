"""CLI helpers for paper trading simulation and status display."""

from __future__ import annotations

import signal
import sys
from typing import Optional

import questionary
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table

from tradingagents.backtest import (
    deploy_winning_strategy,
    optimize_strategies,
    require_optimization_results,
)
from tradingagents.simulator import PaperTradingEngine, PaperTradingState, session_from_optimization

console = Console()


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
    table.add_row("Position", state.open_position or "flat")
    table.add_row("Adaptive re-tests", str(state.rebacktest_count))
    return table


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

        session = PaperTradingSession(
            symbol=ticker,
            strategy_name=strategy_name,
            lookback=lookback,
            signal=StrategySignal.FLAT,
            initial_equity=float(cfg.get("paper_initial_equity", 100_000.0)),
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

    def _handle_sigint(_signum, _frame) -> None:
        nonlocal stop_requested
        stop_requested = True
        engine.stop()

    signal.signal(signal.SIGINT, _handle_sigint)

    console.print(
        Panel(
            f"Paper simulation for [bold]{ticker}[/bold]\n"
            f"Strategy: {session.strategy_name} | Adaptive: {'on' if adaptive_on else 'off'}\n"
            f"Interval: {interval}s | Press Ctrl+C to stop",
            title="Paper Trading Simulation",
            border_style="green",
        )
    )

    tick_count = 0
    latest_state: Optional[PaperTradingState] = None

    def _on_state(state: PaperTradingState) -> None:
        nonlocal latest_state
        latest_state = state

    def _on_switch(old: str, new: str) -> None:
        console.print(
            f"[yellow][AUTONOMOUS ROTATION]:[/yellow] Strategy changed from [{old}] to [{new}] "
            "due to threshold violation."
        )

    engine.on_state_change = _on_state
    engine.on_strategy_switch = _on_switch

    with Live(console=console, refresh_per_second=4, transient=False) as live:
        def _on_tick(_result) -> None:
            nonlocal tick_count
            tick_count += 1
            if latest_state is not None:
                live.update(render_paper_state_table(latest_state))

        try:
            engine.run_loop(
                interval_seconds=interval,
                max_ticks=ticks,
                on_tick=_on_tick,
            )
        except KeyboardInterrupt:
            stop_requested = True
            engine.stop()

    if latest_state is not None:
        console.print()
        console.print(render_paper_state_table(latest_state))
    console.print(f"[dim]Paper session ended after {tick_count} tick(s).[/dim]")


def prompt_paper_options(config: dict) -> dict:
    """Interactive paper-trading options."""
    adaptive = questionary.confirm(
        "Enable adaptive strategy switching on sustained losses?",
        default=bool(config.get("paper_adaptive_enabled", True)),
    ).ask()
    ticks_str = questionary.text(
        "Number of ticks (empty = run until Ctrl+C):",
        default="",
    ).ask() or ""
    ticks = int(ticks_str) if ticks_str.strip().isdigit() else None
    window = questionary.text(
        "Drawdown review window (minutes):",
        default=str(config.get("drawdown_time_window_minutes", config.get("paper_loss_review_minutes", 60))),
    ).ask()
    threshold = questionary.text(
        "Max allowed drawdown % (e.g. 5.0):",
        default=str(config.get("max_allowed_drawdown_pct", config.get("paper_loss_threshold_pct", 5.0))),
    ).ask()
    if window:
        config["drawdown_time_window_minutes"] = float(window)
        config["paper_loss_review_minutes"] = float(window)
    if threshold:
        config["max_allowed_drawdown_pct"] = float(threshold)
        config["paper_loss_threshold_pct"] = float(threshold)
    return {"adaptive": adaptive, "ticks": ticks}
