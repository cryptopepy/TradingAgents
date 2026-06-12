"""Post-Portfolio-Manager risk guard and veto layer.

Validates stop-loss distance vs ATR, position sizing caps, and simple
concentration / VaR heuristics. On violation the guard overrides the PM
decision to Hold or scales down exposure before state is persisted.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from tradingagents.agents.utils.rating import parse_rating
from tradingagents.dataflows.stockstats_utils import StockstatsUtils


@dataclass
class RiskGuardResult:
    """Outcome of programmatic risk validation."""

    approved: bool
    violations: List[str] = field(default_factory=list)
    adjusted_decision: Optional[str] = None
    action: str = "approve"  # approve | hold | scale_down


def _parse_percent(text: str) -> Optional[float]:
    """Extract the first percentage literal from text (e.g. '6% of portfolio')."""
    if not text:
        return None
    match = re.search(r"(\d+(?:\.\d+)?)\s*%", text)
    if match:
        return float(match.group(1))
    return None


def _parse_stop_and_entry(trader_plan: str) -> tuple[Optional[float], Optional[float]]:
    """Heuristically parse stop-loss and entry from trader markdown."""
    entry = stop = None
    for line in trader_plan.splitlines():
        lower = line.lower()
        if "stop loss" in lower or "stop-loss" in lower:
            nums = re.findall(r"(\d+(?:\.\d+)?)", line)
            if nums:
                stop = float(nums[-1])
        if "entry price" in lower:
            nums = re.findall(r"(\d+(?:\.\d+)?)", line)
            if nums:
                entry = float(nums[-1])
    return entry, stop


def _fetch_atr(symbol: str, trade_date: str) -> Optional[float]:
    try:
        raw = StockstatsUtils.get_stock_stats(symbol, "atr", trade_date)
        if isinstance(raw, (int, float)):
            return float(raw)
        if isinstance(raw, str) and raw.replace(".", "", 1).isdigit():
            return float(raw)
    except Exception:
        return None
    return None


def apply_risk_guard(state: Dict[str, Any], config: Dict[str, Any]) -> RiskGuardResult:
    """Validate PM output against mechanical risk constraints."""
    violations: List[str] = []
    ticker = state.get("company_of_interest", "")
    trade_date = state.get("trade_date", "")
    trader_plan = state.get("trader_investment_plan", "") or ""
    final_decision = state.get("final_trade_decision", "") or ""

    max_stop_atr = float(config.get("max_stop_atr_multiple", 3.0))
    max_position_pct = float(config.get("max_position_pct", 10.0))
    max_var_pct = float(config.get("max_var_pct", 5.0))
    max_concentration_pct = float(config.get("max_concentration_pct", 15.0))

    entry, stop = _parse_stop_and_entry(trader_plan)
    if entry is not None and stop is not None and entry > 0:
        atr = _fetch_atr(ticker, trade_date)
        if atr and atr > 0:
            stop_distance = abs(entry - stop)
            allowed = max_stop_atr * atr
            if stop_distance > allowed:
                violations.append(
                    f"Stop distance {stop_distance:.2f} exceeds "
                    f"{max_stop_atr}×ATR ({allowed:.2f})"
                )

    position_pct = _parse_percent(trader_plan)
    if position_pct is not None and position_pct > max_position_pct:
        violations.append(
            f"Position size {position_pct:.1f}% exceeds limit {max_position_pct:.1f}%"
        )

    # Simple VaR proxy: position% × assumed daily vol (2%) annualized heuristic
    if position_pct is not None:
        assumed_daily_vol = float(config.get("assumed_daily_vol_pct", 2.0))
        var_proxy = position_pct * assumed_daily_vol / 100.0
        if var_proxy * 100 > max_var_pct:
            violations.append(
                f"Estimated VaR proxy {var_proxy * 100:.2f}% exceeds {max_var_pct:.1f}%"
            )
        if position_pct > max_concentration_pct:
            violations.append(
                f"Concentration {position_pct:.1f}% exceeds {max_concentration_pct:.1f}%"
            )

    if not violations:
        return RiskGuardResult(approved=True, violations=[], action="approve")

    rating = parse_rating(final_decision)
    if rating in ("Buy", "Overweight"):
        scaled_pct = min(position_pct or max_position_pct, max_position_pct * 0.5)
        adjusted = (
            f"**Rating**: Hold\n\n"
            f"**Executive Summary**: Risk guard veto — position scaled to Hold pending "
            f"manual review. Proposed sizing would have been reduced to ~{scaled_pct:.1f}%.\n\n"
            f"**Investment Thesis**: Programmatic risk checks failed: "
            f"{'; '.join(violations)}. Original rating was {rating}.\n\n"
            f"<!-- risk-guard-veto: hold -->"
        )
        return RiskGuardResult(
            approved=False,
            violations=violations,
            adjusted_decision=adjusted,
            action="hold",
        )

    adjusted = (
        f"{final_decision.rstrip()}\n\n"
        f"**Risk Guard Notice**: {len(violations)} constraint(s) flagged — "
        f"{'; '.join(violations)}"
    )
    return RiskGuardResult(
        approved=False,
        violations=violations,
        adjusted_decision=adjusted,
        action="scale_down",
    )


def create_risk_guard_node(config: Dict[str, Any] | None = None):
    """LangGraph node factory: enforce risk guard after Portfolio Manager."""

    risk_config = config or {}

    def risk_guard_node(state: Dict[str, Any]) -> Dict[str, Any]:
        result = apply_risk_guard(state, risk_config)
        if result.approved or not result.adjusted_decision:
            return {}

        updates: Dict[str, Any] = {"final_trade_decision": result.adjusted_decision}
        risk_state = dict(state.get("risk_debate_state") or {})
        risk_state["judge_decision"] = result.adjusted_decision
        updates["risk_debate_state"] = risk_state
        return updates

    return risk_guard_node
