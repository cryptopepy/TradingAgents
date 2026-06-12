"""Interactive prompts and parameter resolution for ``tradingagents backtest``."""

from __future__ import annotations

import datetime as dt
import sys
from dataclasses import dataclass, replace
from typing import Optional, Sequence

import questionary
from rich.console import Console

from tradingagents.backtest import LookbackWindow
from tradingagents.backtest.validation import (
    BacktestValidationError,
    validate_end_date,
    validate_positive_float,
    validate_ticker,
)
from tradingagents.default_config import DEFAULT_CONFIG

console = Console()

DEFAULT_TICKER = "BTC/USDT"
DEFAULT_EQUITY = 10_000.0
DEFAULT_STOP_LOSS = 0.02
DEFAULT_FEE = 0.001


@dataclass(frozen=True)
class BacktestRunParams:
    ticker: str
    end_date: str
    lookbacks: tuple[LookbackWindow, ...]
    stop_loss_pct: float
    transaction_cost_pct: float
    initial_equity: float
    live_mode: bool


def _is_interactive_tty() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def _prompt_ticker(default: str = DEFAULT_TICKER) -> str:
    raw = questionary.text(
        "Crypto pair (e.g. BTC/USDT, ETH/USDC):",
        default=default,
    ).ask()
    if raw is None:
        raise BacktestValidationError("Backtest cancelled.")
    return validate_ticker(raw)


def _prompt_end_date(default: str | None = None) -> str:
    default = default or dt.date.today().strftime("%Y-%m-%d")
    raw = questionary.text(
        "Backtest end date (YYYY-MM-DD):",
        default=default,
    ).ask()
    if raw is None:
        raise BacktestValidationError("Backtest cancelled.")
    return validate_end_date(raw)


def _prompt_lookbacks() -> list[LookbackWindow]:
    choice = questionary.select(
        "Historical optimization horizons:",
        choices=[
            questionary.Choice("All horizons (8h, 24h, 7d)", value="all"),
            questionary.Choice("8 hours", value="8h"),
            questionary.Choice("24 hours", value="24h"),
            questionary.Choice("7 days", value="7d"),
        ],
        use_indicator=True,
    ).ask()
    if choice is None:
        raise BacktestValidationError("Backtest cancelled.")
    if choice == "all":
        return list(LookbackWindow)
    return [LookbackWindow(choice)]


def _prompt_float(
    message: str,
    default: str,
    *,
    name: str,
    minimum: float = 0.0,
) -> float:
    raw = questionary.text(message, default=default).ask()
    if raw is None:
        raise BacktestValidationError("Backtest cancelled.")
    try:
        value = float(raw)
    except ValueError as exc:
        raise BacktestValidationError(f"{name} must be a number, got {raw!r}") from exc
    return validate_positive_float(value, name=name, minimum=minimum)


def prompt_backtest_params(
    *,
    ticker: Optional[str] = None,
    end_date: Optional[str] = None,
) -> BacktestRunParams:
    """Full interactive questionnaire for standalone backtest runs."""
    if not _is_interactive_tty():
        raise BacktestValidationError(
            "Interactive backtest requires a TTY. "
            "Pass --ticker, --date, and --no-interactive for scripted runs."
        )

    console.print()
    console.print("[bold cyan]Historical Strategy Optimization[/bold cyan]")
    console.print("[dim]10 quantitative strategies × selected horizons (no LLM tokens)[/dim]\n")

    resolved_ticker = validate_ticker(ticker) if ticker else _prompt_ticker()
    resolved_date = validate_end_date(end_date) if end_date else _prompt_end_date()
    lookbacks = _prompt_lookbacks()
    stop_loss = _prompt_float(
        "Stop-loss fraction (e.g. 0.02 = 2%):",
        str(DEFAULT_STOP_LOSS),
        name="Stop-loss",
    )
    fee = _prompt_float(
        "Transaction cost per side (e.g. 0.001 = 0.1%):",
        str(DEFAULT_FEE),
        name="Transaction cost",
    )
    equity = _prompt_float(
        "Starting equity for paper deploy (USD):",
        str(DEFAULT_EQUITY),
        name="Equity",
        minimum=1.0,
    )
    live = questionary.confirm(
        "Enable live-mode price fallback (ccxt Binance) after optimization?",
        default=False,
    ).ask()
    if live is None:
        raise BacktestValidationError("Backtest cancelled.")

    return BacktestRunParams(
        ticker=resolved_ticker,
        end_date=resolved_date,
        lookbacks=tuple(lookbacks),
        stop_loss_pct=stop_loss,
        transaction_cost_pct=fee,
        initial_equity=equity,
        live_mode=bool(live),
    )


def resolve_backtest_params(
    *,
    ticker: Optional[str],
    end_date: Optional[str],
    interactive: bool,
    lookbacks: Optional[Sequence[LookbackWindow]] = None,
    stop_loss_pct: Optional[float] = None,
    transaction_cost_pct: Optional[float] = None,
    equity: Optional[float] = None,
    live_mode: bool = False,
) -> BacktestRunParams:
    """Resolve CLI flags into a validated ``BacktestRunParams``."""
    missing = ticker is None or end_date is None
    if interactive and missing and not _is_interactive_tty():
        raise BacktestValidationError(
            "Interactive backtest requires a TTY. "
            "Pass --ticker, --date, and --no-interactive for scripted runs."
        )
    needs_prompt = interactive and _is_interactive_tty() and missing
    if needs_prompt:
        params = prompt_backtest_params(ticker=ticker, end_date=end_date)
        if lookbacks:
            params = replace(params, lookbacks=tuple(lookbacks))
        if stop_loss_pct is not None:
            params = replace(params, stop_loss_pct=stop_loss_pct)
        if transaction_cost_pct is not None:
            params = replace(params, transaction_cost_pct=transaction_cost_pct)
        if equity is not None:
            params = replace(params, initial_equity=equity)
        if live_mode:
            params = replace(params, live_mode=True)
        return params

    resolved_ticker = validate_ticker(ticker or DEFAULT_TICKER)
    resolved_date = validate_end_date(
        end_date or dt.date.today().strftime("%Y-%m-%d")
    )
    windows = tuple(lookbacks or LookbackWindow)
    return BacktestRunParams(
        ticker=resolved_ticker,
        end_date=resolved_date,
        lookbacks=windows,
        stop_loss_pct=stop_loss_pct if stop_loss_pct is not None else DEFAULT_STOP_LOSS,
        transaction_cost_pct=(
            transaction_cost_pct if transaction_cost_pct is not None else DEFAULT_FEE
        ),
        initial_equity=equity if equity is not None else DEFAULT_EQUITY,
        live_mode=live_mode,
    )


def apply_params_to_config(params: BacktestRunParams, config: dict | None = None) -> dict:
    cfg = (config or DEFAULT_CONFIG).copy()
    cfg["paper_initial_equity"] = params.initial_equity
    if params.live_mode:
        cfg["live_mode"] = True
    return cfg
