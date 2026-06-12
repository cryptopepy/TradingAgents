"""Mathematical strategy backtesting engine (no LLM).

Provides RSI/MACD rule evaluation with long/short support, stop-loss,
transaction costs, and configurable lookback windows (8h, 24h, 7d).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import List, Optional

import pandas as pd

from tradingagents.dataflows.stockstats_utils import load_ohlcv


class LookbackWindow(str, Enum):
    """Supported runtime lookback windows."""

    H8 = "8h"
    H24 = "24h"
    D7 = "7d"

    def to_timedelta(self) -> timedelta:
        if self == LookbackWindow.H8:
            return timedelta(hours=8)
        if self == LookbackWindow.H24:
            return timedelta(hours=24)
        return timedelta(days=7)


@dataclass
class TradeRecord:
    entry_date: str
    exit_date: str
    side: str
    entry_price: float
    exit_price: float
    pnl_pct: float
    exit_reason: str


@dataclass
class BacktestResult:
    symbol: str
    end_date: str
    lookback: LookbackWindow
    total_return_pct: float
    num_trades: int
    win_rate: float
    trades: List[TradeRecord] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)


def fetch_historical_price_slice(
    symbol: str,
    end_date: str,
    lookback_hours: int,
) -> pd.DataFrame:
    """Placeholder API: return OHLCV rows ending at ``end_date``.

    ``lookback_hours`` selects how far back from ``end_date`` to include.
    Uses daily bars from ``load_ohlcv``; intraday resolution is approximated
    by scaling the day count from hours (minimum 2 rows).
    """
    end_dt = pd.to_datetime(end_date)
    lookback_days = max(2, int(lookback_hours / 24) + 2)
    start_dt = end_dt - timedelta(days=lookback_days)
    df = load_ohlcv(symbol, end_date)
    if df.empty:
        return df
    mask = (df["Date"] >= start_dt) & (df["Date"] <= end_dt)
    return df.loc[mask].reset_index(drop=True)


def _compute_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, pd.NA)
    return 100 - (100 / (1 + rs))


def _compute_macd(series: pd.Series) -> tuple[pd.Series, pd.Series]:
    ema12 = series.ewm(span=12, adjust=False).mean()
    ema26 = series.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    return macd, signal


def run_strategy_backtest(
    symbol: str,
    end_date: str,
    lookback: LookbackWindow = LookbackWindow.D7,
    *,
    allow_short: bool = True,
    stop_loss_pct: float = 0.02,
    transaction_cost_pct: float = 0.001,
    rsi_oversold: float = 30.0,
    rsi_overbought: float = 70.0,
) -> BacktestResult:
    """Run RSI/MACD rules over the selected lookback window."""
    hours = {LookbackWindow.H8: 8, LookbackWindow.H24: 24, LookbackWindow.D7: 24 * 7}[lookback]
    df = fetch_historical_price_slice(symbol, end_date, hours)
    notes: List[str] = []

    if len(df) < 30:
        return BacktestResult(
            symbol=symbol,
            end_date=end_date,
            lookback=lookback,
            total_return_pct=0.0,
            num_trades=0,
            win_rate=0.0,
            notes=[f"Insufficient data ({len(df)} rows) for backtest"],
        )

    close = df["Close"].astype(float)
    rsi = _compute_rsi(close)
    macd, signal = _compute_macd(close)
    dates = df["Date"].dt.strftime("%Y-%m-%d").tolist()

    position = 0  # 1 long, -1 short, 0 flat
    entry_price = 0.0
    entry_idx = 0
    trades: List[TradeRecord] = []
    equity = 1.0

    for i in range(1, len(df)):
        price = float(close.iloc[i])
        prev_rsi = float(rsi.iloc[i - 1]) if pd.notna(rsi.iloc[i - 1]) else 50.0
        curr_rsi = float(rsi.iloc[i]) if pd.notna(rsi.iloc[i]) else 50.0
        prev_macd = macd.iloc[i - 1]
        curr_macd = macd.iloc[i]
        prev_sig = signal.iloc[i - 1]
        curr_sig = signal.iloc[i]
        macd_cross_up = (
            pd.notna(prev_macd)
            and pd.notna(curr_macd)
            and pd.notna(prev_sig)
            and pd.notna(curr_sig)
            and prev_macd <= prev_sig
            and curr_macd > curr_sig
        )
        macd_cross_down = (
            pd.notna(prev_macd)
            and pd.notna(curr_macd)
            and pd.notna(prev_sig)
            and pd.notna(curr_sig)
            and prev_macd >= prev_sig
            and curr_macd < curr_sig
        )

        if position != 0:
            move = (price - entry_price) / entry_price
            if position < 0:
                move = -move
            if move <= -stop_loss_pct:
                net = move - 2 * transaction_cost_pct
                equity *= 1 + net
                trades.append(
                    TradeRecord(
                        entry_date=dates[entry_idx],
                        exit_date=dates[i],
                        side="long" if position > 0 else "short",
                        entry_price=entry_price,
                        exit_price=price,
                        pnl_pct=net * 100,
                        exit_reason="stop_loss",
                    )
                )
                position = 0
                continue

        if position == 0:
            long_signal = (prev_rsi < rsi_oversold and curr_rsi >= rsi_oversold) or macd_cross_up
            short_signal = allow_short and (
                (prev_rsi > rsi_overbought and curr_rsi <= rsi_overbought) or macd_cross_down
            )
            if long_signal:
                position = 1
                entry_price = price
                entry_idx = i
                equity *= 1 - transaction_cost_pct
            elif short_signal:
                position = -1
                entry_price = price
                entry_idx = i
                equity *= 1 - transaction_cost_pct
        elif position == 1 and (curr_rsi >= rsi_overbought or macd_cross_down):
            move = (price - entry_price) / entry_price - 2 * transaction_cost_pct
            equity *= 1 + move
            trades.append(
                TradeRecord(
                    entry_date=dates[entry_idx],
                    exit_date=dates[i],
                    side="long",
                    entry_price=entry_price,
                    exit_price=price,
                    pnl_pct=move * 100,
                    exit_reason="signal_exit",
                )
            )
            position = 0
        elif position == -1 and (curr_rsi <= rsi_oversold or macd_cross_up):
            move = (entry_price - price) / entry_price - 2 * transaction_cost_pct
            equity *= 1 + move
            trades.append(
                TradeRecord(
                    entry_date=dates[entry_idx],
                    exit_date=dates[i],
                    side="short",
                    entry_price=entry_price,
                    exit_price=price,
                    pnl_pct=move * 100,
                    exit_reason="signal_exit",
                )
            )
            position = 0

    if position != 0:
        price = float(close.iloc[-1])
        move = (price - entry_price) / entry_price
        if position < 0:
            move = -move
        move -= 2 * transaction_cost_pct
        equity *= 1 + move
        trades.append(
            TradeRecord(
                entry_date=dates[entry_idx],
                exit_date=dates[-1],
                side="long" if position > 0 else "short",
                entry_price=entry_price,
                exit_price=price,
                pnl_pct=move * 100,
                exit_reason="end_of_window",
            )
        )

    wins = sum(1 for t in trades if t.pnl_pct > 0)
    win_rate = (wins / len(trades) * 100) if trades else 0.0
    return BacktestResult(
        symbol=symbol,
        end_date=end_date,
        lookback=lookback,
        total_return_pct=(equity - 1) * 100,
        num_trades=len(trades),
        win_rate=win_rate,
        trades=trades,
        notes=notes,
    )
