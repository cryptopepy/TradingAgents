from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from tradingagents.agents.utils.agent_utils import (
    get_instrument_context_from_state,
    get_indicators,
    get_language_instruction,
    get_crypto_ohlcv,
    get_verified_market_snapshot,
    get_perps_data,
)


def create_market_analyst(llm):

    def market_analyst_node(state):
        current_date = state["trade_date"]
        instrument_context = get_instrument_context_from_state(state)

        tools = [
            get_crypto_ohlcv,
            get_indicators,
            get_perps_data,
            get_verified_market_snapshot,
        ]

        system_message = (
            """You are a crypto market analyst covering 24/7 perpetual and spot markets.

Your focus areas:
- **Perpetuals**: funding rates, open interest, basis vs spot (use get_perps_data)
- **Technicals**: RSI, MACD, Bollinger, ATR on crypto OHLCV (use get_crypto_ohlcv then get_indicators)
- **Market structure**: liquidity regimes, volatility clusters, weekend vs weekday behavior
- **Derivatives context**: when funding is extreme, flag potential squeeze/reset risk

Available indicators (call get_indicators once per name):
- close_50_sma, close_200_sma, close_10_ema — trend
- macd, macds, macdh — momentum
- rsi — overbought/oversold (70/30; can stay extreme in trends)
- boll, boll_ub, boll_lb, atr — volatility bands and stop placement
- vwma — volume-weighted trend confirmation

Workflow: call get_crypto_ohlcv first, then get_indicators for up to 8 complementary indicators.
Call get_perps_data for funding/OI. Call get_verified_market_snapshot before final numeric claims.

Crypto trades continuously — do not cite market holidays or session gaps. Flag when order-book depth
or liquidation data is unavailable rather than inventing figures.

Write a detailed report with actionable levels and risk notes."""
            + """ Append a Markdown summary table at the end."""
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
            "market_report": report,
        }

    return market_analyst_node
