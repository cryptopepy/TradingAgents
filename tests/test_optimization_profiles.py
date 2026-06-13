"""Tests for optimization profiles, risk variants, and ATR stops."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from tradingagents.backtest.optimization_profile import (
    enrich_optimization_config,
    is_alt_symbol,
    is_major_symbol,
)
from tradingagents.backtest.risk_variants import (
    RiskVariant,
    iter_risk_variants,
    resolve_atr_stop_pcts,
    resolve_position_stop_pcts,
)
from tradingagents.backtest.signal_filters import apply_min_edge_filter, prepare_strategy_signals
from tradingagents.backtest.engine import run_strategy_on_frame
from tradingagents.backtest.strategies import RsiMeanReversionStrategy


def _ohlcv(rows: int = 80, *, volatile: bool = False) -> pd.DataFrame:
    dates = pd.date_range("2025-01-01", periods=rows, freq="5min")
    if volatile:
        rng = np.random.default_rng(42)
        close = 100 + np.cumsum(rng.normal(0, 2, rows))
    else:
        close = np.linspace(100, 120, rows)
    close = pd.Series(close, dtype=float)
    spread = 2.0 if volatile else 0.5
    return pd.DataFrame(
        {
            "Date": dates,
            "Open": close,
            "High": close + spread,
            "Low": close - spread,
            "Close": close,
            "Volume": 1000,
        }
    )


def test_major_vs_alt_detection():
    assert is_major_symbol("BTC/USDT")
    assert is_major_symbol("ETH/USD")
    assert is_alt_symbol("SOL/USDT")
    assert is_alt_symbol("STG/USD")


def test_enrich_config_enables_filters_for_all():
    cfg = enrich_optimization_config({}, "BTC/USDT")
    assert cfg["regime_filter_enabled"] is True
    assert cfg["atr_stops_enabled"] is True
    assert cfg["min_edge_filter_enabled"] is True
    assert cfg["min_bars_between_trades"] >= 1
    assert cfg["optimize_strategy_params"] is False


def test_enrich_config_richer_for_alts():
    cfg = enrich_optimization_config({}, "SOL/USDT")
    assert cfg["optimize_strategy_params"] is True
    assert cfg["walk_forward_enabled"] is True
    assert cfg["param_search_samples"] >= 12


def test_major_risk_variants_count():
    cfg = enrich_optimization_config({}, "BTC/USDT")
    variants = iter_risk_variants(
        cfg,
        symbol="BTC/USDT",
        stop_loss_pct=0.02,
        take_profit_pct=0.04,
        transaction_cost_pct=0.001,
        is_alt=False,
    )
    assert len(variants) == 3
    assert all(v.atr_stops for v in variants)


def test_alt_risk_variants_expanded():
    cfg = enrich_optimization_config({}, "SOL/USDT")
    variants = iter_risk_variants(
        cfg,
        symbol="SOL/USDT",
        stop_loss_pct=0.02,
        take_profit_pct=0.04,
        transaction_cost_pct=0.001,
        is_alt=True,
    )
    assert len(variants) >= 8


def test_resolve_atr_stop_pcts_within_bounds():
    df = _ohlcv(40, volatile=True)
    sl, tp = resolve_atr_stop_pcts(
        df,
        30,
        float(df["Close"].iloc[30]),
        {"atr_stop_min_pct": 0.008, "atr_stop_max_pct": 0.06},
        atr_sl_mult=2.0,
        atr_tp_mult=3.5,
        fallback_sl=0.02,
        fallback_tp=0.04,
    )
    assert 0.008 <= sl <= 0.06
    assert tp > sl


def test_min_edge_filter_blocks_low_vol_entries():
    dates = pd.date_range("2025-01-01", periods=40, freq="5min")
    close = pd.Series([100.0] * 40)
    df = pd.DataFrame(
        {
            "Date": dates,
            "Open": close,
            "High": close + 0.01,
            "Low": close - 0.01,
            "Close": close,
            "Volume": 1000,
        }
    )
    signals = pd.Series([0] * 39 + [1])
    cfg = {
        "min_edge_filter_enabled": True,
        "min_edge_fee_multiple": 3.0,
        "_transaction_cost_pct": 0.001,
    }
    filtered = apply_min_edge_filter(df, signals, cfg)
    assert filtered.iloc[-1] == 0


def test_run_strategy_on_frame_records_effective_atr_stops():
    df = _ohlcv(80, volatile=True)
    strategy = RsiMeanReversionStrategy(oversold=35, overbought=65)
    variant = RiskVariant(0.02, 0.04, 0.001, atr_stops=True, atr_sl_mult=2.0, atr_tp_mult=3.5)
    cfg = enrich_optimization_config({}, "SOL/USDT")
    result = run_strategy_on_frame(
        df,
        strategy,
        config=cfg,
        risk_variant=variant,
    )
    if result.num_trades > 0:
        assert result.effective_stop_loss_pct is not None
        assert result.effective_take_profit_pct is not None
        assert result.effective_stop_loss_pct > 0


def test_prepare_strategy_signals_applies_min_edge():
    dates = pd.date_range("2025-01-01", periods=50, freq="5min")
    close = pd.Series([100.0] * 50)
    df = pd.DataFrame(
        {
            "Date": dates,
            "Open": close,
            "High": close + 0.01,
            "Low": close - 0.01,
            "Close": close,
            "Volume": 1000,
        }
    )
    signals = pd.Series([1] * len(df))
    cfg = enrich_optimization_config({}, "BTC/USDT")
    cfg["_transaction_cost_pct"] = 0.001
    out = prepare_strategy_signals(df, "ema_crossover", signals, cfg)
    assert (out.iloc[20:] == 0).all()
