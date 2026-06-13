"""CLI helpers for paper trading simulation and status display."""

from __future__ import annotations

import signal
from typing import Optional

from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from cli.activity_log import (
    ActivityLog,
    is_live_display_tty,
    make_backtest_callbacks,
)
from cli.keyboard_input import cbreak_stdin, poll_stdin_key
from tradingagents.simulator.activity_messages import (
    format_optimization_winner,
    format_session_start,
)

from tradingagents.backtest import (
    deploy_winning_strategy,
    optimize_strategies,
    require_optimization_results,
)
from tradingagents.simulator import PaperTradingEngine, PaperTradingState, session_from_optimization

console = Console()

PAPER_CONTROLS_TEXT = "Controls: (c) Close and retest · (q) quit"


def render_paper_state_table(state: PaperTradingState) -> Table:
    """Rich table for portfolio balance, strategy, and PnL."""
    table = Table(title=f"Paper Trading — {state.symbol}", show_header=True, header_style="bold cyan")
    table.add_column("Field", style="dim")
    table.add_column("Value", justify="right")
    table.add_row("Strategy", f"{state.strategy_name} ({state.lookback})")
    table.add_row("Signal", state.signal)
    table.add_row("Price", f"${state.price:,.4f} ({state.price_source})")
    if state.price_endpoint:
        table.add_row("Price endpoint", state.price_endpoint)
    if state.vendor_failures:
        table.add_row("Skipped vendors", state.vendor_failures)
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


def render_paper_live_display(
    state: PaperTradingState,
    log: Optional[ActivityLog] = None,
) -> Group:
    """Rich live view: optional activity log, status table, controls footer."""
    controls = Text(PAPER_CONTROLS_TEXT, style="dim")
    parts = []
    if log is not None and log.enabled:
        parts.append(log.render_panel())
    parts.extend([render_paper_state_table(state), controls])
    return Group(*parts)


def _run_initial_backtest(
    ticker: str,
    cfg: dict,
    log: ActivityLog,
):
    """Run strategy optimization with visible per-horizon progress."""
    log.append(f"Running backtest to select strategy for {ticker}…")
    end_date = __import__("datetime").datetime.now().strftime("%Y-%m-%d")
    on_start, on_complete, on_skipped = make_backtest_callbacks(log)
    sl = float(cfg.get("paper_stop_loss_pct", 0.02))
    tp_raw = cfg.get("paper_take_profit_pct")
    transaction_cost_pct = 10.0 / 10_000.0
    optimization = require_optimization_results(
        optimize_strategies(
            ticker,
            end_date,
            config=cfg,
            stop_loss_pct=sl,
            take_profit_pct=float(tp_raw) if tp_raw is not None else None,
            transaction_cost_pct=transaction_cost_pct,
            on_horizon_start=on_start,
            on_horizon_complete=on_complete,
            on_horizon_skipped=on_skipped,
        )
    )
    optimization = deploy_winning_strategy(optimization, cfg)
    if optimization.winner is None or not optimization.deployable:
        reason = (
            "; ".join(optimization.gate_failures)
            if optimization.gate_failures
            else "no candidate passed quality gates"
        )
        log.append(f"No deployable strategy — {reason}")
        console.print(f"[red]No deployable strategy — {reason}[/red]")
        return None
    log.append(format_optimization_winner(optimization.winner))
    console.print(
        f"[green]Recommended strategy:[/green] {optimization.winner.strategy_name} "
        f"({optimization.winner.lookback})"
    )
    return session_from_optimization(optimization, cfg)


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
    use_live_log = is_live_display_tty()

    def _echo(message: str) -> None:
        if not use_live_log:
            console.print(f"[dim]{__import__('datetime').datetime.now().strftime('%H:%M:%S')}[/dim] {message}")

    log = ActivityLog(enabled=True, echo=_echo if not use_live_log else None)

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
        session = _run_initial_backtest(ticker, cfg, log)
        if session is None:
            return

    engine = PaperTradingEngine(session, cfg, adaptive_enabled=adaptive_on)
    interval = float(cfg.get("paper_tick_interval_seconds", 10.0))
    stop_requested = False
    quit_requested = False
    previous_sigint = signal.getsignal(signal.SIGINT)

    def _handle_sigint(_signum, _frame) -> None:
        nonlocal stop_requested
        stop_requested = True
        engine.stop()

    log.append(
        format_session_start(
            ticker,
            session.strategy_name,
            session.lookback,
            adaptive=adaptive_on,
            interval=interval,
        )
    )

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
    live: Optional[Live] = None

    def _refresh_display(state: Optional[PaperTradingState] = None) -> None:
        target = state or latest_state
        if target is not None and live is not None:
            live.update(render_paper_live_display(target, log))

    engine.on_activity = log.append

    def _on_switch(old: str, new: str) -> None:
        log.append(f"Strategy switch (adaptive): {old} → {new}")

    engine.on_strategy_switch = _on_switch

    signal.signal(signal.SIGINT, _handle_sigint)
    try:
        with cbreak_stdin():
            def _run_loop_body() -> None:
                nonlocal tick_count, quit_requested, stop_requested, latest_state

                def _on_state(state: PaperTradingState) -> None:
                    nonlocal latest_state
                    latest_state = state
                    if live is not None:
                        _refresh_display(state)

                engine.on_state_change = _on_state

                def _on_tick(_result) -> None:
                    nonlocal tick_count
                    tick_count += 1
                    if live is not None:
                        _refresh_display()

                def _poll_key(timeout: float) -> Optional[str]:
                    return poll_stdin_key(timeout)

                if latest_state is None:
                    latest_state = engine.get_state()
                    if live is not None:
                        _refresh_display(latest_state)

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

            if use_live_log:
                with Live(
                    console=console,
                    refresh_per_second=4,
                    transient=False,
                ) as live_ctx:
                    live = live_ctx
                    _run_loop_body()
            else:
                _run_loop_body()
    finally:
        signal.signal(signal.SIGINT, previous_sigint)

    if latest_state is not None:
        console.print()
        console.print(render_paper_live_display(latest_state, log))
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
