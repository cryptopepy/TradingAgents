"""Tests for IMPROVE-7 signal filters and composite winner score."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from tradingagents.backtest.schemas import StrategyMetrics
from tradingagents.backtest.signal_filters import (
    apply_regime_filter,
    apply_trade_cooldown,
    resolve_position_sizing_pct,
)
from tradingagents.backtest.winner_gate import WinnerGateConfig, metric_selection_score, select_winner


def _ohlcv_from_close(close: np.ndarray) -> pd.DataFrame:
    close = pd.Series(close, dtype=float)
    return pd.DataFrame(
        {
            "Date": pd.date_range("2025-01-01", periods=len(close), freq="5min"),
            "Open": close,
            "High": close + 1,
            "Low": close - 1,
            "Close": close,
            "Volume": 1000,
        }
    )


def test_trade_cooldown_blocks_immediate_reentry():
    signals = pd.Series([1, 0, 1])
    cooled = apply_trade_cooldown(signals, min_bars=1)
    assert list(cooled) == [1, 0, 0]

    churn = pd.Series([0, 1, 0, 1, -1, 0, -1])
    cooled_churn = apply_trade_cooldown(churn, min_bars=2)
    assert cooled_churn.iloc[3] == 0


def test_regime_filter_flats_mean_revert_in_trend():
    # Steady climb -> ADX should be elevated
    close = np.linspace(100, 200, 80)
    df = _ohlcv_from_close(close)
    signals = pd.Series([1] * len(df))
    filtered = apply_regime_filter(
        df,
        signals,
        "rsi_mean_reversion",
        enabled=True,
    )
    assert (filtered.iloc[-10:] == 0).any()


def test_position_sizing_pct_clamped():
    df = _ohlcv_from_close(np.linspace(100, 110, 30))
    assert resolve_position_sizing_pct(df, {"position_size_pct": 0.5}) == 0.5
    assert resolve_position_sizing_pct(df, {}) == 1.0


def test_composite_score_prefers_better_risk_adjusted_metric():
    high_dd = StrategyMetrics(
        strategy_name="a",
        lookback="8h",
        net_profit_ratio=0.10,
        profit_factor=1.2,
        max_drawdown=0.20,
        num_trades=5,
    )
    low_dd = StrategyMetrics(
        strategy_name="b",
        lookback="8h",
        net_profit_ratio=0.08,
        profit_factor=2.0,
        max_drawdown=0.05,
        num_trades=5,
    )
    cfg = {"winner_score_mode": "composite", "winner_selection_mode": "flat"}
    assert metric_selection_score(low_dd, cfg) > metric_selection_score(high_dd, cfg)

    winner, _ = select_winner(
        [high_dd, low_dd],
        WinnerGateConfig(),
        stop_loss_pct=0.02,
        take_profit_pct=None,
        transaction_cost_pct=0.001,
        config=cfg,
    )
    assert winner is not None
    assert winner.strategy_name == "b"
