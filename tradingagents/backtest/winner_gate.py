"""Winner selection gates for strategy optimization."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from .schemas import StrategyMetrics, WinningStrategySummary

LOOKBACK_HOURS: Dict[str, float] = {
    "8h": 8.0,
    "24h": 24.0,
    "7d": 168.0,
}

LOOKBACK_RANK: Dict[str, int] = {
    "8h": 1,
    "24h": 2,
    "7d": 3,
}

DEFAULT_HORIZON_WEIGHTS: Dict[str, float] = {
    "8h": 0.35,
    "24h": 1.0,
    "7d": 2.5,
}

LONG_HORIZONS = frozenset({"24h", "7d"})


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


def horizon_weight(lookback: str, config: dict) -> float:
    """Relative importance of a lookback window in pooled winner scoring."""
    weights = config.get("winner_horizon_weights") or DEFAULT_HORIZON_WEIGHTS
    return float(weights.get(lookback, DEFAULT_HORIZON_WEIGHTS.get(lookback, 1.0)))


def time_normalized_return(metric: StrategyMetrics) -> float:
    """Scale net return to a 24h-equivalent rate for fair cross-horizon comparison."""
    hours = LOOKBACK_HOURS.get(metric.lookback, 24.0)
    if hours <= 0:
        return float(metric.net_profit_ratio)
    return float(metric.net_profit_ratio) * (24.0 / hours)


def metric_selection_score(metric: StrategyMetrics, config: dict) -> float:
    """Ranking key for winner selection (higher is better)."""
    mode = str(config.get("winner_score_mode", "net_profit")).strip().lower()
    if mode == "composite":
        pf = min(float(metric.profit_factor), 3.0)
        base = float(metric.net_profit_ratio) * pf / (1.0 + float(metric.max_drawdown))
    else:
        base = float(metric.net_profit_ratio)

    norm = time_normalized_return(metric)
    win_rate_boost = 1.0 + min(float(metric.win_rate) / 100.0, 1.0) * 0.25
    blended = (0.6 * base + 0.4 * norm) * win_rate_boost
    return blended * horizon_weight(metric.lookback, config)


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


def _select_winner_flat(
    metrics: List[StrategyMetrics],
    gate: WinnerGateConfig,
    *,
    stop_loss_pct: float,
    take_profit_pct: Optional[float],
    transaction_cost_pct: float,
    config: dict,
) -> Tuple[Optional[WinningStrategySummary], List[str]]:
    """Legacy flat pool: best single strategy×horizon row."""
    score = lambda m: metric_selection_score(m, config)

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


def _pick_representative_metric(
    passing: List[StrategyMetrics],
    config: dict,
) -> StrategyMetrics:
    """Prefer the longest lookback with solid risk-adjusted performance."""
    score = lambda m: metric_selection_score(m, config)
    return max(
        passing,
        key=lambda m: (LOOKBACK_RANK.get(m.lookback, 0), score(m)),
    )


def _select_winner_multi_horizon(
    metrics: List[StrategyMetrics],
    gate: WinnerGateConfig,
    *,
    stop_loss_pct: float,
    take_profit_pct: Optional[float],
    transaction_cost_pct: float,
    config: dict,
) -> Tuple[Optional[WinningStrategySummary], List[str]]:
    """Pool per-strategy scores across horizons; require longer-horizon confirmation."""
    require_long = bool(config.get("winner_require_long_horizon", True))
    by_strategy: Dict[str, List[StrategyMetrics]] = defaultdict(list)
    for metric in metrics:
        by_strategy[metric.strategy_name].append(metric)

    candidates: List[Tuple[float, StrategyMetrics]] = []
    for rows in by_strategy.values():
        passing = [m for m in rows if evaluate_winner_gate(m, gate)[0]]
        if not passing:
            continue

        if require_long:
            long_passing = [
                m
                for m in passing
                if m.lookback in LONG_HORIZONS
                and m.net_profit_ratio > gate.min_net_profit_ratio
            ]
            if not long_passing:
                continue

        pooled_score = sum(metric_selection_score(m, config) for m in passing)
        representative = _pick_representative_metric(passing, config)
        candidates.append((pooled_score, representative))

    if candidates:
        _, best_metric = max(candidates, key=lambda item: item[0])
        sl, tp, cost = _risk_params_from_metric(
            best_metric,
            stop_loss_pct=stop_loss_pct,
            take_profit_pct=take_profit_pct,
            transaction_cost_pct=transaction_cost_pct,
        )
        return (
            metrics_to_winner_summary(
                best_metric,
                deployable=True,
                stop_loss_pct=sl,
                take_profit_pct=tp,
                transaction_cost_pct=cost,
            ),
            [],
        )

    best_overall = max(metrics, key=lambda m: metric_selection_score(m, config))
    _, failures = evaluate_winner_gate(best_overall, gate)
    summary_lines = [
        f"best overall: {best_overall.strategy_name} ({best_overall.lookback}) "
        f"net={best_overall.net_profit_ratio * 100:.2f}%",
        *failures,
    ]
    if require_long:
        summary_lines.append(
            "no strategy passed long-horizon confirmation (profitable 24h or 7d required)"
        )
    return None, summary_lines


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
    if not metrics:
        return None, ["no strategy metrics evaluated"]

    mode = str(cfg.get("winner_selection_mode", "multi_horizon")).strip().lower()
    if mode == "multi_horizon":
        return _select_winner_multi_horizon(
            metrics,
            gate,
            stop_loss_pct=stop_loss_pct,
            take_profit_pct=take_profit_pct,
            transaction_cost_pct=transaction_cost_pct,
            config=cfg,
        )

    return _select_winner_flat(
        metrics,
        gate,
        stop_loss_pct=stop_loss_pct,
        take_profit_pct=take_profit_pct,
        transaction_cost_pct=transaction_cost_pct,
        config=cfg,
    )
