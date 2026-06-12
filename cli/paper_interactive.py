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

console = Console()

DEFAULT_TICKER = "BTC/USDT"
DEFAULT_EQUITY = float(DEFAULT_CONFIG.get("paper_initial_equity", 100_000.0))
DEFAULT_STRATEGY = "ema_crossover"
STRATEGY_AUTO = "__auto_backtest__"


@dataclass(frozen=True)
class PaperRunParams:
    ticker: str
    strategy_name: Optional[str]
    lookback: str
    initial_equity: float
    ticks: Optional[int]
    live_mode: bool
    adaptive_enabled: bool
    drawdown_window_minutes: float
    max_drawdown_pct: float


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
        "Max allowed drawdown % (e.g. 5.0):",
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


def prompt_paper_params(
    config: dict | None = None,
    *,
    ticker: Optional[str] = None,
    strategy_name: Optional[str] = None,
    equity: Optional[float] = None,
    ticks: Optional[int] = None,
    live_mode: bool = False,
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
    resolved_equity = (
        validate_positive_float(equity, name="Equity", minimum=1.0)
        if equity is not None
        else _prompt_equity(float(cfg.get("paper_initial_equity", DEFAULT_EQUITY)))
    )
    resolved_ticks = validate_ticks(ticks) if ticks is not None else _prompt_ticks()

    if live_mode:
        resolved_live = True
    else:
        live_answer = questionary.confirm(
            "Enable live-mode price fallback (ccxt Binance) when vendors fail?",
            default=False,
        ).ask()
        if live_answer is None:
            raise BacktestValidationError("Paper trading cancelled.")
        resolved_live = bool(live_answer)

    adaptive, window, threshold = _prompt_adaptive_settings(cfg)

    return PaperRunParams(
        ticker=resolved_ticker,
        strategy_name=resolved_strategy,
        lookback="24h",
        initial_equity=resolved_equity,
        ticks=resolved_ticks,
        live_mode=resolved_live,
        adaptive_enabled=adaptive,
        drawdown_window_minutes=window,
        max_drawdown_pct=threshold,
    )


def resolve_paper_params(
    *,
    ticker: Optional[str],
    strategy_name: Optional[str],
    equity: Optional[float],
    ticks: Optional[int],
    live_mode: bool,
    adaptive_enabled: Optional[bool],
    interactive: bool,
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
        return params

    resolved_ticker = validate_ticker(ticker or DEFAULT_TICKER)
    resolved_equity = (
        validate_positive_float(equity, name="Equity", minimum=1.0)
        if equity is not None
        else float(cfg.get("paper_initial_equity", DEFAULT_EQUITY))
    )
    resolved_adaptive = (
        adaptive_enabled
        if adaptive_enabled is not None
        else bool(cfg.get("paper_adaptive_enabled", True))
    )
    return PaperRunParams(
        ticker=resolved_ticker,
        strategy_name=validate_strategy_name(strategy_name),
        lookback="24h",
        initial_equity=resolved_equity,
        ticks=validate_ticks(ticks),
        live_mode=live_mode,
        adaptive_enabled=resolved_adaptive,
        drawdown_window_minutes=_default_drawdown_window(cfg),
        max_drawdown_pct=_default_drawdown_pct(cfg),
    )


def apply_paper_params_to_config(params: PaperRunParams, config: dict | None = None) -> dict:
    cfg = (config or DEFAULT_CONFIG).copy()
    cfg["paper_trade_enabled"] = True
    cfg["paper_initial_equity"] = params.initial_equity
    cfg["paper_adaptive_enabled"] = params.adaptive_enabled
    cfg["drawdown_time_window_minutes"] = params.drawdown_window_minutes
    cfg["paper_loss_review_minutes"] = params.drawdown_window_minutes
    cfg["max_allowed_drawdown_pct"] = params.max_drawdown_pct
    cfg["paper_loss_threshold_pct"] = params.max_drawdown_pct
    if params.live_mode:
        cfg["live_mode"] = True
    return cfg
