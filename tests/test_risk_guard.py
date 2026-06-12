"""Tests for programmatic risk guard."""

import pytest

from tradingagents.risk.guard import apply_risk_guard, create_risk_guard_node


def _state(trader_plan: str, final: str = "**Rating**: Buy\n\nBuy."):
    return {
        "company_of_interest": "NVDA",
        "trade_date": "2026-01-10",
        "trader_investment_plan": trader_plan,
        "final_trade_decision": final,
        "risk_debate_state": {"judge_decision": final},
    }


@pytest.mark.unit
class TestRiskGuard:
    def test_approves_when_within_limits(self):
        state = _state("**Position Sizing**: 5% of portfolio")
        result = apply_risk_guard(
            state,
            {"max_position_pct": 10.0, "max_concentration_pct": 15.0, "max_var_pct": 5.0},
        )
        assert result.approved is True
        assert not result.violations

    def test_vetoes_oversized_position(self):
        state = _state("**Position Sizing**: 20% of portfolio\n**Action**: Buy")
        result = apply_risk_guard(
            state,
            {"max_position_pct": 10.0, "max_concentration_pct": 15.0, "max_var_pct": 5.0},
        )
        assert result.approved is False
        assert result.action == "hold"
        assert result.adjusted_decision is not None
        assert "**Rating**: Hold" in result.adjusted_decision

    def test_node_overrides_final_decision(self):
        state = _state("**Position Sizing**: 25% of portfolio")
        node = create_risk_guard_node({"max_position_pct": 10.0, "max_concentration_pct": 15.0, "max_var_pct": 5.0})
        updates = node(state)
        assert "final_trade_decision" in updates
        assert "**Rating**: Hold" in updates["final_trade_decision"]
