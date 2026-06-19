"""CLI helpers for paper trading simulation and status display."""

from __future__ import annotations

import signal
import threading
import time
from typing import Callable, Optional

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
from cli.movers_board import MoversBoard
from cli.paper_display import (
    PaperDisplayContext,
    activity_panel_height,
    clip_cell,
    render_market_panel,
    terminal_column_widths,
    terminal_size,
)
from cli.price_history import PriceHistoryLog
from tradingagents.simulator.activity_messages import (
    format_close_retest_confirm_prompt,
    format_optimization_winner,
    format_reanalyze_confirm_prompt,
    format_session_config_summary,
    format_session_start,
)

from tradingagents.backtest import (
    deploy_winning_strategy,
    optimize_strategies,
    require_optimization_results,
)
from tradingagents.simulator import PaperTradingEngine, PaperTradingState, session_from_optimization
from tradingagents.dataflows.kraken import kraken_status_summary
from tradingagents.dataflows.trading_fees import paper_fee_bps, paper_transaction_cost_pct

console = Console()

PAPER_CONTROLS_TEXT = (
    "(m) movers · (c) close & retest · (r) reanalyze · (q) quit"
)
MOVERS_CONTROLS_TEXT = (
    "(1–9) switch pair · (s) refresh · (m/esc) close movers"
)


def render_paper_state_table(
    state: PaperTradingState,
    *,
    titled: bool = True,
    width: Optional[int] = None,
) -> Table:
    """Rich table for portfolio balance, strategy, and PnL."""
    title = f"Paper Trading — {state.symbol}" if titled else None
    value_max = max(12, (width - 20)) if width else 24
    table = Table(
        title=title,
        show_header=True,
        header_style="bold cyan",
        expand=False,
        pad_edge=False,
        width=width,
    )
    table.add_column("Field", style="dim", min_width=10, max_width=14, no_wrap=True)
    table.add_column(
        "Value",
        justify="right",
        min_width=12,
        max_width=value_max,
        overflow="ellipsis",
        no_wrap=True,
    )
    table.add_row("Strategy", clip_cell(f"{state.strategy_name} ({state.lookback})", value_max))
    table.add_row("Status", clip_cell(state.activity_status, value_max))
    table.add_row("Signal", state.signal)
    table.add_row(
        "Price",
        clip_cell(f"${state.price:,.4f} ({state.price_source})", value_max),
    )
    if state.price_endpoint:
        table.add_row("Price endpoint", clip_cell(state.price_endpoint, value_max))
    if state.vendor_failures:
        table.add_row("Skipped vendors", clip_cell(state.vendor_failures, value_max))
    table.add_row("Equity", f"${state.equity:,.2f}")
    table.add_row("Cash", f"${state.cash:,.2f}")
    pnl_style = "green" if state.pnl >= 0 else "red"
    table.add_row("PnL", f"[{pnl_style}]${state.pnl:,.2f} ({state.pnl_pct:+.2f}%)[/{pnl_style}]")
    sl_str = f"{state.stop_loss_pct * 100:.1f}%" if state.stop_loss_pct is not None else "off"
    tp_str = f"{state.take_profit_pct * 100:.1f}%" if state.take_profit_pct is not None else "off"
    table.add_row(
        "Stop / TP",
        f"{sl_str} / {tp_str}",
    )
    dd_val = f"{state.drawdown_pct:.2f}%" if state.drawdown_pct is not None else "0.00%"
    dd_cap = f"{state.max_drawdown_pct:.1f}% cap" if state.max_drawdown_pct is not None else "no cap"
    table.add_row(
        "Drawdown",
        f"{dd_val} / {dd_cap}",
    )
    if state.adaptive_enabled:
        table.add_row("Last DD review", state.last_drawdown_review)
        table.add_row(
            "DD review window",
            f"{state.effective_drawdown_window_minutes:.0f}m",
        )
    else:
        table.add_row("Adaptive review", "off")
    if state.spike_review_enabled:
        spike_mode = "auto-tuned" if state.spike_intelligent_tuning else "fixed"
        table.add_row("Fast-move review", f"on ({spike_mode})")
        table.add_row(
            "Fast-move watch",
            clip_cell(state.spike_watch_display, value_max),
        )
        table.add_row("Last fast-move review", state.last_spike_review)
        table.add_row("Fast-move reviews", str(state.spike_review_count))
    else:
        table.add_row("Fast-move review", "off")
    table.add_row("Position", state.open_position or "flat")
    table.add_row("Adaptive re-tests", str(state.rebacktest_count))
    return table


def render_paper_portfolio_panel(
    state: PaperTradingState,
    *,
    width: Optional[int] = None,
) -> Panel:
    """Portfolio table wrapped in a panel (matches market / ticks styling)."""
    return Panel(
        render_paper_state_table(state, titled=False, width=width),
        title=f"Paper Trading — {state.symbol}",
        border_style="cyan",
        expand=False,
        width=width,
    )


def render_paper_live_display(
    state: PaperTradingState,
    log: Optional[ActivityLog] = None,
    price_history: Optional[PriceHistoryLog] = None,
    display_ctx: Optional[PaperDisplayContext] = None,
    movers_board: Optional[MoversBoard] = None,
) -> Group:
    """Live view: activity on top, ticks in the middle, portfolio + market, footer."""
    ctx = display_ctx or PaperDisplayContext()
    parts: list = []

    term_w, _term_h = terminal_size()
    full_width = max(60, term_w - 2)

    session_high = price_history.session_high if price_history else None
    session_low = price_history.session_low if price_history else None

    movers_reserve = 8 if ctx.show_movers and movers_board is not None else 0
    reserved = 12 + 22 + 1 + movers_reserve
    activity_h = activity_panel_height(reserved_lines=reserved)
    activity_lines = max(6, activity_h - 3)
    if log is not None and log.enabled:
        parts.append(
            log.render_panel(visible_lines=activity_lines, height=activity_h)
        )

    if price_history is not None:
        parts.append(
            price_history.render_panel(
                width=full_width,
                max_rows=8,
                compact_summary=True,
            )
        )

    w_left, w_right = terminal_column_widths(2)

    def _market_panel(width: int) -> Panel:
        return render_market_panel(
            state,
            ctx,
            session_high=session_high,
            session_low=session_low,
            width=width,
        )

    parts.append(
        Columns(
            [
                render_paper_portfolio_panel(state, width=w_left),
                _market_panel(w_right),
            ],
            expand=False,
            equal=True,
        )
    )

    if ctx.show_movers and movers_board is not None:
        parts.append(movers_board.render_panel(active_pair=state.symbol))

    parts.append(_render_footer_controls(ctx))
    return Group(*parts)


def _render_footer_controls(ctx: PaperDisplayContext) -> Text:
    if ctx.busy_label:
        return Text(f"⏳ {ctx.busy_label} — please wait", style="bold cyan")
    if ctx.status_prompt:
        return Text(ctx.status_prompt, style="bold yellow")
    controls = MOVERS_CONTROLS_TEXT if ctx.show_movers else PAPER_CONTROLS_TEXT
    return Text(controls, style="dim")


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
    transaction_cost_pct = paper_transaction_cost_pct(ticker, cfg)
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
    current_ticker = ticker
    movers_board = MoversBoard(cfg)

    def _echo(message: str) -> None:
        if not use_live_log:
            console.print(f"[dim]{__import__('datetime').datetime.now().strftime('%H:%M:%S')}[/dim] {message}")

    tick_count = 0
    latest_state: Optional[PaperTradingState] = None
    live: Optional[Live] = None
    price_history = PriceHistoryLog()
    display_ctx = PaperDisplayContext(
        tick_interval=interval,
        kraken_status=kraken_status_summary(),
    )
    loop_clock: dict = {"next_tick_at": time.monotonic() + interval}

    def _record_price(state: PaperTradingState) -> None:
        if state.price > 0:
            price_history.record(state.price, state.price_source, state.timestamp)
        loop_clock["next_tick_at"] = time.monotonic() + interval
        display_ctx.seconds_until_next = interval

    display_pending: dict = {"refresh": False, "state": None}

    def _refresh_display(state: Optional[PaperTradingState] = None) -> None:
        target = state or latest_state
        if target is not None and live is not None:
            remaining = loop_clock["next_tick_at"] - time.monotonic()
            display_ctx.seconds_until_next = max(0.0, remaining)
            display_ctx.fee_bps = paper_fee_bps(target.symbol, cfg)
            live.update(
                render_paper_live_display(
                    target, log, price_history, display_ctx, movers_board
                )
            )

    def _request_display_refresh(state: Optional[PaperTradingState] = None) -> None:
        display_pending["refresh"] = True
        if state is not None:
            display_pending["state"] = state

    def _flush_display_refresh() -> None:
        if not display_pending["refresh"]:
            return
        state = display_pending["state"]
        display_pending["refresh"] = False
        display_pending["state"] = None
        _refresh_display(state)

    log = ActivityLog(
        enabled=True,
        echo=_echo if not use_live_log else None,
        on_change=_request_display_refresh,
    )

    stop_requested = False
    quit_requested = False
    engine_ref: dict = {"engine": None}
    switch_requested: dict = {"pair": None}
    previous_sigint = signal.getsignal(signal.SIGINT)

    def _handle_sigint(_signum, _frame) -> None:
        nonlocal stop_requested
        stop_requested = True
        eng = engine_ref.get("engine")
        if eng is not None:
            eng.stop()

    def _resolve_session(symbol: str):
        if strategy_name:
            from tradingagents.simulator import PaperTradingSession, StrategySignal

            take_profit_raw = cfg.get("paper_take_profit_pct")
            return PaperTradingSession(
                symbol=symbol,
                strategy_name=strategy_name,
                lookback=lookback,
                signal=StrategySignal.FLAT,
                initial_equity=float(cfg.get("paper_initial_equity", 10_000.0)),
                stop_loss_pct=float(cfg.get("paper_stop_loss_pct", 0.02)),
                take_profit_pct=float(take_profit_raw) if take_profit_raw is not None else None,
                slippage_bps=paper_fee_bps(symbol, cfg),
            )
        return _run_initial_backtest(
            symbol,
            cfg,
            log,
            echo_to_console=not use_live_log,
        )

    def _run_loop_body(session, symbol: str) -> None:
        nonlocal tick_count, quit_requested, stop_requested, latest_state

        engine = PaperTradingEngine(session, cfg, adaptive_enabled=adaptive_on)
        engine_ref["engine"] = engine
        engine.on_activity = log.append

        def _on_switch(old: str, new: str) -> None:
            log.append(f"Strategy switch (adaptive): {old} → {new}")

        engine.on_strategy_switch = _on_switch

        log.append(
            format_session_start(
                symbol,
                session.strategy_name,
                session.lookback,
                adaptive=adaptive_on,
                interval=interval,
            )
        )
        log.append(
            format_session_config_summary(
                stop_loss_pct=float(session.stop_loss_pct),
                take_profit_pct=session.take_profit_pct,
                adaptive=adaptive_on,
                drawdown_window_minutes=float(
                    cfg.get("drawdown_time_window_minutes", 60)
                ),
                max_drawdown_pct=float(
                    cfg.get("max_allowed_drawdown_pct", 5.0)
                ),
                spike_enabled=bool(cfg.get("paper_spike_review_enabled", False)),
                spike_intelligent_tuning=bool(
                    cfg.get("paper_spike_intelligent_tuning_enabled", False)
                ),
                tick_interval_seconds=interval,
            )
        )

        if not use_live_log:
            console.print(
                Panel(
                    f"Paper simulation for [bold]{symbol}[/bold]\n"
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
            _request_display_refresh(state)

        engine.on_state_change = _on_state

        def _on_tick(_result) -> None:
            nonlocal tick_count
            tick_count += 1
            loop_clock["next_tick_at"] = time.monotonic() + interval
            display_ctx.seconds_until_next = interval
            _flush_display_refresh()

        confirm_state: dict = {"action": None}  # "close" | "reanalyze"
        action_state: dict = {"running": False, "label": ""}

        def _start_background_action(action_fn: Callable[[], object], label: str) -> None:
            if action_state["running"]:
                log.append(f"Already running {action_state['label']} — please wait")
                _refresh_display()
                return

            action_state["running"] = True
            action_state["label"] = label
            display_ctx.busy_label = label
            log.append(f"{label} — started")
            _refresh_display()

            def _worker() -> None:
                try:
                    result = action_fn()
                    if label != "Close & retest" or result:
                        log.append(f"{label} — complete")
                except Exception as exc:
                    log.append(f"{label} — failed: {exc}")
                finally:
                    action_state["running"] = False
                    action_state["label"] = ""
                    display_ctx.busy_label = None
                    _request_display_refresh()

            threading.Thread(target=_worker, name=f"paper-{label}", daemon=True).start()

        def _cancel_confirm(message: str) -> None:
            confirm_state["action"] = None
            display_ctx.status_prompt = None
            log.append(message)
            _refresh_display()

        def _poll_key(timeout: float) -> Optional[str]:
            _flush_display_refresh()
            key = poll_stdin_key(timeout)
            if confirm_state["action"]:
                if key == "y":
                    pending = confirm_state["action"]
                    confirm_state["action"] = None
                    display_ctx.status_prompt = None
                    if pending == "close":
                        log.append("Close & retest confirmed")
                        _start_background_action(
                            lambda: engine.close_open_position(reoptimize=True),
                            "Close & retest",
                        )
                    elif pending == "reanalyze":
                        log.append("Reanalyze confirmed")
                        _start_background_action(engine.reanalyze, "Reanalyze")
                    else:
                        _refresh_display()
                    return None
                if key in ("n", "\x1b"):
                    label = "Close & retest" if confirm_state["action"] == "close" else "Reanalyze"
                    _cancel_confirm(f"{label} cancelled")
                    return None
                return None

            if key in ("\x1b", "\x1b\x1b"):
                if display_ctx.show_movers:
                    display_ctx.show_movers = False
                    _refresh_display()
                return None
            if key == "m":
                display_ctx.show_movers = not display_ctx.show_movers
                if display_ctx.show_movers:
                    movers_board.refresh(log.append, force=True)
                _refresh_display()
                return None
            if display_ctx.show_movers:
                if key is not None and key in "123456789":
                    pair = movers_board.pair_for_hotkey(int(key) - 1)
                    if pair and pair != symbol:
                        switch_requested["pair"] = pair
                        display_ctx.show_movers = False
                        engine.stop()
                    return None
                if key == "s":
                    movers_board.refresh(log.append, force=True)
                    _refresh_display()
                    return None
            if key == "c":
                if action_state["running"]:
                    log.append(f"Busy with {action_state['label']} — please wait")
                    _refresh_display()
                    return None
                confirm_state["action"] = "close"
                display_ctx.status_prompt = format_close_retest_confirm_prompt()
                log.append("Close & retest requested — press (y) to confirm or (n) to cancel")
                _refresh_display()
                return None
            if key == "r":
                if action_state["running"]:
                    log.append(f"Busy with {action_state['label']} — please wait")
                    _refresh_display()
                    return None
                confirm_state["action"] = "reanalyze"
                display_ctx.status_prompt = format_reanalyze_confirm_prompt()
                log.append("Reanalyze requested — press (y) to confirm or (n) to cancel")
                _refresh_display()
                return None
            return key

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
        if not stop_requested and engine._stop_event.is_set() and switch_requested["pair"] is None:
            quit_requested = True

        if switch_requested["pair"] and engine.portfolio.positions:
            engine.close_open_position(reoptimize=False)

    signal.signal(signal.SIGINT, _handle_sigint)
    try:
        with cbreak_stdin():
            if use_live_log:
                console.clear()
                with Live(
                    console=console,
                    refresh_per_second=4,
                    transient=False,
                ) as live_ctx:
                    live = live_ctx
                    while not stop_requested:
                        switch_requested["pair"] = None
                        latest_state = _bootstrap_paper_state(current_ticker, cfg)
                        display_ctx.fee_bps = paper_fee_bps(current_ticker, cfg)
                        _refresh_display(latest_state)
                        session = _resolve_session(current_ticker)
                        if session is None:
                            return
                        latest_state.strategy_name = session.strategy_name
                        latest_state.lookback = session.lookback
                        latest_state.signal = session.signal.value
                        latest_state.symbol = current_ticker
                        _refresh_display(latest_state)
                        _run_loop_body(session, current_ticker)

                        if stop_requested or quit_requested:
                            break
                        next_pair = switch_requested.get("pair")
                        if not next_pair or next_pair == current_ticker:
                            break

                        from tradingagents.simulator.persistence import delete_paper_session

                        equity = float(cfg.get("paper_initial_equity", 10_000.0))
                        eng = engine_ref.get("engine")
                        if eng is not None:
                            equity = eng.portfolio.equity
                        delete_paper_session(current_ticker, cfg)
                        log.append(
                            f"Switching {current_ticker} → {next_pair} "
                            f"(equity ${equity:,.2f})"
                        )
                        cfg["paper_initial_equity"] = equity
                        cfg["paper_fresh_start"] = True
                        price_history.reset()
                        current_ticker = next_pair
            else:
                session = _resolve_session(current_ticker)
                if session is None:
                    return
                _run_loop_body(session, current_ticker)
    finally:
        signal.signal(signal.SIGINT, previous_sigint)

    if latest_state is not None:
        console.print()
        console.print(
            render_paper_live_display(
                latest_state, log, price_history, display_ctx, movers_board
            )
        )
    if quit_requested:
        console.print("[yellow]Paper trading stopped (q). State saved.[/yellow]")
    elif stop_requested:
        console.print("[yellow]Paper trading stopped. State saved.[/yellow]")
    console.print(f"[dim]Paper session ended after {tick_count} tick(s).[/dim]")


def prompt_paper_options(config: dict, *, ticker: str) -> dict:
    """Interactive paper-trading options (post-analysis deploy flow)."""
    from cli.paper_interactive import (
        _prompt_paper_monitoring_settings,
        _prompt_risk_exit_settings,
        _prompt_tick_interval,
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

    tick_interval = _prompt_tick_interval(config)
    stop_loss_pct, take_profit_pct = _prompt_risk_exit_settings(config)
    adaptive, window, threshold, spike = _prompt_paper_monitoring_settings(
        config,
        stop_loss_pct=stop_loss_pct,
    )
    config["paper_tick_interval_seconds"] = tick_interval
    config["paper_stop_loss_pct"] = stop_loss_pct
    config["paper_take_profit_pct"] = take_profit_pct
    config["drawdown_time_window_minutes"] = window
    config["paper_loss_review_minutes"] = window
    config["max_allowed_drawdown_pct"] = threshold
    config["paper_loss_threshold_pct"] = threshold
    config["paper_adaptive_enabled"] = adaptive
    config["paper_spike_review_enabled"] = spike.enabled and adaptive
    config["paper_spike_intelligent_tuning_enabled"] = (
        spike.intelligent_tuning and spike.enabled and adaptive
    )
    config["paper_spike_1m_loss_pct"] = spike.loss_1m_pct
    config["paper_spike_5m_loss_pct"] = spike.loss_5m_pct
    config["paper_spike_10m_loss_pct"] = spike.loss_10m_pct
    config["paper_spike_switch_min_net_profit"] = spike.switch_min_net_profit
    config["paper_spike_min_cooldown_minutes"] = spike.min_cooldown_minutes
    ticks = _prompt_ticks()
    return {
        "adaptive": adaptive,
        "spike_review": spike.enabled,
        "spike_intelligent_tuning": spike.intelligent_tuning,
        "tick_interval_seconds": tick_interval,
        "ticks": ticks,
    }
