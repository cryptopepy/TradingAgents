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


def compute_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
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


_compute_atr = compute_atr  # legacy alias


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


def apply_min_edge_filter(
    df: pd.DataFrame,
    signals: pd.Series,
    config: dict,
) -> pd.Series:
    """Skip entries when expected ATR move is below fee round-trip × multiplier."""
    if not config.get("min_edge_filter_enabled"):
        return signals

    mult = float(config.get("min_edge_fee_multiple", 3.0))
    cost = float(config.get("_transaction_cost_pct", config.get("transaction_cost_pct", 0.001)))
    min_move = mult * 2.0 * cost
    period = int(config.get("atr_period", 14))
    atr = compute_atr(df, period)
    close = df["Close"].astype(float)
    out = signals.copy()
    for i in range(len(out)):
        target = int(out.iloc[i]) if pd.notna(out.iloc[i]) else 0
        if target == 0:
            continue
        price = float(close.iloc[i])
        atr_val = float(atr.iloc[i]) if i < len(atr) else float("nan")
        if price <= 0 or pd.isna(atr_val):
            continue
        if (atr_val / price) < min_move:
            out.iloc[i] = 0
    return out


def apply_signal_confirm_bars(signals: pd.Series, confirm_bars: int) -> pd.Series:
    """Require N consecutive bars in same direction before entry."""
    if confirm_bars <= 0:
        return signals
    out = signals.copy()
    streak = 0
    last_dir = 0
    for i in range(len(out)):
        target = int(out.iloc[i]) if pd.notna(out.iloc[i]) else 0
        if target == 0:
            streak = 0
            last_dir = 0
            continue
        if target == last_dir:
            streak += 1
        else:
            streak = 1
            last_dir = target
        if streak < confirm_bars:
            out.iloc[i] = 0
    return out


def prepare_strategy_signals(
    df: pd.DataFrame,
    strategy_name: str,
    signals: pd.Series,
    config: Optional[dict] = None,
) -> pd.Series:
    """Apply regime filter, min-edge gate, confirm bars, and trade cooldown."""
    cfg = config or {}
    filtered = apply_regime_filter(
        df,
        signals,
        strategy_name,
        enabled=bool(cfg.get("regime_filter_enabled")),
        adx_trend_threshold=float(cfg.get("adx_trend_threshold", 25.0)),
        adx_chop_threshold=float(cfg.get("adx_chop_threshold", 20.0)),
    )
    filtered = apply_min_edge_filter(df, filtered, cfg)
    filtered = apply_signal_confirm_bars(filtered, int(cfg.get("signal_confirm_bars", 0)))
    return apply_trade_cooldown(
        filtered,
        int(cfg.get("min_bars_between_trades", 0)),
    )
