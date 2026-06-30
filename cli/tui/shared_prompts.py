"""Shared questionary prompts for paper and visual backtest setup."""

from __future__ import annotations

from typing import Optional

import questionary

from tradingagents.backtest.strategies import STRATEGY_REGISTRY
from tradingagents.backtest.validation import (
    BacktestValidationError,
    validate_positive_float,
    validate_ticker,
)
from tradingagents.default_config import DEFAULT_CONFIG

DEFAULT_TICKER = "BTC/USDT"
DEFAULT_EQUITY = float(DEFAULT_CONFIG.get("paper_initial_equity", 10_000.0))


def _prompt_pct_to_fraction(value: float) -> float:
    if value < 0.1:
        return value
    return value / 100.0


def _stored_fraction_to_prompt_pct(value: float) -> float:
    return value * 100.0


def prompt_ticker(default: str = DEFAULT_TICKER) -> str:
    raw = questionary.text(
        "Crypto pair (e.g. BTC/USDT, ETH/USDC):",
        default=default,
    ).ask()
    if raw is None:
        raise BacktestValidationError("Cancelled.")
    return validate_ticker(raw)


def prompt_stop_loss_pct(default_fraction: float = 0.02) -> float:
    default_pct = _stored_fraction_to_prompt_pct(default_fraction)
    raw = questionary.text(
        "Stop loss (% of price from entry):",
        default=f"{default_pct:g}",
    ).ask()
    if raw is None:
        raise BacktestValidationError("Cancelled.")
    try:
        value = float(raw.strip())
    except ValueError as exc:
        raise BacktestValidationError(f"Stop loss must be a number, got {raw!r}") from exc
    fraction = _prompt_pct_to_fraction(value)
    validate_positive_float(fraction, name="Stop loss", minimum=0.0001)
    return fraction


def prompt_take_profit_pct(
    default_fraction: Optional[float],
    *,
    stop_loss_fraction: float,
) -> Optional[float]:
    default_pct = (
        _stored_fraction_to_prompt_pct(default_fraction)
        if default_fraction is not None
        else _stored_fraction_to_prompt_pct(stop_loss_fraction * 2)
    )
    raw = questionary.text(
        "Take profit (% of price from entry, empty = 2× stop loss):",
        default=f"{default_pct:g}",
    ).ask()
    if raw is None:
        raise BacktestValidationError("Cancelled.")
    text = raw.strip()
    if not text:
        return None
    try:
        value = float(text)
    except ValueError as exc:
        raise BacktestValidationError(f"Take profit must be a number, got {raw!r}") from exc
    fraction = _prompt_pct_to_fraction(value)
    validate_positive_float(fraction, name="Take profit", minimum=0.0001)
    return fraction


def prompt_transaction_cost_pct(default: float = 0.001) -> float:
    raw = questionary.text(
        "Transaction cost per side (%):",
        default=f"{default * 100:g}",
    ).ask()
    if raw is None:
        raise BacktestValidationError("Cancelled.")
    try:
        value = float(raw.strip())
    except ValueError as exc:
        raise BacktestValidationError(f"Fee must be a number, got {raw!r}") from exc
    fraction = _prompt_pct_to_fraction(value)
    validate_positive_float(fraction, name="Transaction cost", minimum=0.0)
    return fraction


def prompt_initial_equity(default: float = DEFAULT_EQUITY) -> float:
    raw = questionary.text(
        "Initial equity (USD):",
        default=f"{default:,.0f}",
    ).ask()
    if raw is None:
        raise BacktestValidationError("Cancelled.")
    try:
        value = float(raw.replace(",", "").strip())
    except ValueError as exc:
        raise BacktestValidationError(f"Equity must be a number, got {raw!r}") from exc
    validate_positive_float(value, name="Initial equity", minimum=1.0)
    return value


def prompt_leverage(default: float = 1.0) -> float:
    raw = questionary.text(
        "Leverage (1 = spot, 2–3 = margin simulation):",
        default=f"{default:g}",
    ).ask()
    if raw is None:
        raise BacktestValidationError("Cancelled.")
    try:
        value = float(raw.strip())
    except ValueError as exc:
        raise BacktestValidationError(f"Leverage must be a number, got {raw!r}") from exc
    validate_positive_float(value, name="Leverage", minimum=1.0)
    return value


def prompt_strategy_single(default: str = "ema_crossover") -> str:
    choices = [
        questionary.Choice(name, value=name)
        for name in sorted(STRATEGY_REGISTRY)
    ]
    choice = questionary.select(
        "Strategy to test:",
        choices=choices,
        default=default if default in STRATEGY_REGISTRY else None,
        use_indicator=True,
    ).ask()
    if choice is None:
        raise BacktestValidationError("Cancelled.")
    return choice


def prompt_strategy_mode() -> str:
    choice = questionary.select(
        "Strategies to run:",
        choices=[
            questionary.Choice("Single strategy", value="single"),
            questionary.Choice("All registered strategies", value="all"),
        ],
        use_indicator=True,
    ).ask()
    if choice is None:
        raise BacktestValidationError("Cancelled.")
    return choice
