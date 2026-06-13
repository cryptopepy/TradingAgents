"""Tests for IMPROVE-1 parity and IMPROVE-2 winner gating."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from tradingagents.backtest.engine import run_strategy_on_frame
from tradingagents.backtest.schemas import StrategyMetrics
from tradingagents.backtest.strategies import EmaCrossoverStrategy
from tradingagents.backtest.winner_gate import (
    WinnerGateConfig,
    evaluate_winner_gate,
    select_winner,
)


def _trending_ohlcv(rows: int = 120) -> pd.DataFrame:
    dates = pd.date_range("2025-01-01", periods=rows, freq="5min")
    close = pd.Series(np.linspace(100, 160, rows), dtype=float)
    return pd.DataFrame(
        {
            "Date": dates,
            "Open": close,
            "High": close + 1,
            "Low": close - 1,
            "Close": close,
            "Volume": 1_000,
        }
    )


def test_take_profit_exits_before_end_of_window():
    df = _trending_ohlcv()
    strategy = EmaCrossoverStrategy(fast_period=5, slow_period=20)
    with_tp = run_strategy_on_frame(
        df,
        strategy,
        stop_loss_pct=0.5,
        take_profit_pct=0.02,
        transaction_cost_pct=0.0,
    )
    tp_exits = [t for t in with_tp.trades if t.exit_reason == "take_profit"]
    assert tp_exits, "expected at least one take-profit exit"


def test_winner_gate_rejects_unprofitable():
    metric = StrategyMetrics(
        strategy_name="ema_crossover",
        lookback="8h",
        net_profit_ratio=-0.05,
        num_trades=10,
        max_drawdown=0.08,
    )
    gate = WinnerGateConfig(min_net_profit_ratio=0.0, min_trades=3, max_drawdown=0.15)
    ok, failures = evaluate_winner_gate(metric, gate)
    assert not ok
    assert any("net profit" in f for f in failures)


def test_winner_gate_rejects_too_few_trades():
    metric = StrategyMetrics(
        strategy_name="ema_crossover",
        lookback="8h",
        net_profit_ratio=0.05,
        num_trades=1,
        max_drawdown=0.02,
    )
    gate = WinnerGateConfig(min_trades=3)
    ok, failures = evaluate_winner_gate(metric, gate)
    assert not ok
    assert any("trades" in f for f in failures)


def test_select_winner_returns_none_when_all_fail_gate():
    metrics = [
        StrategyMetrics(
            strategy_name="a",
            lookback="8h",
            net_profit_ratio=-0.01,
            num_trades=5,
            max_drawdown=0.05,
        ),
        StrategyMetrics(
            strategy_name="b",
            lookback="24h",
            net_profit_ratio=-0.02,
            num_trades=4,
            max_drawdown=0.04,
        ),
    ]
    winner, failures = select_winner(
        metrics,
        WinnerGateConfig(),
        stop_loss_pct=0.02,
        take_profit_pct=None,
        transaction_cost_pct=0.001,
    )
    assert winner is None
    assert failures


def test_select_winner_picks_best_deployable():
    metrics = [
        StrategyMetrics(
            strategy_name="loser",
            lookback="8h",
            net_profit_ratio=-0.01,
            num_trades=5,
            max_drawdown=0.05,
        ),
        StrategyMetrics(
            strategy_name="winner",
            lookback="24h",
            net_profit_ratio=0.04,
            num_trades=6,
            max_drawdown=0.06,
            parameters={
                "_stop_loss_pct": 0.015,
                "_take_profit_pct": 0.03,
                "_transaction_cost_pct": 0.001,
            },
        ),
    ]
    winner, failures = select_winner(
        metrics,
        WinnerGateConfig(),
        stop_loss_pct=0.02,
        take_profit_pct=None,
        transaction_cost_pct=0.001,
    )
    assert failures == []
    assert winner is not None
    assert winner.strategy_name == "winner"
    assert winner.deployable
    assert winner.stop_loss_pct == pytest.approx(0.015)
    assert winner.take_profit_pct == pytest.approx(0.03)
