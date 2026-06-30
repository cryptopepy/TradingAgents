"""Smart Trading runtime coordinator."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

from tradingagents.backtest.signal_filters import compute_atr
from tradingagents.simulator.smart_trading.guards import SmartTradingGuardState, validate_entry
from tradingagents.simulator.smart_trading.momentum import momentum_signal_from_closes
from tradingagents.simulator.smart_trading.profiles import EffectiveSmartConfig
from tradingagents.simulator.smart_trading.registry import get_cadence_plugin
from tradingagents.simulator.smart_trading.resolver import format_effective_summary, resolve_effective_config
from tradingagents.simulator.smart_trading.walk_forward_validate import validate_cadence_switch
from tradingagents.simulator.core import StrategySignal


class SmartTradingRuntime:
    """Session-scoped smart trading state and resolution."""

    def __init__(self, config: dict) -> None:
        self.config = config
        self.guards = SmartTradingGuardState()
        self._last_atr_pct: float = 0.01
        self._last_atr_percentile: float = 0.5
        self._bar_high: float = 0.0
        self._bar_low: float = 0.0
        self._price_history_1m: List[float] = []

    def is_enabled(self) -> bool:
        return bool(self.config.get("smart_trading_enabled", False))

    def update_atr_from_df(self, df: pd.DataFrame) -> None:
        if df is None or df.empty or "Close" not in df.columns:
            return
        atr = compute_atr(df)
        close = float(df["Close"].iloc[-1])
        if close > 0 and len(atr):
            val = float(atr.iloc[-1])
            self._last_atr_pct = val / close
            if len(atr) >= 20:
                recent = atr.dropna().tail(100)
                if len(recent) > 1:
                    rank = (recent < val).sum() / len(recent)
                    self._last_atr_percentile = float(rank)

    def resolve(
        self,
        leverage: float,
        *,
        enabled: Optional[bool] = None,
        cadence: Optional[str] = None,
        risk: Optional[str] = None,
    ) -> EffectiveSmartConfig:
        return resolve_effective_config(
            self.config,
            leverage=leverage,
            atr_pct=self._last_atr_pct,
            atr_percentile=self._last_atr_percentile,
            enabled=enabled,
            cadence=cadence,
            risk=risk,
        )

    def adjust_parameters(
        self,
        strategy_name: str,
        parameters: Dict[str, Any],
        effective: EffectiveSmartConfig,
    ) -> Dict[str, Any]:
        plugin = get_cadence_plugin()
        return plugin.adjust_strategy_parameters(strategy_name, parameters, effective)

    def check_entry_allowed(
        self,
        portfolio,
        asset: str,
        price: float,
        effective: EffectiveSmartConfig,
        now: datetime,
    ) -> tuple[bool, str, float]:
        chg_1m = 0.0
        if len(self._price_history_1m) >= 2:
            a, b = self._price_history_1m[-2], self._price_history_1m[-1]
            if a > 0:
                chg_1m = (b - a) / a * 100.0
        spike_thr = float(self.config.get("paper_spike_1m_loss_pct", 1.5))
        return validate_entry(
            self.guards,
            portfolio,
            asset,
            price,
            effective,
            now,
            price_change_1m_pct=chg_1m,
            spike_threshold_pct=spike_thr,
        )

    def record_price(self, price: float) -> None:
        self._price_history_1m.append(price)
        if len(self._price_history_1m) > 120:
            self._price_history_1m.pop(0)
        self._bar_high = max(self._bar_high or price, price)
        self._bar_low = min(self._bar_low or price, price)

    def reset_bar(self, price: float) -> None:
        self._bar_high = price
        self._bar_low = price

    def momentum_override(
        self,
        df: pd.DataFrame,
        base_signal: StrategySignal,
        effective: EffectiveSmartConfig,
        leverage: float,
    ) -> StrategySignal:
        if not effective.enabled or not effective.momentum_overlay:
            return base_signal
        if base_signal != StrategySignal.FLAT:
            return base_signal
        if df is None or "Close" not in df.columns:
            return base_signal
        thr = 0.10 if effective.cadence == "scalp" else 0.15
        mom = momentum_signal_from_closes(df["Close"], threshold_pct=thr)
        if mom is not None:
            return mom
        return base_signal

    def validate_cadence_change(
        self,
        symbol: str,
        strategy_name: str,
        parameters: dict,
        effective: EffectiveSmartConfig,
    ):
        return validate_cadence_switch(
            symbol,
            strategy_name,
            parameters,
            effective.signal_lookback,
            config=self.config,
            stop_loss_pct=effective.stop_loss_pct,
            take_profit_pct=effective.take_profit_pct,
        )

    def summary_line(self, effective: EffectiveSmartConfig) -> str:
        return format_effective_summary(effective)

    def break_even_pct(self, fee_bps: float, leverage: float) -> float:
        """Price move % needed to cover round-trip fees (leverage scales equity impact)."""
        round_trip = 2.0 * (fee_bps / 10_000.0)
        return round_trip / max(leverage, 1.0) * 100.0


def export_profile(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def import_profile(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))
