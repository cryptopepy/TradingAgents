# TradingAgents/graph/setup.py

import threading
from typing import Any, Callable, Dict, List

from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode
from langgraph.types import Send

from tradingagents.agents import *
from tradingagents.agents.utils.agent_states import AgentState
from tradingagents.risk.guard import create_risk_guard_node

from .analyst_execution import AnalystExecutionPlan, build_analyst_execution_plan
from .conditional_logic import ConditionalLogic


def _wrap_with_semaphore(fn: Callable, semaphore: threading.Semaphore) -> Callable:
    """Limit concurrent analyst LLM invocations."""

    def wrapped(state):
        with semaphore:
            return fn(state)

    return wrapped


def create_analyst_join_node():
    """Fan-in barrier after parallel analyst branches; reset messages for research."""

    clear_messages = create_msg_delete()

    def analyst_join_node(state):
        return clear_messages(state)

    return analyst_join_node


class GraphSetup:
    """Handles the setup and configuration of the agent graph."""

    def __init__(
        self,
        quick_thinking_llm: Any,
        deep_thinking_llm: Any,
        tool_nodes: Dict[str, ToolNode],
        conditional_logic: ConditionalLogic,
        analyst_concurrency_limit: int = 1,
        risk_config: Dict[str, Any] | None = None,
    ):
        """Initialize with required components."""
        self.quick_thinking_llm = quick_thinking_llm
        self.deep_thinking_llm = deep_thinking_llm
        self.tool_nodes = tool_nodes
        self.conditional_logic = conditional_logic
        self.analyst_concurrency_limit = max(1, analyst_concurrency_limit)
        self.risk_config = risk_config or {}
        self._analyst_semaphore = threading.Semaphore(self.analyst_concurrency_limit)

    def _schedule_analysts(self, state: AgentState, plan: AnalystExecutionPlan) -> List[Send]:
        """Fan-out from START to each selected analyst in parallel."""
        return [Send(spec.agent_node, state) for spec in plan.specs]

    def setup_graph(
        self, selected_analysts=["market", "social", "news", "fundamentals"]
    ):
        """Set up and compile the agent workflow graph.

        Args:
            selected_analysts (list): List of analyst types to include. Options are:
                - "market": Market analyst
                - "social": Social media analyst
                - "news": News analyst
                - "fundamentals": Fundamentals analyst
        """
        plan = build_analyst_execution_plan(
            selected_analysts,
            concurrency_limit=self.analyst_concurrency_limit,
        )

        analyst_factories = {
            "market": lambda: create_market_analyst(self.quick_thinking_llm),
            "social": lambda: create_sentiment_analyst(self.quick_thinking_llm),
            "news": lambda: create_news_analyst(self.quick_thinking_llm),
            "fundamentals": lambda: create_fundamentals_analyst(self.quick_thinking_llm),
        }

        # Create researcher and manager nodes
        bull_researcher_node = create_bull_researcher(self.quick_thinking_llm)
        bear_researcher_node = create_bear_researcher(self.quick_thinking_llm)
        research_manager_node = create_research_manager(self.deep_thinking_llm)
        trader_node = create_trader(self.quick_thinking_llm)

        # Create risk analysis nodes
        aggressive_analyst = create_aggressive_debator(self.quick_thinking_llm)
        neutral_analyst = create_neutral_debator(self.quick_thinking_llm)
        conservative_analyst = create_conservative_debator(self.quick_thinking_llm)
        portfolio_manager_node = create_portfolio_manager(self.deep_thinking_llm)
        risk_guard_node = create_risk_guard_node(self.risk_config)

        # Create workflow
        workflow = StateGraph(AgentState)

        # Add analyst nodes to the graph (semaphore-limited)
        for spec in plan.specs:
            workflow.add_node(
                spec.agent_node,
                _wrap_with_semaphore(analyst_factories[spec.key](), self._analyst_semaphore),
            )
            workflow.add_node(spec.clear_node, create_msg_delete())
            workflow.add_node(spec.tool_node, self.tool_nodes[spec.key])

        workflow.add_node("Analyst Join", create_analyst_join_node())

        # Add other nodes
        workflow.add_node("Bull Researcher", bull_researcher_node)
        workflow.add_node("Bear Researcher", bear_researcher_node)
        workflow.add_node("Research Manager", research_manager_node)
        workflow.add_node("Trader", trader_node)
        workflow.add_node("Aggressive Analyst", aggressive_analyst)
        workflow.add_node("Neutral Analyst", neutral_analyst)
        workflow.add_node("Conservative Analyst", conservative_analyst)
        workflow.add_node("Portfolio Manager", portfolio_manager_node)
        workflow.add_node("Risk Guard", risk_guard_node)

        # Parallel fan-out from START to all selected analysts
        workflow.add_conditional_edges(
            START,
            lambda state: self._schedule_analysts(state, plan),
        )

        # Per-analyst tool loops; each branch fans in at Analyst Join
        for spec in plan.specs:
            workflow.add_conditional_edges(
                spec.agent_node,
                getattr(self.conditional_logic, f"should_continue_{spec.key}"),
                [spec.tool_node, spec.clear_node],
            )
            workflow.add_edge(spec.tool_node, spec.agent_node)
            workflow.add_edge(spec.clear_node, "Analyst Join")

        workflow.add_edge("Analyst Join", "Bull Researcher")

        # Add remaining edges
        workflow.add_conditional_edges(
            "Bull Researcher",
            self.conditional_logic.should_continue_debate,
            {
                "Bear Researcher": "Bear Researcher",
                "Research Manager": "Research Manager",
            },
        )
        workflow.add_conditional_edges(
            "Bear Researcher",
            self.conditional_logic.should_continue_debate,
            {
                "Bull Researcher": "Bull Researcher",
                "Research Manager": "Research Manager",
            },
        )
        workflow.add_edge("Research Manager", "Trader")
        workflow.add_edge("Trader", "Aggressive Analyst")
        workflow.add_conditional_edges(
            "Aggressive Analyst",
            self.conditional_logic.should_continue_risk_analysis,
            {
                "Conservative Analyst": "Conservative Analyst",
                "Portfolio Manager": "Portfolio Manager",
            },
        )
        workflow.add_conditional_edges(
            "Conservative Analyst",
            self.conditional_logic.should_continue_risk_analysis,
            {
                "Neutral Analyst": "Neutral Analyst",
                "Portfolio Manager": "Portfolio Manager",
            },
        )
        workflow.add_conditional_edges(
            "Neutral Analyst",
            self.conditional_logic.should_continue_risk_analysis,
            {
                "Aggressive Analyst": "Aggressive Analyst",
                "Portfolio Manager": "Portfolio Manager",
            },
        )

        workflow.add_edge("Portfolio Manager", "Risk Guard")
        workflow.add_edge("Risk Guard", END)

        return workflow
