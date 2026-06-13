"""Walk-forward train/validate splitting for backtest optimization."""

from __future__ import annotations

import pandas as pd

from .schemas import StrategyMetrics
from .winner_gate import WinnerGateConfig, evaluate_winner_gate


def validate_bars_for_hours(validate_hours: float, granularity_seconds: int) -> int:
    return max(1, int(validate_hours * 3600 / granularity_seconds))


def split_walk_forward(
    df: pd.DataFrame,
    validate_hours: float,
    granularity_seconds: int,
    *,
    min_train_bars: int = 30,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split OHLCV into train (older) and validate (recent hold-out) segments."""
    validate_bars = validate_bars_for_hours(validate_hours, granularity_seconds)
    if len(df) < min_train_bars + validate_bars:
        raise ValueError(
            f"insufficient bars for walk-forward ({len(df)} < {min_train_bars + validate_bars})"
        )
    train_df = df.iloc[:-validate_bars].copy().reset_index(drop=True)
    validate_df = df.iloc[-validate_bars:].copy().reset_index(drop=True)
    return train_df, validate_df


def attach_walk_forward_fields(
    metric: StrategyMetrics,
    *,
    train_metric: StrategyMetrics,
    validate_metric: StrategyMetrics,
) -> StrategyMetrics:
    notes = list(metric.notes)
    notes.append(
        f"walk-forward train {train_metric.net_profit_ratio:+.2%} / "
        f"validate {validate_metric.net_profit_ratio:+.2%}"
    )
    return metric.model_copy(
        update={
            "net_profit_ratio": validate_metric.net_profit_ratio,
            "profit_factor": validate_metric.profit_factor,
            "sharpe_ratio": validate_metric.sharpe_ratio,
            "max_drawdown": validate_metric.max_drawdown,
            "num_trades": validate_metric.num_trades,
            "win_rate": validate_metric.win_rate,
            "train_net_profit_ratio": train_metric.net_profit_ratio,
            "validate_net_profit_ratio": validate_metric.net_profit_ratio,
            "notes": notes,
        }
    )


def walk_forward_deployable(
    train_metric: StrategyMetrics,
    validate_metric: StrategyMetrics,
    gate: WinnerGateConfig,
) -> tuple[bool, list[str]]:
    """Both train and validate segments must pass winner gates."""
    train_ok, train_fail = evaluate_winner_gate(train_metric, gate)
    val_ok, val_fail = evaluate_winner_gate(validate_metric, gate)
    failures: list[str] = []
    if not train_ok:
        failures.extend(f"train: {f}" for f in train_fail)
    if not val_ok:
        failures.extend(f"validate: {f}" for f in val_fail)
    return train_ok and val_ok, failures
