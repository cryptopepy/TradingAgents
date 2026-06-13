"""ATR-based stop sizing and per-symbol risk knob variations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

import pandas as pd

from .signal_filters import compute_atr


@dataclass(frozen=True)
class RiskVariant:
    """One risk/fee configuration to try during optimization."""

    stop_loss_pct: float
    take_profit_pct: Optional[float]
    transaction_cost_pct: float
    atr_stops: bool = True
    atr_sl_mult: float = 2.0
    atr_tp_mult: float = 3.5


def resolve_atr_stop_pcts(
    df: pd.DataFrame,
    bar_index: int,
    entry_price: float,
    config: dict,
    *,
    atr_sl_mult: float,
    atr_tp_mult: float,
    fallback_sl: float,
    fallback_tp: Optional[float],
) -> Tuple[float, float]:
    """Return (stop_loss_pct, take_profit_pct) as fractions of price from ATR at entry."""
    if entry_price <= 0:
        return fallback_sl, fallback_tp or fallback_sl * 2.0

    period = int(config.get("atr_period", 14))
    atr = compute_atr(df, period)
    atr_val = float(atr.iloc[bar_index]) if bar_index < len(atr) else float("nan")
    if pd.isna(atr_val) or atr_val <= 0:
        tp = fallback_tp if fallback_tp is not None else fallback_sl * 2.0
        return fallback_sl, tp

    sl_pct = (atr_val * atr_sl_mult) / entry_price
    tp_pct = (atr_val * atr_tp_mult) / entry_price
    min_pct = float(config.get("atr_stop_min_pct", 0.008))
    max_pct = float(config.get("atr_stop_max_pct", 0.06))
    sl_pct = float(max(min_pct, min(max_pct, sl_pct)))
    tp_pct = float(max(sl_pct * 1.5, min(max_pct * 1.5, tp_pct)))
    return sl_pct, tp_pct


def resolve_position_stop_pcts(
    df: pd.DataFrame,
    bar_index: int,
    entry_price: float,
    variant: RiskVariant,
    config: dict,
) -> Tuple[float, float]:
    """Effective SL/TP percentages for a new position."""
    tp_fallback = variant.take_profit_pct
    if variant.atr_stops and bool(config.get("atr_stops_enabled", True)):
        return resolve_atr_stop_pcts(
            df,
            bar_index,
            entry_price,
            config,
            atr_sl_mult=variant.atr_sl_mult,
            atr_tp_mult=variant.atr_tp_mult,
            fallback_sl=variant.stop_loss_pct,
            fallback_tp=tp_fallback,
        )
    sl = variant.stop_loss_pct
    tp = tp_fallback if tp_fallback is not None else sl * 2.0
    return sl, tp


def iter_risk_variants(
    config: dict,
    *,
    symbol: str,
    stop_loss_pct: float,
    take_profit_pct: Optional[float],
    transaction_cost_pct: float,
    is_alt: bool,
) -> List[RiskVariant]:
    """Knob variations: a few for majors, expanded grid for midsize alts."""
    cfg = config or {}
    base_tp = take_profit_pct if take_profit_pct is not None else stop_loss_pct * 2.0

    if cfg.get("optimize_risk_params"):
        combos: List[RiskVariant] = []
        for sl in (0.01, 0.015, 0.02):
            for tp_mult in (2.0, 3.0):
                for cost in (0.001, 0.002):
                    combos.append(
                        RiskVariant(sl, sl * tp_mult, cost, atr_stops=True, atr_sl_mult=2.0, atr_tp_mult=3.5)
                    )
        max_runs = int(cfg.get("optimize_risk_max_runs", 500))
        return combos[:max_runs]

    if is_alt and cfg.get("alt_expand_risk_variants", True):
        mult_pairs = [(1.5, 3.0), (2.0, 3.5), (2.5, 4.5), (3.0, 5.0)]
        costs = [transaction_cost_pct]
        alt_mult = float(cfg.get("paper_alt_fee_multiplier", 2.0))
        if alt_mult > 1.0:
            costs.append(transaction_cost_pct * alt_mult)
        costs = sorted(set(round(c, 6) for c in costs))
        return [
            RiskVariant(
                stop_loss_pct,
                base_tp,
                cost,
                atr_stops=bool(cfg.get("atr_stops_enabled", True)),
                atr_sl_mult=sl_m,
                atr_tp_mult=tp_m,
            )
            for sl_m, tp_m in mult_pairs
            for cost in costs
        ]

    if not cfg.get("major_risk_variants_enabled", True):
        return [
            RiskVariant(
                stop_loss_pct,
                base_tp,
                transaction_cost_pct,
                atr_stops=bool(cfg.get("atr_stops_enabled", True)),
            )
        ]

    return [
        RiskVariant(
            0.015,
            0.03,
            transaction_cost_pct,
            atr_stops=bool(cfg.get("atr_stops_enabled", True)),
            atr_sl_mult=1.5,
            atr_tp_mult=3.0,
        ),
        RiskVariant(
            stop_loss_pct,
            base_tp,
            transaction_cost_pct,
            atr_stops=bool(cfg.get("atr_stops_enabled", True)),
            atr_sl_mult=2.0,
            atr_tp_mult=3.5,
        ),
        RiskVariant(
            0.025,
            0.05,
            transaction_cost_pct,
            atr_stops=bool(cfg.get("atr_stops_enabled", True)),
            atr_sl_mult=2.5,
            atr_tp_mult=4.5,
        ),
    ]


def risk_variant_from_metric(
    metric,
    *,
    stop_loss_pct: float,
    take_profit_pct: Optional[float],
    transaction_cost_pct: float,
) -> RiskVariant:
    """Rebuild a RiskVariant from stored optimization parameters."""
    params = metric.parameters
    tp_raw = params.get("_take_profit_pct", take_profit_pct)
    return RiskVariant(
        stop_loss_pct=float(params.get("_stop_loss_pct", stop_loss_pct)),
        take_profit_pct=float(tp_raw) if tp_raw is not None else None,
        transaction_cost_pct=float(params.get("_transaction_cost_pct", transaction_cost_pct)),
        atr_stops=bool(params.get("_atr_stops_enabled", True)),
        atr_sl_mult=float(params.get("_atr_sl_mult", 2.0)),
        atr_tp_mult=float(params.get("_atr_tp_mult", 3.5)),
    )
