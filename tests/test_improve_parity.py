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
            profit_factor=1.6,
            win_rate=55.0,
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
        config={"winner_selection_mode": "flat"},
    )
    assert failures == []
    assert winner is not None
    assert winner.strategy_name == "winner"
    assert winner.deployable
    assert winner.stop_loss_pct == pytest.approx(0.015)
    assert winner.take_profit_pct == pytest.approx(0.03)


def test_multi_horizon_rejects_short_horizon_only_winner():
    metrics = [
        StrategyMetrics(
            strategy_name="flash",
            lookback="8h",
            net_profit_ratio=0.10,
            num_trades=5,
            max_drawdown=0.03,
            profit_factor=2.5,
            win_rate=65.0,
        ),
        StrategyMetrics(
            strategy_name="flash",
            lookback="24h",
            net_profit_ratio=-0.01,
            num_trades=4,
            max_drawdown=0.08,
            profit_factor=0.9,
            win_rate=40.0,
        ),
    ]
    winner, failures = select_winner(
        metrics,
        WinnerGateConfig(),
        stop_loss_pct=0.02,
        take_profit_pct=None,
        transaction_cost_pct=0.001,
        config={
            "winner_selection_mode": "multi_horizon",
            "winner_require_long_horizon": True,
            "winner_score_mode": "composite",
        },
    )
    assert winner is None
    assert any("long-horizon" in line for line in failures)


def test_multi_horizon_prefers_stable_long_window():
    metrics = [
        StrategyMetrics(
            strategy_name="steady",
            lookback="8h",
            net_profit_ratio=0.02,
            num_trades=5,
            max_drawdown=0.05,
            profit_factor=1.4,
            win_rate=52.0,
        ),
        StrategyMetrics(
            strategy_name="steady",
            lookback="7d",
            net_profit_ratio=0.04,
            num_trades=6,
            max_drawdown=0.08,
            profit_factor=1.7,
            win_rate=58.0,
        ),
        StrategyMetrics(
            strategy_name="flash",
            lookback="8h",
            net_profit_ratio=0.15,
            num_trades=5,
            max_drawdown=0.02,
            profit_factor=3.0,
            win_rate=70.0,
        ),
    ]
    winner, failures = select_winner(
        metrics,
        WinnerGateConfig(),
        stop_loss_pct=0.02,
        take_profit_pct=None,
        transaction_cost_pct=0.001,
        config={
            "winner_selection_mode": "multi_horizon",
            "winner_require_long_horizon": True,
            "winner_score_mode": "composite",
        },
    )
    assert failures == []
    assert winner is not None
    assert winner.strategy_name == "steady"
    assert winner.lookback == "7d"


def test_param_search_returns_multiple_candidates_when_enabled():
    from tradingagents.backtest.param_search import param_candidates

    cfg = {"optimize_strategy_params": True, "param_search_samples": 5}
    candidates = param_candidates("rsi_mean_reversion", cfg)
    assert len(candidates) >= 2
    assert candidates[0] != candidates[1] or len(candidates) == 1


def test_walk_forward_split_reserves_recent_bars():
    from tradingagents.backtest.walk_forward import split_walk_forward

    df = _trending_ohlcv(150)
    train, validate = split_walk_forward(df, validate_hours=8, granularity_seconds=300)
    assert len(validate) == 96
    assert len(train) == 54


def test_walk_forward_rejects_when_validate_fails_gate():
    from tradingagents.backtest.walk_forward import walk_forward_deployable
    from tradingagents.backtest.winner_gate import WinnerGateConfig

    train = StrategyMetrics(
        strategy_name="ema_crossover",
        lookback="8h",
        net_profit_ratio=0.05,
        num_trades=5,
        max_drawdown=0.05,
    )
    validate = StrategyMetrics(
        strategy_name="ema_crossover",
        lookback="8h",
        net_profit_ratio=-0.02,
        num_trades=4,
        max_drawdown=0.08,
    )
    ok, failures = walk_forward_deployable(train, validate, WinnerGateConfig())
    assert not ok
    assert failures
