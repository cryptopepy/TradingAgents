"""Pydantic schemas for backtest optimization results."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class StrategyMetrics(BaseModel):
    """Performance metrics for a single strategy run."""

    strategy_name: str
    lookback: str
    parameters: Dict[str, Any] = Field(default_factory=dict)
    profit_factor: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0
    net_profit_ratio: float = 0.0
    num_trades: int = 0
    win_rate: float = 0.0
    notes: List[str] = Field(default_factory=list)


class WinningStrategySummary(BaseModel):
    """Best strategy selected across all horizons."""

    strategy_name: str
    lookback: str
    historical_profit_ratio: float
    parameters: Dict[str, Any] = Field(default_factory=dict)
    profit_factor: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0
    num_trades: int = 0
    deployable: bool = True
    stop_loss_pct: float = 0.02
    take_profit_pct: Optional[float] = None
    transaction_cost_pct: float = 0.001


class OptimizationResult(BaseModel):
    """Full optimization output for a symbol and end date."""

    symbol: str
    end_date: str
    results: List[StrategyMetrics] = Field(default_factory=list)
    winner: Optional[WinningStrategySummary] = None
    deployable: bool = False
    gate_failures: List[str] = Field(default_factory=list)
    live_price: Optional[float] = None
    paper_signal: Optional[str] = None
    warnings: List[str] = Field(default_factory=list)
