"""Post-process strategy signals: regime gate and trade cooldown."""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from .strategies import compute_adx

MEAN_REVERT_STRATEGIES = frozenset(
    {
        "rsi_mean_reversion",
        "bollinger_mean_reversion",
        "cmo_mean_reversion",
        "vwap_band_mean_reversion",
    }
)

TREND_STRATEGIES = frozenset(
    {
        "ema_crossover",
        "macd_crossover",
        "adx_trend_filter",
        "cci_breakout",
        "trix_momentum",
        "apo_crossover",
    }
)


def _compute_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high = df["High"].astype(float)
    low = df["Low"].astype(float)
    close = df["Close"].astype(float)
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.rolling(period).mean()


def resolve_position_sizing_pct(df: pd.DataFrame, config: dict) -> float:
    """Fraction of equity per trade (1.0 = full). Optional ATR inverse scaling."""
    base = float(config.get("position_size_pct", 1.0))
    base = float(np.clip(base, 0.05, 1.0))
    if not config.get("atr_position_sizing"):
        return base

    atr = _compute_atr(df)
    current = float(atr.iloc[-1]) if len(atr) else 0.0
    target = float(config.get("atr_target_pct", 0.02)) * float(df["Close"].iloc[-1])
    if current <= 0 or target <= 0:
        return base
    scale = float(np.clip(target / current, 0.25, 1.0))
    return float(np.clip(base * scale, 0.05, 1.0))


def apply_regime_filter(
    df: pd.DataFrame,
    signals: pd.Series,
    strategy_name: str,
    *,
    enabled: bool,
    adx_trend_threshold: float = 25.0,
    adx_chop_threshold: float = 20.0,
) -> pd.Series:
    """Flat mean-revert signals in strong trends; flat trend signals in chop."""
    if not enabled or strategy_name not in MEAN_REVERT_STRATEGIES | TREND_STRATEGIES:
        return signals

    adx, _, _ = compute_adx(df)
    out = signals.copy()
    for i in range(len(out)):
        val = adx.iloc[i]
        if pd.isna(val):
            continue
        if strategy_name in MEAN_REVERT_STRATEGIES and float(val) > adx_trend_threshold:
            out.iloc[i] = 0
        elif strategy_name in TREND_STRATEGIES and float(val) < adx_chop_threshold:
            out.iloc[i] = 0
    return out


def apply_trade_cooldown(signals: pd.Series, min_bars: int) -> pd.Series:
    """Suppress new entries for ``min_bars`` after an exit or side flip."""
    if min_bars <= 0:
        return signals

    out = signals.copy()
    prev = 0
    wait = 0

    for i in range(len(out)):
        target = int(out.iloc[i]) if pd.notna(out.iloc[i]) else 0

        if wait > 0:
            entering = prev == 0 and target != 0
            flipping = prev != 0 and target != 0 and target != prev
            if entering or flipping:
                target = prev if prev != 0 else 0
            wait -= 1

        if prev != 0 and (target == 0 or (target != 0 and target != prev)):
            wait = min_bars

        out.iloc[i] = target
        prev = target
    return out


def prepare_strategy_signals(
    df: pd.DataFrame,
    strategy_name: str,
    signals: pd.Series,
    config: Optional[dict] = None,
) -> pd.Series:
    """Apply regime filter and trade cooldown (no-op when disabled)."""
    cfg = config or {}
    filtered = apply_regime_filter(
        df,
        signals,
        strategy_name,
        enabled=bool(cfg.get("regime_filter_enabled")),
    )
    return apply_trade_cooldown(
        filtered,
        int(cfg.get("min_bars_between_trades", 0)),
    )
