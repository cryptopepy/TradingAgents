from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from tradingagents.agents.utils.agent_utils import (
    get_instrument_context_from_state,
    get_fundamentals,
    get_onchain_metrics,
    get_tokenomics,
    get_language_instruction,
)


def create_fundamentals_analyst(llm):
    def fundamentals_analyst_node(state):
        current_date = state["trade_date"]
        instrument_context = get_instrument_context_from_state(state)

        tools = [
            get_fundamentals,
            get_onchain_metrics,
            get_tokenomics,
        ]

        system_message = (
            "You are a crypto fundamentals researcher. Analyze on-chain and token-level metrics — "
            "NOT equity fundamentals (no P/E, EPS, balance sheets, or SEC filings).\n\n"
            "Focus on:\n"
            "- **Tokenomics**: circulating/total/max supply, FDV, MC/FDV ratio (get_tokenomics)\n"
            "- **Market structure**: market cap rank, volume, category positioning (get_fundamentals)\n"
            "- **On-chain**: TVL, chain activity, gas/burn where relevant (get_onchain_metrics)\n"
            "- **Protocol revenue / emissions**: token unlock schedules when data is available\n\n"
            "Be explicit when TVL, active addresses, or protocol revenue data is unavailable. "
            "Do not fabricate on-chain figures."
            + " Append a Markdown summary table at the end."
            + get_language_instruction()
        )

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are a helpful AI assistant, collaborating with other assistants."
                    " Use the provided tools to progress towards answering the question."
                    " If you are unable to fully answer, that's OK; another assistant with different tools"
                    " will help where you left off. Execute what you can to make progress."
                    " If you or any other assistant has the FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL** or deliverable,"
                    " prefix your response with FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL** so the team knows to stop."
                    " You have access to the following tools: {tool_names}.\n{system_message}"
                    "For your reference, the current date is {current_date}. {instrument_context}",
                ),
                MessagesPlaceholder(variable_name="messages"),
            ]
        )

        prompt = prompt.partial(system_message=system_message)
        prompt = prompt.partial(tool_names=", ".join([tool.name for tool in tools]))
        prompt = prompt.partial(current_date=current_date)
        prompt = prompt.partial(instrument_context=instrument_context)

        chain = prompt | llm.bind_tools(tools)
        result = chain.invoke(state["messages"])

        report = ""
        if len(result.tool_calls) == 0:
            report = result.content

        return {
            "messages": [result],
            "fundamentals_report": report,
        }

    return fundamentals_analyst_node
