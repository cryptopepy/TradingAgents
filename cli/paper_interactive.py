"""Interactive prompts and parameter resolution for ``tradingagents paper``."""

from __future__ import annotations

import sys
from dataclasses import dataclass, replace
from typing import Optional

import questionary
from rich.console import Console

from tradingagents.backtest.strategies import STRATEGY_REGISTRY
from tradingagents.backtest.validation import (
    BacktestValidationError,
    validate_positive_float,
    validate_ticker,
)
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.simulator.persistence import delete_paper_session, load_paper_session

console = Console()

DEFAULT_TICKER = "BTC/USDT"
DEFAULT_EQUITY = float(DEFAULT_CONFIG.get("paper_initial_equity", 10_000.0))
DEFAULT_STRATEGY = "ema_crossover"
STRATEGY_AUTO = "__auto_backtest__"


@dataclass(frozen=True)
class SpikeSettings:
    """Fast-move review options collected during setup."""

    enabled: bool = False
    intelligent_tuning: bool = False
    loss_1m_pct: float = 1.5
    loss_5m_pct: float = 2.0
    loss_10m_pct: float = 2.5
    switch_min_net_profit: float = 0.005
    min_cooldown_minutes: Optional[float] = None


@dataclass(frozen=True)
class PaperRunParams:
    ticker: str
    strategy_name: Optional[str]
    lookback: str
    initial_equity: float
    ticks: Optional[int]
    tick_interval_seconds: float
    live_mode: bool
    stop_loss_pct: float
    take_profit_pct: Optional[float]
    leverage: float
    adaptive_enabled: bool
    spike_review_enabled: bool
    spike_intelligent_tuning: bool
    spike_1m_loss_pct: float
    spike_5m_loss_pct: float
    spike_10m_loss_pct: float
    spike_switch_min_net_profit: float
    spike_min_cooldown_minutes: Optional[float]
    drawdown_window_minutes: float
    max_drawdown_pct: float
    resume_saved_session: bool = False
    fresh_start: bool = False


def _is_interactive_tty() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def _default_drawdown_window(config: dict) -> float:
    return float(
        config.get(
            "drawdown_time_window_minutes",
            config.get("paper_loss_review_minutes", 60),
        )
    )


def _default_drawdown_pct(config: dict) -> float:
    return float(
        config.get(
            "max_allowed_drawdown_pct",
            config.get("paper_loss_threshold_pct", 5.0),
        )
    )


def _default_stop_loss_pct(config: dict) -> float:
    return float(config.get("paper_stop_loss_pct", 0.02))


def _default_take_profit_pct(config: dict) -> Optional[float]:
    raw = config.get("paper_take_profit_pct")
    if raw is None:
        return None
    return float(raw)


def _default_tick_interval(config: dict) -> float:
    return float(config.get("paper_tick_interval_seconds", 10.0))


def _default_spike_settings(config: dict) -> SpikeSettings:
    cooldown = config.get("paper_spike_min_cooldown_minutes")
    return SpikeSettings(
        enabled=bool(config.get("paper_spike_review_enabled", True)),
        intelligent_tuning=bool(config.get("paper_spike_intelligent_tuning_enabled", True)),
        loss_1m_pct=float(config.get("paper_spike_1m_loss_pct", 1.5)),
        loss_5m_pct=float(config.get("paper_spike_5m_loss_pct", 2.0)),
        loss_10m_pct=float(config.get("paper_spike_10m_loss_pct", 2.5)),
        switch_min_net_profit=float(config.get("paper_spike_switch_min_net_profit", 0.005)),
        min_cooldown_minutes=float(cooldown) if cooldown is not None else None,
    )


def _parse_optional_positive_float(raw: str, *, name: str) -> Optional[float]:
    text = raw.strip()
    if not text:
        return None
    try:
        value = float(text)
    except ValueError as exc:
        raise BacktestValidationError(f"{name} must be a number, got {raw!r}") from exc
    validate_positive_float(value, name=name, minimum=0.1)
    return value


def _stored_fraction_to_prompt_pct(value: float) -> float:
    """Config/engine fractions (0.02) → setup prompt percent (2.0)."""
    return value * 100.0


def _prompt_pct_to_fraction(value: float) -> float:
    """Setup answer as percent (2.0) → stored fraction (0.02). Accepts 0.02 too."""
    if value < 0.1:
        return value
    return value / 100.0


def _format_prompt_pct(value: float) -> str:
    return f"{value:g}"


def validate_strategy_name(name: Optional[str]) -> Optional[str]:
    """Validate strategy registry name; ``None`` means auto backtest selection."""
    if name is None or name == STRATEGY_AUTO:
        return None
    if name not in STRATEGY_REGISTRY:
        known = ", ".join(sorted(STRATEGY_REGISTRY))
        raise BacktestValidationError(
            f"Unknown strategy {name!r}. Registered strategies: {known}"
        )
    return name


def validate_ticks(value: Optional[int]) -> Optional[int]:
    if value is None:
        return None
    if value < 1:
        raise BacktestValidationError(
            f"Tick count must be a positive integer, got {value}"
        )
    return value


def _prompt_ticker(default: str = DEFAULT_TICKER) -> str:
    raw = questionary.text(
        "Crypto pair (e.g. BTC/USDT, ETH/USDC):",
        default=default,
    ).ask()
    if raw is None:
        raise BacktestValidationError("Paper trading cancelled.")
    return validate_ticker(raw)


def _prompt_strategy() -> Optional[str]:
    choices = [
        questionary.Choice(
            "Auto — run backtest to pick winner",
            value=STRATEGY_AUTO,
        ),
        questionary.Choice(
            f"Fixed — {DEFAULT_STRATEGY}",
            value=DEFAULT_STRATEGY,
        ),
    ]
    for name in sorted(STRATEGY_REGISTRY):
        if name == DEFAULT_STRATEGY:
            continue
        choices.append(questionary.Choice(name, value=name))

    choice = questionary.select(
        "Strategy:",
        choices=choices,
        use_indicator=True,
    ).ask()
    if choice is None:
        raise BacktestValidationError("Paper trading cancelled.")
    return validate_strategy_name(choice)


def _saved_session_equity(ticker: str, config: dict) -> Optional[float]:
    saved = load_paper_session(ticker, config)
    if not saved:
        return None
    return float(saved.get("equity", saved.get("cash", 0.0)))


def _prompt_resume_or_fresh(
    *,
    ticker: str,
    saved_equity: float,
) -> bool:
    """Return True to resume the saved session, False to start fresh."""
    saved_label = f"${saved_equity:,.2f}"
    choice = questionary.select(
        f"Saved session for {ticker} ({saved_label} equity). Resume or start fresh?",
        choices=[
            questionary.Choice(
                f"Resume saved session ({saved_label})",
                value=True,
            ),
            questionary.Choice(
                "Start fresh",
                value=False,
            ),
        ],
        use_indicator=True,
    ).ask()
    if choice is None:
        raise BacktestValidationError("Paper trading cancelled.")
    return bool(choice)


def _resolve_equity_and_session(
    *,
    ticker: str,
    config: dict,
    equity: Optional[float] = None,
    fresh_start: bool = False,
    interactive: bool = True,
) -> tuple[float, bool, bool]:
    """Return ``(initial_equity, resume_saved_session, fresh_start)``."""
    default_equity = float(config.get("paper_initial_equity", DEFAULT_EQUITY))
    resume_saved = False
    start_fresh = fresh_start
    saved_equity = _saved_session_equity(ticker, config)

    if saved_equity is not None and not fresh_start:
        if interactive:
            resume_saved = _prompt_resume_or_fresh(
                ticker=ticker,
                saved_equity=saved_equity,
            )
            start_fresh = not resume_saved
        else:
            resume_saved = True

    if resume_saved:
        return saved_equity, True, False

    if start_fresh and saved_equity is not None:
        delete_paper_session(ticker, config)

    if equity is not None:
        resolved = validate_positive_float(equity, name="Equity", minimum=1.0)
    elif interactive:
        resolved = _prompt_equity(default_equity)
    else:
        resolved = default_equity

    return resolved, False, start_fresh


def _prompt_equity(default: float = DEFAULT_EQUITY) -> float:
    raw = questionary.text(
        "Starting portfolio equity (USD):",
        default=str(int(default) if default == int(default) else default),
    ).ask()
    if raw is None:
        raise BacktestValidationError("Paper trading cancelled.")
    try:
        value = float(raw)
    except ValueError as exc:
        raise BacktestValidationError(
            f"Equity must be a number, got {raw!r}"
        ) from exc
    return validate_positive_float(value, name="Equity", minimum=1.0)


def _prompt_ticks() -> Optional[int]:
    raw = questionary.text(
        "Number of price ticks (empty = run until Ctrl+C):",
        default="",
    ).ask()
    if raw is None:
        raise BacktestValidationError("Paper trading cancelled.")
    text = raw.strip()
    if not text:
        return None
    if not text.isdigit():
        raise BacktestValidationError(
            f"Tick count must be a positive integer, got {raw!r}"
        )
    return validate_ticks(int(text))


def _prompt_tick_interval(config: dict) -> float:
    default = _default_tick_interval(config)
    default_str = str(int(default) if default == int(default) else default)
    raw = questionary.text(
        "Price check interval (seconds between ticks):",
        default=default_str,
    ).ask()
    if raw is None:
        raise BacktestValidationError("Paper trading cancelled.")
    try:
        value = float(raw)
    except ValueError as exc:
        raise BacktestValidationError(
            f"Tick interval must be a number, got {raw!r}"
        ) from exc
    return validate_positive_float(value, name="Tick interval", minimum=1.0)


def _prompt_risk_exit_settings(config: dict) -> tuple[float, Optional[float]]:
    stop_default_pct = _stored_fraction_to_prompt_pct(_default_stop_loss_pct(config))
    take_default = _default_take_profit_pct(config)
    take_default_pct = (
        None if take_default is None else _stored_fraction_to_prompt_pct(take_default)
    )
    take_default_str = "" if take_default_pct is None else _format_prompt_pct(take_default_pct)

    stop_raw = questionary.text(
        f"Stop-loss % (e.g. 2.0):",
        default=_format_prompt_pct(stop_default_pct),
    ).ask()
    if stop_raw is None:
        raise BacktestValidationError("Paper trading cancelled.")

    take_label = (
        f"Take-profit % (default {take_default_str or '2× stop-loss'}; empty = 2× stop-loss):"
        if take_default_pct is not None
        else "Take-profit % (empty = 2× stop-loss, e.g. 4.0):"
    )
    take_raw = questionary.text(
        take_label,
        default=take_default_str,
    ).ask()
    if take_raw is None:
        raise BacktestValidationError("Paper trading cancelled.")

    try:
        stop_loss_pct = _prompt_pct_to_fraction(float(stop_raw))
    except ValueError as exc:
        raise BacktestValidationError(
            f"Stop-loss must be a number, got {stop_raw!r}"
        ) from exc
    validate_positive_float(stop_loss_pct, name="Stop-loss", minimum=0.0001)

    take_profit_pct: Optional[float] = None
    if take_raw.strip():
        try:
            take_profit_pct = _prompt_pct_to_fraction(float(take_raw))
        except ValueError as exc:
            raise BacktestValidationError(
                f"Take-profit must be a number, got {take_raw!r}"
            ) from exc
        validate_positive_float(take_profit_pct, name="Take-profit", minimum=0.0001)

    return stop_loss_pct, take_profit_pct


def _default_leverage(config: dict) -> float:
    return float(config.get("paper_leverage", 1.0))


def _prompt_leverage(config: dict) -> float:
    default = _default_leverage(config)
    default_str = str(int(default) if default == int(default) else default)
    raw = questionary.text(
        "Leverage multiplier (1 = none, 2 or 3 = margin; PnL scales with leverage):",
        default=default_str,
    ).ask()
    if raw is None:
        raise BacktestValidationError("Paper trading cancelled.")
    try:
        value = float(raw)
    except ValueError as exc:
        raise BacktestValidationError(
            f"Leverage must be a number, got {raw!r}"
        ) from exc
    return validate_positive_float(value, name="Leverage", minimum=1.0)


def _prompt_adaptive_settings(config: dict) -> tuple[bool, float, float]:
    adaptive = questionary.confirm(
        "Enable adaptive strategy re-optimization on sustained drawdown?",
        default=bool(config.get("paper_adaptive_enabled", True)),
    ).ask()
    if adaptive is None:
        raise BacktestValidationError("Paper trading cancelled.")

    window_default = str(_default_drawdown_window(config))
    threshold_default = str(_default_drawdown_pct(config))
    if not adaptive:
        return False, float(window_default), float(threshold_default)

    window_raw = questionary.text(
        "Drawdown review window (minutes):",
        default=window_default,
    ).ask()
    if window_raw is None:
        raise BacktestValidationError("Paper trading cancelled.")
    threshold_raw = questionary.text(
        "Max allowed drawdown (loss) % (e.g. 5.0):",
        default=threshold_default,
    ).ask()
    if threshold_raw is None:
        raise BacktestValidationError("Paper trading cancelled.")

    try:
        window = float(window_raw)
        threshold = float(threshold_raw)
    except ValueError as exc:
        raise BacktestValidationError(
            "Drawdown settings must be numbers."
        ) from exc
    validate_positive_float(window, name="Drawdown window", minimum=0.1)
    validate_positive_float(threshold, name="Max drawdown", minimum=0.1)
    return True, window, threshold


def _prompt_spike_settings(
    config: dict,
    *,
    adaptive_enabled: bool,
    stop_loss_pct: float,
) -> SpikeSettings:
    defaults = _default_spike_settings(config)
    if not adaptive_enabled:
        return SpikeSettings(enabled=False)

    enabled = questionary.confirm(
        "Enable fast-movement reviews (re-check when equity drops quickly)?",
        default=defaults.enabled,
    ).ask()
    if enabled is None:
        raise BacktestValidationError("Paper trading cancelled.")
    if not enabled:
        return SpikeSettings(enabled=False)

    intelligent = questionary.confirm(
        "Enable intelligent spike tuning (adapt thresholds to stop-loss & chop)?",
        default=defaults.intelligent_tuning,
    ).ask()
    if intelligent is None:
        raise BacktestValidationError("Paper trading cancelled.")

    loss_1m = defaults.loss_1m_pct
    loss_5m = defaults.loss_5m_pct
    loss_10m = defaults.loss_10m_pct
    if not intelligent:
        console.print(
            "[dim]Fast-move loss triggers (% of equity drop over the window).[/dim]"
        )
        for label, attr, current in (
            ("1-minute loss trigger % (e.g. 1.5)", "loss_1m", loss_1m),
            ("5-minute loss trigger % (e.g. 2.0)", "loss_5m", loss_5m),
            ("10-minute loss trigger % (e.g. 2.5)", "loss_10m", loss_10m),
        ):
            raw = questionary.text(f"{label}:", default=str(current)).ask()
            if raw is None:
                raise BacktestValidationError("Paper trading cancelled.")
            try:
                value = float(raw)
            except ValueError as exc:
                raise BacktestValidationError(
                    f"{label} must be a number, got {raw!r}"
                ) from exc
            validate_positive_float(value, name=label, minimum=0.1)
            if attr == "loss_1m":
                loss_1m = value
            elif attr == "loss_5m":
                loss_5m = value
            else:
                loss_10m = value
    else:
        console.print(
            "[dim]Intelligent tuning scales fast-move thresholds from your "
            f"{stop_loss_pct * 100:.1f}% stop-loss and recent chop.[/dim]"
        )

    switch_default_pct = _stored_fraction_to_prompt_pct(defaults.switch_min_net_profit)
    switch_raw = questionary.text(
        "Min backtest edge to switch on fast-move review % (e.g. 0.5):",
        default=_format_prompt_pct(switch_default_pct),
    ).ask()
    if switch_raw is None:
        raise BacktestValidationError("Paper trading cancelled.")
    try:
        switch_min = _prompt_pct_to_fraction(float(switch_raw))
    except ValueError as exc:
        raise BacktestValidationError(
            f"Switch edge must be a number, got {switch_raw!r}"
        ) from exc
    validate_positive_float(switch_min, name="Switch edge", minimum=0.0001)

    cooldown_default = (
        ""
        if defaults.min_cooldown_minutes is None
        else str(defaults.min_cooldown_minutes)
    )
    cooldown_raw = questionary.text(
        "Fast-move review cooldown minutes (empty = lookback default):",
        default=cooldown_default,
    ).ask()
    if cooldown_raw is None:
        raise BacktestValidationError("Paper trading cancelled.")
    cooldown = _parse_optional_positive_float(
        cooldown_raw, name="Fast-move cooldown"
    )

    return SpikeSettings(
        enabled=True,
        intelligent_tuning=bool(intelligent),
        loss_1m_pct=loss_1m,
        loss_5m_pct=loss_5m,
        loss_10m_pct=loss_10m,
        switch_min_net_profit=switch_min,
        min_cooldown_minutes=cooldown,
    )


def _prompt_paper_monitoring_settings(
    config: dict,
    *,
    stop_loss_pct: float,
) -> tuple[bool, float, float, SpikeSettings]:
    """Adaptive drawdown + fast-move review prompts."""
    adaptive, window, threshold = _prompt_adaptive_settings(config)
    spike = _prompt_spike_settings(
        config,
        adaptive_enabled=adaptive,
        stop_loss_pct=stop_loss_pct,
    )
    return adaptive, window, threshold, spike


def prompt_paper_params(
    config: dict | None = None,
    *,
    ticker: Optional[str] = None,
    strategy_name: Optional[str] = None,
    equity: Optional[float] = None,
    ticks: Optional[int] = None,
    live_mode: bool = False,
    fresh_start: bool = False,
) -> PaperRunParams:
    """Full interactive questionnaire for standalone paper trading runs."""
    if not _is_interactive_tty():
        raise BacktestValidationError(
            "Interactive paper trading requires a TTY. "
            "Pass --ticker and --no-interactive for scripted runs."
        )

    cfg = config or DEFAULT_CONFIG.copy()

    console.print()
    console.print("[bold cyan]Paper Trading Simulation[/bold cyan]")
    console.print(
        "[dim]Live price feed, portfolio tracking, optional adaptive re-optimization[/dim]\n"
    )

    resolved_ticker = validate_ticker(ticker) if ticker else _prompt_ticker()
    resolved_strategy = (
        validate_strategy_name(strategy_name)
        if strategy_name is not None
        else _prompt_strategy()
    )
    resolved_equity, resume_saved, start_fresh = _resolve_equity_and_session(
        ticker=resolved_ticker,
        config=cfg,
        equity=equity,
        fresh_start=fresh_start,
        interactive=True,
    )
    if resume_saved:
        console.print(
            f"[dim]Resuming saved session at {resolved_equity:,.2f} USD.[/dim]"
        )

    resolved_ticks = validate_ticks(ticks) if ticks is not None else _prompt_ticks()
    tick_interval = _prompt_tick_interval(cfg)
    stop_loss_pct, take_profit_pct = _prompt_risk_exit_settings(cfg)
    leverage = _prompt_leverage(cfg)

    if live_mode:
        resolved_live = True
    else:
        live_answer = questionary.confirm(
            "Enable live-mode price fallback (ccxt Binance) when vendors fail?",
            default=True,
        ).ask()
        if live_answer is None:
            raise BacktestValidationError("Paper trading cancelled.")
        resolved_live = bool(live_answer)

    adaptive, window, threshold, spike = _prompt_paper_monitoring_settings(
        cfg,
        stop_loss_pct=stop_loss_pct,
    )

    return PaperRunParams(
        ticker=resolved_ticker,
        strategy_name=resolved_strategy,
        lookback="24h",
        initial_equity=resolved_equity,
        ticks=resolved_ticks,
        tick_interval_seconds=tick_interval,
        live_mode=resolved_live,
        stop_loss_pct=stop_loss_pct,
        take_profit_pct=take_profit_pct,
        leverage=leverage,
        adaptive_enabled=adaptive,
        spike_review_enabled=spike.enabled,
        spike_intelligent_tuning=spike.intelligent_tuning,
        spike_1m_loss_pct=spike.loss_1m_pct,
        spike_5m_loss_pct=spike.loss_5m_pct,
        spike_10m_loss_pct=spike.loss_10m_pct,
        spike_switch_min_net_profit=spike.switch_min_net_profit,
        spike_min_cooldown_minutes=spike.min_cooldown_minutes,
        drawdown_window_minutes=window,
        max_drawdown_pct=threshold,
        resume_saved_session=resume_saved,
        fresh_start=start_fresh,
    )


def resolve_paper_params(
    *,
    ticker: Optional[str],
    strategy_name: Optional[str],
    equity: Optional[float],
    ticks: Optional[int],
    live_mode: bool,
    adaptive_enabled: Optional[bool] = None,
    spike_review_enabled: Optional[bool] = None,
    spike_intelligent_tuning: Optional[bool] = None,
    interactive: bool,
    fresh_start: bool = False,
    config: dict | None = None,
) -> PaperRunParams:
    """Resolve CLI flags into validated ``PaperRunParams``."""
    cfg = (config or DEFAULT_CONFIG).copy()
    missing = ticker is None
    if interactive and missing and not _is_interactive_tty():
        raise BacktestValidationError(
            "Interactive paper trading requires a TTY. "
            "Pass --ticker and --no-interactive for scripted runs."
        )

    needs_prompt = interactive and _is_interactive_tty() and missing
    if needs_prompt:
        params = prompt_paper_params(
            cfg,
            ticker=ticker,
            strategy_name=strategy_name,
            equity=equity,
            ticks=ticks,
            live_mode=live_mode,
            fresh_start=fresh_start,
        )
        if strategy_name is not None:
            params = replace(
                params,
                strategy_name=validate_strategy_name(strategy_name),
            )
        if equity is not None:
            params = replace(
                params,
                initial_equity=validate_positive_float(
                    equity, name="Equity", minimum=1.0
                ),
            )
        if ticks is not None:
            params = replace(params, ticks=validate_ticks(ticks))
        if live_mode:
            params = replace(params, live_mode=True)
        if adaptive_enabled is not None:
            params = replace(params, adaptive_enabled=adaptive_enabled)
        if spike_review_enabled is not None:
            params = replace(params, spike_review_enabled=spike_review_enabled)
        if spike_intelligent_tuning is not None:
            params = replace(params, spike_intelligent_tuning=spike_intelligent_tuning)
        return params

    resolved_ticker = validate_ticker(ticker or DEFAULT_TICKER)
    resolved_equity, resume_saved, start_fresh = _resolve_equity_and_session(
        ticker=resolved_ticker,
        config=cfg,
        equity=equity,
        fresh_start=fresh_start,
        interactive=False,
    )
    resolved_adaptive = (
        adaptive_enabled
        if adaptive_enabled is not None
        else bool(cfg.get("paper_adaptive_enabled", True))
    )
    resolved_spike = (
        spike_review_enabled
        if spike_review_enabled is not None
        else bool(cfg.get("paper_spike_review_enabled", True))
    )
    if not resolved_adaptive:
        resolved_spike = False
        resolved_spike_tuning = False
    else:
        resolved_spike_tuning = (
            spike_intelligent_tuning
            if spike_intelligent_tuning is not None
            else bool(cfg.get("paper_spike_intelligent_tuning_enabled", True))
        )
        if not resolved_spike:
            resolved_spike_tuning = False
    spike_defaults = _default_spike_settings(cfg)
    return PaperRunParams(
        ticker=resolved_ticker,
        strategy_name=validate_strategy_name(strategy_name),
        lookback="24h",
        initial_equity=resolved_equity,
        ticks=validate_ticks(ticks),
        tick_interval_seconds=_default_tick_interval(cfg),
        live_mode=live_mode,
        stop_loss_pct=_default_stop_loss_pct(cfg),
        take_profit_pct=_default_take_profit_pct(cfg),
        leverage=_default_leverage(cfg),
        adaptive_enabled=resolved_adaptive,
        spike_review_enabled=resolved_spike,
        spike_intelligent_tuning=resolved_spike_tuning,
        spike_1m_loss_pct=spike_defaults.loss_1m_pct,
        spike_5m_loss_pct=spike_defaults.loss_5m_pct,
        spike_10m_loss_pct=spike_defaults.loss_10m_pct,
        spike_switch_min_net_profit=spike_defaults.switch_min_net_profit,
        spike_min_cooldown_minutes=spike_defaults.min_cooldown_minutes,
        drawdown_window_minutes=_default_drawdown_window(cfg),
        max_drawdown_pct=_default_drawdown_pct(cfg),
        resume_saved_session=resume_saved,
        fresh_start=start_fresh,
    )


def apply_paper_params_to_config(params: PaperRunParams, config: dict | None = None) -> dict:
    cfg = (config or DEFAULT_CONFIG).copy()
    cfg["paper_trade_enabled"] = True
    cfg["paper_initial_equity"] = params.initial_equity
    cfg["paper_adaptive_enabled"] = params.adaptive_enabled
    cfg["paper_spike_review_enabled"] = (
        params.spike_review_enabled and params.adaptive_enabled
    )
    cfg["paper_spike_intelligent_tuning_enabled"] = (
        params.spike_intelligent_tuning and params.spike_review_enabled and params.adaptive_enabled
    )
    cfg["paper_spike_1m_loss_pct"] = params.spike_1m_loss_pct
    cfg["paper_spike_5m_loss_pct"] = params.spike_5m_loss_pct
    cfg["paper_spike_10m_loss_pct"] = params.spike_10m_loss_pct
    cfg["paper_spike_switch_min_net_profit"] = params.spike_switch_min_net_profit
    cfg["paper_spike_min_cooldown_minutes"] = params.spike_min_cooldown_minutes
    cfg["paper_tick_interval_seconds"] = params.tick_interval_seconds
    cfg["drawdown_time_window_minutes"] = params.drawdown_window_minutes
    cfg["paper_loss_review_minutes"] = params.drawdown_window_minutes
    cfg["max_allowed_drawdown_pct"] = params.max_drawdown_pct
    cfg["paper_loss_threshold_pct"] = params.max_drawdown_pct
    cfg["paper_stop_loss_pct"] = params.stop_loss_pct
    cfg["paper_take_profit_pct"] = params.take_profit_pct
    cfg["paper_leverage"] = params.leverage
    if params.live_mode:
        cfg["live_mode"] = True
    cfg["paper_fresh_start"] = params.fresh_start
    return cfg
