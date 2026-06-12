"""End-to-end integration tests for the unified propagate() path."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.trading_graph import TradingAgentsGraph


def _minimal_final_state(ticker: str = "NVDA", trade_date: str = "2026-01-10") -> dict:
    return {
        "final_trade_decision": "**Rating**: Hold\n\n**Executive Summary**: Wait.\n\n**Investment Thesis**: Balanced.",
        "company_of_interest": ticker,
        "trade_date": trade_date,
        "market_report": "Market ok.",
        "sentiment_report": "",
        "news_report": "",
        "fundamentals_report": "",
        "investment_debate_state": {
            "bull_history": "bull",
            "bear_history": "bear",
            "history": "history",
            "current_response": "Bull",
            "judge_decision": "**Recommendation**: Hold",
            "count": 2,
        },
        "investment_plan": "**Recommendation**: Hold",
        "trader_investment_plan": "**Action**: Hold\n\n**Reasoning**: Flat.",
        "risk_debate_state": {
            "aggressive_history": "agg",
            "conservative_history": "con",
            "neutral_history": "neu",
            "history": "risk history",
            "judge_decision": "**Rating**: Hold",
            "current_aggressive_response": "",
            "current_conservative_response": "",
            "current_neutral_response": "",
            "count": 3,
            "latest_speaker": "Neutral",
        },
        "messages": [],
        "past_context": "Prior NVDA lesson.",
    }


@pytest.mark.unit
class TestPropagateUnifiedPath:
    def test_propagate_stream_callback_and_memory_log(self, tmp_path, mock_llm_client):
        config = DEFAULT_CONFIG.copy()
        config["results_dir"] = str(tmp_path / "results")
        config["data_cache_dir"] = str(tmp_path / "cache")
        config["memory_log_path"] = str(tmp_path / "memory.md")

        chunks = []
        final_state = _minimal_final_state()

        graph = TradingAgentsGraph(
            selected_analysts=["market"],
            config=config,
            debug=False,
            callbacks=[],
        )

        def on_chunk(chunk):
            chunks.append(chunk)

        stream_chunks = [final_state]

        def fake_stream(init_state, **kwargs):
            for chunk in stream_chunks:
                yield chunk

        with patch.object(graph.graph, "stream", side_effect=fake_stream):
            state, signal = graph.propagate(
                "NVDA",
                "2026-01-10",
                stream_callback=on_chunk,
                callbacks=[MagicMock()],
            )

        assert signal == "Hold"
        assert state["final_trade_decision"].startswith("**Rating**")
        assert len(chunks) == 1

        entries = graph.memory_log.load_entries()
        assert len(entries) == 1
        assert entries[0]["ticker"] == "NVDA"
        assert entries[0]["pending"] is True

        log_dir = Path(config["results_dir"]) / "NVDA" / "TradingAgentsStrategy_logs"
        log_file = log_dir / "full_states_log_2026-01-10.json"
        assert log_file.exists()
        payload = json.loads(log_file.read_text(encoding="utf-8"))
        assert payload["company_of_interest"] == "NVDA"
        assert payload["market_report"] == "Market ok."

    def test_graph_has_parallel_join_and_risk_guard(self, mock_llm_client):
        graph = TradingAgentsGraph(
            selected_analysts=["market", "news"],
            config=DEFAULT_CONFIG.copy(),
        )
        node_names = set(graph.workflow.nodes.keys())
        assert "Analyst Join" in node_names
        assert "Risk Guard" in node_names
