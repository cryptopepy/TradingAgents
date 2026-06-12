"""Backtest input validation and result guards."""

from __future__ import annotations

import datetime as dt
from typing import Sequence

from tradingagents.backtest.schemas import OptimizationResult
from tradingagents.dataflows.symbol_utils import parse_crypto_pair


class BacktestValidationError(ValueError):
    """Raised when backtest inputs or outputs are invalid."""


class BacktestDataError(BacktestValidationError):
    """Raised when historical OHLCV cannot be loaded for backtesting."""


def validate_ticker(ticker: str) -> str:
    """Normalize and validate a crypto pair string."""
    if not ticker or not str(ticker).strip():
        raise BacktestValidationError(
            "Ticker is required. Example: BTC/USDT, ETH/USDC, SOL/USD"
        )
    try:
        return parse_crypto_pair(ticker).display
    except ValueError as exc:
        raise BacktestValidationError(f"Invalid crypto pair {ticker!r}: {exc}") from exc


def validate_end_date(end_date: str) -> str:
    """Validate YYYY-MM-DD and ensure the date is not in the future."""
    if not end_date or not str(end_date).strip():
        raise BacktestValidationError("End date is required (YYYY-MM-DD).")
    try:
        parsed = dt.datetime.strptime(end_date.strip(), "%Y-%m-%d").date()
    except ValueError as exc:
        raise BacktestValidationError(
            f"Invalid end date {end_date!r}. Use YYYY-MM-DD."
        ) from exc
    if parsed > dt.date.today():
        raise BacktestValidationError(
            f"End date {end_date} cannot be in the future."
        )
    return parsed.strftime("%Y-%m-%d")


def validate_positive_float(
    value: float,
    *,
    name: str,
    minimum: float = 0.0,
) -> float:
    if value < minimum:
        raise BacktestValidationError(f"{name} must be >= {minimum}, got {value}")
    return value


def require_optimization_results(result: OptimizationResult) -> OptimizationResult:
    """Ensure optimization produced at least one strategy metric."""
    if result.results:
        return result

    lines = [
        "Backtest produced no strategy metrics — nothing to rank or deploy.",
        f"Symbol: {result.symbol} | End date: {result.end_date}",
    ]
    if result.warnings:
        lines.append("")
        lines.append("Diagnostics:")
        lines.extend(f"  • {w}" for w in result.warnings)
    else:
        lines.extend(
            [
                "",
                "Common causes:",
                "  • CryptoCompare/Binance/ccxt could not fetch intraday candles",
                "  • Lookback window returned fewer than 30 bars",
                "  • Invalid or illiquid pair for the selected end date",
                "  • Geo-blocked Binance API (try --live for ccxt fallback)",
            ]
        )
    raise BacktestValidationError("\n".join(lines))


def format_validation_errors(errors: Sequence[str]) -> str:
    return "\n".join(f"  • {e}" for e in errors)
