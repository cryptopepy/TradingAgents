"""Default cadence plugin — RSI/EMA param adjust + entry validation."""

from __future__ import annotations

from typing import Any, Dict

from tradingagents.backtest.portfolio import VirtualPortfolio

from .profiles import EffectiveSmartConfig, TradingCadenceProfile, CADENCE_PRESETS, TradingCadence
from .resolver import adjust_strategy_parameters


class DefaultCadencePlugin:
    name = "default"

    def adjust_strategy_parameters(
        self,
        strategy_name: str,
        parameters: Dict[str, Any],
        effective: EffectiveSmartConfig,
    ) -> Dict[str, Any]:
        if not effective.enabled:
            return dict(parameters or {})
        try:
            cadence = TradingCadence(effective.cadence)
            if effective.adaptive_resolved_cadence:
                cadence = TradingCadence(effective.adaptive_resolved_cadence)
        except ValueError:
            return dict(parameters or {})
        profile = CADENCE_PRESETS.get(cadence)
        if profile is None:
            return dict(parameters or {})
        return adjust_strategy_parameters(strategy_name, parameters, profile)

    def validate_entry(
        self,
        portfolio: VirtualPortfolio,
        asset: str,
        price: float,
        leverage: float,
        effective: EffectiveSmartConfig,
    ) -> tuple[bool, str]:
        return True, ""

    def on_trade_completed(self, action: str, effective: EffectiveSmartConfig) -> None:
        pass
