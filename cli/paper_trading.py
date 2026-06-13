"""CLI helpers for paper trading simulation and status display."""

from __future__ import annotations

import signal
import time
from typing import Optional

from rich.columns import Columns
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
from cli.paper_display import PaperDisplayContext, render_market_panel
from cli.price_history import PriceHistoryLog
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

PAPER_CONTROLS_TEXT = (
    "Controls: (c) Close position and retest · (r) Reanalyze · (q) quit"
)


def render_paper_state_table(state: PaperTradingState, *, titled: bool = True) -> Table:
    """Rich table for portfolio balance, strategy, and PnL."""
    title = f"Paper Trading — {state.symbol}" if titled else None
    table = Table(title=title, show_header=True, header_style="bold cyan", expand=True, pad_edge=False)
    table.add_column("Field", style="dim", min_width=12)
    table.add_column("Value", justify="right", min_width=14)
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


def render_paper_portfolio_panel(state: PaperTradingState) -> Panel:
    """Portfolio table wrapped in a panel (matches market / ticks styling)."""
    return Panel(
        render_paper_state_table(state, titled=False),
        title=f"Paper Trading — {state.symbol}",
        border_style="cyan",
        expand=True,
    )


def render_paper_live_display(
    state: PaperTradingState,
    log: Optional[ActivityLog] = None,
    price_history: Optional[PriceHistoryLog] = None,
    display_ctx: Optional[PaperDisplayContext] = None,
) -> Group:
    """Rich live view: activity log, status + market + price history, controls."""
    controls = Text(PAPER_CONTROLS_TEXT, style="dim")
    parts = []
    if log is not None and log.enabled:
        parts.append(log.render_panel())

    ctx = display_ctx or PaperDisplayContext()
    market_panel = render_market_panel(
        state,
        ctx,
        session_high=price_history.session_high if price_history else None,
        session_low=price_history.session_low if price_history else None,
    )

    if price_history is not None:
        # Columns (not Layout) — Layout split_row draws full-height dividers in Live.
        parts.append(
            Columns(
                [
                    render_paper_portfolio_panel(state),
                    market_panel,
                    price_history.render_panel(),
                ],
                expand=True,
                equal=False,
            )
        )
    else:
        parts.append(
            Columns(
                [render_paper_portfolio_panel(state), market_panel],
                expand=True,
                equal=False,
            )
        )
    parts.append(controls)
    return Group(*parts)


def _bootstrap_paper_state(ticker: str, cfg: dict) -> PaperTradingState:
    """Placeholder status while the initial backtest selects a strategy."""
    equity = float(cfg.get("paper_initial_equity", 10_000.0))
    return PaperTradingState(
        symbol=ticker,
        strategy_name="(selecting…)",
        lookback="—",
        signal="flat",
        equity=equity,
        cash=equity,
        initial_equity=equity,
        pnl=0.0,
        pnl_pct=0.0,
        price=0.0,
        price_source="—",
        drawdown_pct=0.0,
        rebacktest_count=0,
    )


def _run_initial_backtest(
    ticker: str,
    cfg: dict,
    log: ActivityLog,
    *,
    echo_to_console: bool = True,
):
    """Run strategy optimization with visible per-horizon progress."""
    log.append(f"Running backtest to select strategy for {ticker}…")
    end_date = __import__("datetime").datetime.now().strftime("%Y-%m-%d")
    on_start, on_complete, on_skipped, on_provider_attempt = make_backtest_callbacks(log)
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
            on_horizon_provider_attempt=on_provider_attempt,
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
        if echo_to_console:
            console.print(f"[red]No deployable strategy — {reason}[/red]")
        return None
    log.append(format_optimization_winner(optimization.winner))
    if echo_to_console:
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
    interval = float(cfg.get("paper_tick_interval_seconds", 10.0))

    def _echo(message: str) -> None:
        if not use_live_log:
            console.print(f"[dim]{__import__('datetime').datetime.now().strftime('%H:%M:%S')}[/dim] {message}")

    tick_count = 0
    latest_state: Optional[PaperTradingState] = None
    live: Optional[Live] = None
    price_history = PriceHistoryLog()
    display_ctx = PaperDisplayContext(tick_interval=interval)
    loop_clock: dict = {"next_tick_at": time.monotonic() + interval}

    def _record_price(state: PaperTradingState) -> None:
        if state.price > 0:
            price_history.record(state.price, state.price_source, state.timestamp)
        loop_clock["next_tick_at"] = time.monotonic() + interval
        display_ctx.seconds_until_next = interval

    def _refresh_display(state: Optional[PaperTradingState] = None) -> None:
        target = state or latest_state
        if target is not None and live is not None:
            remaining = loop_clock["next_tick_at"] - time.monotonic()
            display_ctx.seconds_until_next = max(0.0, remaining)
            live.update(render_paper_live_display(target, log, price_history, display_ctx))

    log = ActivityLog(
        enabled=True,
        echo=_echo if not use_live_log else None,
        on_change=lambda: _refresh_display(),
    )

    stop_requested = False
    quit_requested = False
    engine_ref: dict = {"engine": None}
    previous_sigint = signal.getsignal(signal.SIGINT)

    def _handle_sigint(_signum, _frame) -> None:
        nonlocal stop_requested
        stop_requested = True
        eng = engine_ref.get("engine")
        if eng is not None:
            eng.stop()

    def _resolve_session():
        if strategy_name:
            from tradingagents.simulator import PaperTradingSession, StrategySignal

            take_profit_raw = cfg.get("paper_take_profit_pct")
            return PaperTradingSession(
                symbol=ticker,
                strategy_name=strategy_name,
                lookback=lookback,
                signal=StrategySignal.FLAT,
                initial_equity=float(cfg.get("paper_initial_equity", 10_000.0)),
                stop_loss_pct=float(cfg.get("paper_stop_loss_pct", 0.02)),
                take_profit_pct=float(take_profit_raw) if take_profit_raw is not None else None,
            )
        return _run_initial_backtest(
            ticker,
            cfg,
            log,
            echo_to_console=not use_live_log,
        )

    def _run_loop_body(session) -> None:
        nonlocal tick_count, quit_requested, stop_requested, latest_state

        engine = PaperTradingEngine(session, cfg, adaptive_enabled=adaptive_on)
        engine_ref["engine"] = engine
        engine.on_activity = log.append

        def _on_switch(old: str, new: str) -> None:
            log.append(f"Strategy switch (adaptive): {old} → {new}")

        engine.on_strategy_switch = _on_switch

        log.append(
            format_session_start(
                ticker,
                session.strategy_name,
                session.lookback,
                adaptive=adaptive_on,
                interval=interval,
            )
        )

        if not use_live_log:
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

        def _on_state(state: PaperTradingState) -> None:
            nonlocal latest_state
            latest_state = state
            _record_price(state)
            _refresh_display(state)

        engine.on_state_change = _on_state

        def _on_tick(_result) -> None:
            nonlocal tick_count
            tick_count += 1
            loop_clock["next_tick_at"] = time.monotonic() + interval
            display_ctx.seconds_until_next = interval
            _refresh_display()

        def _poll_key(timeout: float) -> Optional[str]:
            return poll_stdin_key(timeout)

        latest_state = engine.get_state()
        _record_price(latest_state)
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

    signal.signal(signal.SIGINT, _handle_sigint)
    try:
        with cbreak_stdin():
            if use_live_log:
                latest_state = _bootstrap_paper_state(ticker, cfg)
                with Live(
                    console=console,
                    refresh_per_second=4,
                    transient=False,
                ) as live_ctx:
                    live = live_ctx
                    _refresh_display(latest_state)
                    session = _resolve_session()
                    if session is None:
                        return
                    latest_state.strategy_name = session.strategy_name
                    latest_state.lookback = session.lookback
                    latest_state.signal = session.signal.value
                    _refresh_display(latest_state)
                    _run_loop_body(session)
            else:
                session = _resolve_session()
                if session is None:
                    return
                _run_loop_body(session)
    finally:
        signal.signal(signal.SIGINT, previous_sigint)

    if latest_state is not None:
        console.print()
        console.print(render_paper_live_display(latest_state, log, price_history, display_ctx))
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
