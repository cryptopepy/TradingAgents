"""Interactive setup for the visual backtest pane."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Optional

import questionary
from rich.console import Console

from cli.tui.shared_prompts import (
    prompt_initial_equity,
    prompt_leverage,
    prompt_stop_loss_pct,
    prompt_strategy_mode,
    prompt_strategy_single,
    prompt_take_profit_pct,
    prompt_ticker,
    prompt_transaction_cost_pct,
)
from tradingagents.backtest.historical_data import granularity_label_to_seconds
from tradingagents.backtest.range_validation import validate_backtest_range
from tradingagents.backtest.validation import (
    BacktestValidationError,
    validate_datetime_utc,
)
from tradingagents.dataflows.trading_fees import paper_transaction_cost_pct

console = Console()


@dataclass(frozen=True)
class VisualBacktestParams:
    ticker: str
    start_dt: dt.datetime
    end_dt: dt.datetime
    granularity_seconds: int
    granularity_label: str
    stop_loss_pct: float
    take_profit_pct: Optional[float]
    transaction_cost_pct: float
    initial_equity: float
    leverage: float
    strategy_mode: str  # "single" | "all"
    strategy_name: Optional[str]
    pause_between_strategies: bool


def _default_range() -> tuple[str, str]:
    end = dt.datetime.utcnow().replace(second=0, microsecond=0)
    start = end - dt.timedelta(days=3)
    return start.strftime("%Y-%m-%d %H:%M"), end.strftime("%Y-%m-%d %H:%M")


def _prompt_datetime(label: str, default: str) -> dt.datetime:
    raw = questionary.text(
        f"{label} (YYYY-MM-DD or YYYY-MM-DD HH:MM, UTC):",
        default=default,
    ).ask()
    if raw is None:
        raise BacktestValidationError("Visual backtest cancelled.")
    return validate_datetime_utc(raw, name=label)


def _prompt_granularity() -> str:
    choice = questionary.select(
        "Bar size:",
        choices=["5m", "15m", "1h", "1d"],
        use_indicator=True,
    ).ask()
    if choice is None:
        raise BacktestValidationError("Visual backtest cancelled.")
    return choice


def prompt_visual_backtest_params(config: dict) -> VisualBacktestParams:
    """Collect visual backtest parameters with validation retry."""
    defaults_start, defaults_end = _default_range()
    ticker = prompt_ticker(config.get("last_ticker", "BTC/USDT"))
    sl_default = float(config.get("paper_stop_loss_pct", 0.02))
    tp_default = config.get("paper_take_profit_pct")
    tp_default_f = float(tp_default) if tp_default is not None else None
    fee_default = paper_transaction_cost_pct(ticker, config)
    equity_default = float(config.get("paper_initial_equity", 10_000.0))
    leverage_default = float(config.get("paper_leverage", 1.0))

    while True:
        try:
            start_default, end_default = defaults_start, defaults_end
            start_dt = _prompt_datetime("Start datetime", start_default)
            end_dt = _prompt_datetime("End datetime", end_default)
            gran_label = _prompt_granularity()
            gran_sec = granularity_label_to_seconds(gran_label)
            end_dt = validate_backtest_range(start_dt, end_dt, gran_sec)

            stop_loss_pct = prompt_stop_loss_pct(sl_default)
            take_profit_pct = prompt_take_profit_pct(
                tp_default_f,
                stop_loss_fraction=stop_loss_pct,
            )
            transaction_cost_pct = prompt_transaction_cost_pct(fee_default)
            initial_equity = prompt_initial_equity(equity_default)
            leverage = prompt_leverage(leverage_default)
            strategy_mode = prompt_strategy_mode()
            strategy_name: Optional[str] = None
            pause_between = False
            if strategy_mode == "single":
                strategy_name = prompt_strategy_single()
            else:
                pause_between = bool(
                    questionary.confirm(
                        "Pause between strategies for review?",
                        default=True,
                    ).ask()
                )
                if pause_between is None:
                    raise BacktestValidationError("Visual backtest cancelled.")

            return VisualBacktestParams(
                ticker=ticker,
                start_dt=start_dt,
                end_dt=end_dt,
                granularity_seconds=gran_sec,
                granularity_label=gran_label,
                stop_loss_pct=stop_loss_pct,
                take_profit_pct=take_profit_pct,
                transaction_cost_pct=transaction_cost_pct,
                initial_equity=initial_equity,
                leverage=leverage,
                strategy_mode=strategy_mode,
                strategy_name=strategy_name,
                pause_between_strategies=pause_between,
            )
        except BacktestValidationError as exc:
            console.print(f"[red]{exc}[/red]")
            console.print("[yellow]Adjust the range or bar size and try again.[/yellow]")


def format_params_summary(params: VisualBacktestParams) -> str:
    strategies = (
        params.strategy_name
        if params.strategy_mode == "single"
        else "all strategies"
    )
    tp = (
        f"{params.take_profit_pct * 100:.2f}%"
        if params.take_profit_pct is not None
        else "2× SL"
    )
    return (
        f"{params.ticker} | {params.granularity_label} | "
        f"{params.start_dt:%Y-%m-%d %H:%M} → {params.end_dt:%Y-%m-%d %H:%M} | "
        f"{strategies} | SL {params.stop_loss_pct * 100:.2f}% / TP {tp}"
    )
