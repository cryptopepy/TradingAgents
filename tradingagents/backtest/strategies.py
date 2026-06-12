"""Pure code-driven trading strategies (no LLM).

Each strategy exposes ``generate_signals`` returning a Series of position
targets: 1 long, -1 short, 0 flat. Crypto runs 24/7 — no session gaps.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Protocol, Type

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


def _wilder_smooth(series: pd.Series, period: int) -> pd.Series:
    """Wilder smoothing (RMA) via EWM with alpha=1/period."""
    return series.ewm(alpha=1.0 / period, adjust=False).mean()


def _typical_price(df: pd.DataFrame) -> pd.Series:
    return (df["High"].astype(float) + df["Low"].astype(float) + df["Close"].astype(float)) / 3.0


def _cross_above(a: pd.Series, b: pd.Series) -> pd.Series:
    return (a > b) & (a.shift(1) <= b.shift(1))


def _cross_below(a: pd.Series, b: pd.Series) -> pd.Series:
    return (a < b) & (a.shift(1) >= b.shift(1))


def compute_chande_momentum_oscillator(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Chande Momentum Oscillator: 100 * (sum_up - sum_down) / (sum_up + sum_down)."""
    close = df["Close"].astype(float)
    delta = close.diff()
    up = delta.clip(lower=0)
    down = (-delta.clip(upper=0))
    sum_up = up.rolling(period).sum()
    sum_down = down.rolling(period).sum()
    denom = (sum_up + sum_down).replace(0, np.nan)
    return 100.0 * (sum_up - sum_down) / denom


def compute_adx(df: pd.DataFrame, period: int = 14) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Average Directional Index with +DI and -DI (Wilder smoothing)."""
    high = df["High"].astype(float)
    low = df["Low"].astype(float)
    close = df["Close"].astype(float)

    up_move = high.diff()
    down_move = -low.diff()

    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    prev_close = close.shift(1)
    tr = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)

    tr_smooth = _wilder_smooth(tr, period)
    plus_dm_smooth = _wilder_smooth(pd.Series(plus_dm, index=df.index), period)
    minus_dm_smooth = _wilder_smooth(pd.Series(minus_dm, index=df.index), period)

    plus_di = 100.0 * plus_dm_smooth / tr_smooth.replace(0, np.nan)
    minus_di = 100.0 * minus_dm_smooth / tr_smooth.replace(0, np.nan)

    di_sum = (plus_di + minus_di).replace(0, np.nan)
    dx = 100.0 * (plus_di - minus_di).abs() / di_sum
    adx = _wilder_smooth(dx, period)

    return adx, plus_di, minus_di


def compute_vwap_bands(
    df: pd.DataFrame,
    period: int = 20,
    std_mult: float = 2.0,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Rolling VWAP with volume-weighted standard deviation bands."""
    tp = _typical_price(df)
    vol = df["Volume"].astype(float).replace(0, np.nan)

    vol_sum = vol.rolling(period).sum()
    vwap = (tp * vol).rolling(period).sum() / vol_sum

    squared_diff = vol * (tp - vwap) ** 2
    vw_var = squared_diff.rolling(period).sum() / vol_sum
    vw_std = np.sqrt(vw_var.clip(lower=0))

    upper = vwap + std_mult * vw_std
    lower = vwap - std_mult * vw_std
    return vwap, upper, lower


def compute_cci(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """Commodity Channel Index."""
    tp = _typical_price(df)
    sma = tp.rolling(period).mean()
    mean_dev = tp.rolling(period).apply(lambda x: np.mean(np.abs(x - np.mean(x))), raw=True)
    return (tp - sma) / (0.015 * mean_dev.replace(0, np.nan))


def compute_trix(df: pd.DataFrame, period: int = 9) -> tuple[pd.Series, pd.Series]:
    """TRIX oscillator and its signal line (EMA of TRIX)."""
    close = df["Close"].astype(float)
    ema1 = close.ewm(span=period, adjust=False).mean()
    ema2 = ema1.ewm(span=period, adjust=False).mean()
    ema3 = ema2.ewm(span=period, adjust=False).mean()
    trix = (ema3 - ema3.shift(1)) / ema3.shift(1).replace(0, np.nan) * 100.0
    signal = trix.ewm(span=period, adjust=False).mean()
    return trix, signal


def compute_apo(
    df: pd.DataFrame,
    fast: int = 10,
    slow: int = 20,
) -> pd.Series:
    """Absolute Price Oscillator: fast EMA minus slow EMA."""
    close = df["Close"].astype(float)
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    return ema_fast - ema_slow


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


@dataclass
class CmoMeanReversionStrategy:
    """Strategy E: CMO mean reversion (long < -50, short > 50)."""

    period: int = 14
    oversold: float = -50.0
    overbought: float = 50.0

    @property
    def name(self) -> str:
        return "cmo_mean_reversion"

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "period": self.period,
            "oversold": self.oversold,
            "overbought": self.overbought,
        }

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        cmo = compute_chande_momentum_oscillator(df, self.period)
        signal = pd.Series(0, index=df.index, dtype=int)
        position = 0
        values = []
        for val in cmo:
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
class AdxTrendFilterStrategy:
    """Strategy F: ADX trend filter with directional movement."""

    period: int = 14
    adx_threshold: float = 25.0

    @property
    def name(self) -> str:
        return "adx_trend_filter"

    @property
    def parameters(self) -> Dict[str, Any]:
        return {"period": self.period, "adx_threshold": self.adx_threshold}

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        adx, plus_di, minus_di = compute_adx(df, self.period)
        signal = pd.Series(0, index=df.index, dtype=int)
        trending = adx > self.adx_threshold
        signal[trending & (plus_di > minus_di)] = 1
        signal[trending & (minus_di > plus_di)] = -1
        return signal


@dataclass
class VwapBandMeanReversionStrategy:
    """Strategy G: VWAP band mean reversion (cross back into bands)."""

    period: int = 20
    std_mult: float = 2.0

    @property
    def name(self) -> str:
        return "vwap_band_mean_reversion"

    @property
    def parameters(self) -> Dict[str, Any]:
        return {"period": self.period, "std_mult": self.std_mult}

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        close = df["Close"].astype(float)
        _, upper, lower = compute_vwap_bands(df, self.period, self.std_mult)
        signal = pd.Series(0, index=df.index, dtype=int)
        position = 0
        was_below = False
        was_above = False
        values = []
        for price, hi, lo in zip(close, upper, lower):
            if pd.isna(hi) or pd.isna(lo):
                values.append(position)
                continue
            if price < lo:
                was_below = True
            if price > hi:
                was_above = True
            if was_below and price >= lo:
                position = 1
                was_below = False
            elif was_above and price <= hi:
                position = -1
                was_above = False
            values.append(position)
        return pd.Series(values, index=df.index, dtype=int)


@dataclass
class CciBreakoutStrategy:
    """Strategy H: CCI breakout (cross ±100)."""

    period: int = 20
    upper_threshold: float = 100.0
    lower_threshold: float = -100.0

    @property
    def name(self) -> str:
        return "cci_breakout"

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "period": self.period,
            "upper_threshold": self.upper_threshold,
            "lower_threshold": self.lower_threshold,
        }

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        cci = compute_cci(df, self.period)
        signal = pd.Series(0, index=df.index, dtype=int)
        position = 0
        values = []
        prev_cci = np.nan
        for val in cci:
            if pd.isna(val):
                values.append(position)
                prev_cci = val
                continue
            if not pd.isna(prev_cci):
                if prev_cci <= self.upper_threshold and val > self.upper_threshold:
                    position = 1
                elif prev_cci >= self.lower_threshold and val < self.lower_threshold:
                    position = -1
            values.append(position)
            prev_cci = val
        return pd.Series(values, index=df.index, dtype=int)


@dataclass
class TrixMomentumStrategy:
    """Strategy I: TRIX momentum crossover with signal line."""

    period: int = 9

    @property
    def name(self) -> str:
        return "trix_momentum"

    @property
    def parameters(self) -> Dict[str, Any]:
        return {"period": self.period}

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        trix, sig = compute_trix(df, self.period)
        signal = pd.Series(0, index=df.index, dtype=int)
        position = 0
        values = []
        prev_trix = np.nan
        prev_sig = np.nan
        for t_val, s_val in zip(trix, sig):
            if pd.isna(t_val) or pd.isna(s_val):
                values.append(position)
                prev_trix, prev_sig = t_val, s_val
                continue
            if not pd.isna(prev_trix) and not pd.isna(prev_sig):
                if prev_trix <= prev_sig and t_val > s_val:
                    position = 1
                elif prev_trix >= prev_sig and t_val < s_val:
                    position = -1
            values.append(position)
            prev_trix, prev_sig = t_val, s_val
        return pd.Series(values, index=df.index, dtype=int)


@dataclass
class ApoCrossoverStrategy:
    """Strategy J: APO zero-line crossover."""

    fast: int = 10
    slow: int = 20

    @property
    def name(self) -> str:
        return "apo_crossover"

    @property
    def parameters(self) -> Dict[str, Any]:
        return {"fast": self.fast, "slow": self.slow}

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        apo = compute_apo(df, self.fast, self.slow)
        signal = pd.Series(0, index=df.index, dtype=int)
        position = 0
        values = []
        prev = np.nan
        for val in apo:
            if pd.isna(val):
                values.append(position)
                prev = val
                continue
            if not pd.isna(prev):
                if prev <= 0 and val > 0:
                    position = 1
                elif prev >= 0 and val < 0:
                    position = -1
            values.append(position)
            prev = val
        return pd.Series(values, index=df.index, dtype=int)


STRATEGY_REGISTRY: Dict[str, Type[Any]] = {
    "ema_crossover": EmaCrossoverStrategy,
    "rsi_mean_reversion": RsiMeanReversionStrategy,
    "macd_crossover": MacdCrossoverStrategy,
    "bollinger_mean_reversion": BollingerMeanReversionStrategy,
    "cmo_mean_reversion": CmoMeanReversionStrategy,
    "adx_trend_filter": AdxTrendFilterStrategy,
    "vwap_band_mean_reversion": VwapBandMeanReversionStrategy,
    "cci_breakout": CciBreakoutStrategy,
    "trix_momentum": TrixMomentumStrategy,
    "apo_crossover": ApoCrossoverStrategy,
}


def build_strategy(name: str, parameters: Dict[str, Any] | None = None) -> Strategy:
    """Instantiate a strategy from the registry by name."""
    cls = STRATEGY_REGISTRY.get(name)
    if cls is None:
        raise KeyError(f"Unknown strategy: {name}")
    params = parameters or {}
    fields = getattr(cls, "__dataclass_fields__", {})
    filtered = {k: v for k, v in params.items() if k in fields}
    return cls(**filtered)


def build_default_strategies() -> list[Strategy]:
    """Return fresh instances of all registered strategies (A–J)."""
    return [cls() for cls in STRATEGY_REGISTRY.values()]


DEFAULT_STRATEGIES: list[Strategy] = build_default_strategies()
