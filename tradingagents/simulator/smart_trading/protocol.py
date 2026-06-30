"""Plugin protocol for custom Smart Trading cadences."""

from __future__ import annotations

from typing import Any, Dict, Protocol

from tradingagents.backtest.portfolio import VirtualPortfolio

from .profiles import EffectiveSmartConfig


class CadencePlugin(Protocol):
    """Extend or replace default smart-trading behavior."""

    name: str

    def adjust_strategy_parameters(
        self,
        strategy_name: str,
        parameters: Dict[str, Any],
        effective: EffectiveSmartConfig,
    ) -> Dict[str, Any]: ...

    def validate_entry(
        self,
        portfolio: VirtualPortfolio,
        asset: str,
        price: float,
        leverage: float,
        effective: EffectiveSmartConfig,
    ) -> tuple[bool, str]: ...

    def on_trade_completed(self, action: str, effective: EffectiveSmartConfig) -> None: ...
