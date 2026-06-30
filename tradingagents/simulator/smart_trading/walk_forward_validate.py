"""Walk-forward mini validation on cadence switch."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd

from tradingagents.backtest.engine import fetch_historical_crypto, run_strategy_on_frame, LookbackWindow
from tradingagents.backtest.strategies import build_strategy


@dataclass
class WalkForwardResult:
    ok: bool
    num_trades: int
    return_pct: float
    message: str


def validate_cadence_switch(
    symbol: str,
    strategy_name: str,
    parameters: dict,
    lookback: str,
    *,
    config: dict,
    stop_loss_pct: float,
    take_profit_pct: float,
    transaction_cost_pct: float = 0.001,
) -> WalkForwardResult:
    """Fast 24h-ish validation before applying a new cadence."""
    try:
        lb = LookbackWindow(lookback)
    except ValueError:
        lb = LookbackWindow.H8
    try:
        end = __import__("datetime").datetime.now().strftime("%Y-%m-%d")
        df = fetch_historical_crypto(symbol, end, lb, config=config)
    except Exception as exc:
        return WalkForwardResult(False, 0, 0.0, f"Validation skipped — data error: {exc}")

    if df is None or len(df) < 30:
        return WalkForwardResult(False, 0, 0.0, "Validation skipped — insufficient bars")

    try:
        strategy = build_strategy(strategy_name, parameters)
        result = run_strategy_on_frame(
            df,
            strategy,
            symbol=symbol,
            stop_loss_pct=stop_loss_pct,
            take_profit_pct=take_profit_pct,
            transaction_cost_pct=transaction_cost_pct,
            config=config,
        )
    except Exception as exc:
        return WalkForwardResult(False, 0, 0.0, f"Validation failed: {exc}")

    ok = result.num_trades >= 1 or result.total_return_pct >= 0
    msg = (
        f"Walk-forward: {result.num_trades} trades, {result.total_return_pct:+.2f}%"
        + (" — OK" if ok else " — rejected (negative, no trades)")
    )
    return WalkForwardResult(ok, result.num_trades, result.total_return_pct, msg)
