"""Winner selection gates for strategy optimization."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

from .schemas import StrategyMetrics, WinningStrategySummary


@dataclass(frozen=True)
class WinnerGateConfig:
    """Minimum quality bars for deploying an optimized strategy."""

    min_net_profit_ratio: float = 0.0
    min_trades: int = 3
    max_drawdown: float = 0.15
    enabled: bool = True


def winner_gate_from_config(config: dict) -> WinnerGateConfig:
    """Build gate config from application config / env overrides."""
    return WinnerGateConfig(
        min_net_profit_ratio=float(config.get("winner_min_net_profit", 0.0)),
        min_trades=int(config.get("winner_min_trades", 3)),
        max_drawdown=float(config.get("winner_max_drawdown_pct", 0.15)),
        enabled=bool(config.get("winner_gate_enabled", True)),
    )


def metric_selection_score(metric: StrategyMetrics, config: dict) -> float:
    """Ranking key for winner selection (higher is better)."""
    mode = str(config.get("winner_score_mode", "net_profit")).strip().lower()
    if mode == "composite":
        pf = min(float(metric.profit_factor), 3.0)
        return float(metric.net_profit_ratio) * pf / (1.0 + float(metric.max_drawdown))
    return float(metric.net_profit_ratio)


def evaluate_winner_gate(
    metric: StrategyMetrics,
    gate: WinnerGateConfig,
) -> Tuple[bool, List[str]]:
    """Return whether metric passes gate and human-readable failure reasons."""
    if not gate.enabled:
        return True, []

    failures: List[str] = []
    if metric.net_profit_ratio <= gate.min_net_profit_ratio:
        failures.append(
            f"net profit {metric.net_profit_ratio * 100:.2f}% "
            f"≤ min {gate.min_net_profit_ratio * 100:.2f}%"
        )
    if metric.num_trades < gate.min_trades:
        failures.append(f"trades {metric.num_trades} < min {gate.min_trades}")
    if metric.max_drawdown > gate.max_drawdown:
        failures.append(
            f"max drawdown {metric.max_drawdown * 100:.2f}% "
            f"> cap {gate.max_drawdown * 100:.2f}%"
        )
    return len(failures) == 0, failures


def _risk_params_from_metric(
    metric: StrategyMetrics,
    *,
    stop_loss_pct: float,
    take_profit_pct: Optional[float],
    transaction_cost_pct: float,
) -> Tuple[float, Optional[float], float]:
    params = metric.parameters
    sl = float(params.get("_stop_loss_pct", stop_loss_pct))
    tp_raw = params.get("_take_profit_pct", take_profit_pct)
    tp = float(tp_raw) if tp_raw is not None else None
    cost = float(params.get("_transaction_cost_pct", transaction_cost_pct))
    return sl, tp, cost


def metrics_to_winner_summary(
    metric: StrategyMetrics,
    *,
    deployable: bool,
    stop_loss_pct: float,
    take_profit_pct: Optional[float],
    transaction_cost_pct: float,
) -> WinningStrategySummary:
    return WinningStrategySummary(
        strategy_name=metric.strategy_name,
        lookback=metric.lookback,
        historical_profit_ratio=metric.net_profit_ratio,
        parameters=dict(metric.parameters),
        profit_factor=metric.profit_factor,
        sharpe_ratio=metric.sharpe_ratio,
        max_drawdown=metric.max_drawdown,
        num_trades=metric.num_trades,
        deployable=deployable,
        stop_loss_pct=stop_loss_pct,
        take_profit_pct=take_profit_pct,
        transaction_cost_pct=transaction_cost_pct,
        train_profit_ratio=metric.train_net_profit_ratio,
        validate_profit_ratio=metric.validate_net_profit_ratio,
    )


def select_winner(
    metrics: List[StrategyMetrics],
    gate: WinnerGateConfig,
    *,
    stop_loss_pct: float,
    take_profit_pct: Optional[float],
    transaction_cost_pct: float,
    config: Optional[dict] = None,
) -> Tuple[Optional[WinningStrategySummary], List[str]]:
    """Pick best deployable metric or return rejection reasons for the best overall."""
    cfg = config or {}
    score = lambda m: metric_selection_score(m, cfg)

    if not metrics:
        return None, ["no strategy metrics evaluated"]

    best_overall = max(metrics, key=score)
    eligible = [m for m in metrics if evaluate_winner_gate(m, gate)[0]]

    if eligible:
        best = max(eligible, key=score)
        sl, tp, cost = _risk_params_from_metric(
            best,
            stop_loss_pct=stop_loss_pct,
            take_profit_pct=take_profit_pct,
            transaction_cost_pct=transaction_cost_pct,
        )
        return (
            metrics_to_winner_summary(
                best,
                deployable=True,
                stop_loss_pct=sl,
                take_profit_pct=tp,
                transaction_cost_pct=cost,
            ),
            [],
        )

    _, failures = evaluate_winner_gate(best_overall, gate)
    sl, tp, cost = _risk_params_from_metric(
        best_overall,
        stop_loss_pct=stop_loss_pct,
        take_profit_pct=take_profit_pct,
        transaction_cost_pct=transaction_cost_pct,
    )
    rejected = metrics_to_winner_summary(
        best_overall,
        deployable=False,
        stop_loss_pct=sl,
        take_profit_pct=tp,
        transaction_cost_pct=cost,
    )
    summary_lines = [
        f"best overall: {rejected.strategy_name} ({rejected.lookback}) "
        f"net={rejected.historical_profit_ratio * 100:.2f}%",
        *failures,
    ]
    return None, summary_lines
