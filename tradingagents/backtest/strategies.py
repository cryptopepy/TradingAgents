"""Pure code-driven trading strategies (no LLM).

Each strategy exposes ``generate_signals`` returning a Series of position
targets: 1 long, -1 short, 0 flat. Crypto runs 24/7 — no session gaps.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Protocol

import numpy as np
import pandas as pd


class Strategy(Protocol):
    name: str
    parameters: Dict[str, Any]

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        """Return position targets aligned with ``df`` index (-1, 0, 1)."""


def _compute_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _compute_macd(series: pd.Series) -> tuple[pd.Series, pd.Series]:
    ema12 = series.ewm(span=12, adjust=False).mean()
    ema26 = series.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    return macd, signal


def _compute_bollinger(series: pd.Series, period: int = 20, std_mult: float = 2.0):
    mid = series.rolling(period).mean()
    std = series.rolling(period).std()
    upper = mid + std_mult * std
    lower = mid - std_mult * std
    return mid, upper, lower


@dataclass
class EmaCrossoverStrategy:
    """Strategy A: EMA crossover (fast vs slow)."""

    fast_period: int = 10
    slow_period: int = 50

    @property
    def name(self) -> str:
        return "ema_crossover"

    @property
    def parameters(self) -> Dict[str, Any]:
        return {"fast_period": self.fast_period, "slow_period": self.slow_period}

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        close = df["Close"].astype(float)
        fast = close.ewm(span=self.fast_period, adjust=False).mean()
        slow = close.ewm(span=self.slow_period, adjust=False).mean()
        signal = pd.Series(0, index=df.index, dtype=int)
        signal[fast > slow] = 1
        signal[fast < slow] = -1
        return signal


@dataclass
class RsiMeanReversionStrategy:
    """Strategy B: RSI mean reversion (buy <30, sell >70)."""

    period: int = 14
    oversold: float = 30.0
    overbought: float = 70.0

    @property
    def name(self) -> str:
        return "rsi_mean_reversion"

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "period": self.period,
            "oversold": self.oversold,
            "overbought": self.overbought,
        }

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        close = df["Close"].astype(float)
        rsi = _compute_rsi(close, self.period)
        signal = pd.Series(0, index=df.index, dtype=int)
        position = 0
        values = []
        for val in rsi:
            if pd.isna(val):
                values.append(position)
                continue
            if val < self.oversold:
                position = 1
            elif val > self.overbought:
                position = -1
            values.append(position)
        return pd.Series(values, index=df.index, dtype=int)


@dataclass
class MacdCrossoverStrategy:
    """Strategy C: MACD signal-line crossover."""

    @property
    def name(self) -> str:
        return "macd_crossover"

    @property
    def parameters(self) -> Dict[str, Any]:
        return {"fast": 12, "slow": 26, "signal": 9}

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        close = df["Close"].astype(float)
        macd, sig = _compute_macd(close)
        signal = pd.Series(0, index=df.index, dtype=int)
        signal[macd > sig] = 1
        signal[macd < sig] = -1
        return signal


@dataclass
class BollingerMeanReversionStrategy:
    """Strategy D: Bollinger band mean reversion."""

    period: int = 20
    std_mult: float = 2.0

    @property
    def name(self) -> str:
        return "bollinger_mean_reversion"

    @property
    def parameters(self) -> Dict[str, Any]:
        return {"period": self.period, "std_mult": self.std_mult}

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        close = df["Close"].astype(float)
        _, upper, lower = _compute_bollinger(close, self.period, self.std_mult)
        signal = pd.Series(0, index=df.index, dtype=int)
        position = 0
        values = []
        for price, hi, lo in zip(close, upper, lower):
            if pd.isna(hi) or pd.isna(lo):
                values.append(position)
                continue
            if price <= lo:
                position = 1
            elif price >= hi:
                position = -1
            values.append(position)
        return pd.Series(values, index=df.index, dtype=int)


DEFAULT_STRATEGIES: list[Strategy] = [
    EmaCrossoverStrategy(),
    RsiMeanReversionStrategy(),
    MacdCrossoverStrategy(),
    BollingerMeanReversionStrategy(),
]
