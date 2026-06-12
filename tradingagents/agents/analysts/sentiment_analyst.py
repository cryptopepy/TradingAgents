"""Crypto sentiment analyst — LunarCrush, crypto news, Reddit crypto communities."""

from datetime import datetime, timedelta

from langchain_core.messages import AIMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from tradingagents.agents.schemas import SentimentReport, render_sentiment_report
from tradingagents.agents.utils.agent_utils import (
    get_instrument_context_from_state,
    get_language_instruction,
    get_news,
    get_sentiment,
)
from tradingagents.agents.utils.structured import (
    bind_structured,
    invoke_structured_or_freetext,
)
from tradingagents.dataflows.lunarcrush import fetch_lunarcrush_sentiment
from tradingagents.dataflows.reddit import fetch_reddit_posts


def _seven_days_back(trade_date: str) -> str:
    return (datetime.strptime(trade_date, "%Y-%m-%d") - timedelta(days=7)).strftime("%Y-%m-%d")


def create_sentiment_analyst(llm):
    structured_llm = bind_structured(llm, SentimentReport, "Sentiment Analyst")

    def sentiment_analyst_node(state):
        ticker = state["company_of_interest"]
        end_date = state["trade_date"]
        start_date = _seven_days_back(end_date)
        instrument_context = get_instrument_context_from_state(state)

        news_block = get_news.func(ticker, start_date, end_date)
        lunarcrush_block = fetch_lunarcrush_sentiment(ticker, trade_date=end_date)
        reddit_block = fetch_reddit_posts(ticker, trade_date=end_date)

        system_message = _build_system_message(
            ticker=ticker,
            start_date=start_date,
            end_date=end_date,
            news_block=news_block,
            lunarcrush_block=lunarcrush_block,
            reddit_block=reddit_block,
        )

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are a helpful AI assistant, collaborating with other assistants."
                    " If you or any other assistant has the FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL** or deliverable,"
                    " prefix your response with FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL** so the team knows to stop."
                    "\n{system_message}\n"
                    "For your reference, the current date is {current_date}. {instrument_context}",
                ),
                MessagesPlaceholder(variable_name="messages"),
            ]
        )

        prompt = prompt.partial(system_message=system_message)
        prompt = prompt.partial(current_date=end_date)
        prompt = prompt.partial(instrument_context=instrument_context)

        formatted_messages = prompt.format_messages(messages=state["messages"])
        report_text = invoke_structured_or_freetext(
            structured_llm,
            llm,
            formatted_messages,
            render_sentiment_report,
            "Sentiment Analyst",
        )

        return {
            "messages": [AIMessage(content=report_text)],
            "sentiment_report": report_text,
        }

    return sentiment_analyst_node


def _build_system_message(
    *,
    ticker: str,
    start_date: str,
    end_date: str,
    news_block: str,
    lunarcrush_block: str,
    reddit_block: str,
) -> str:
    return f"""You are a crypto market sentiment analyst for {ticker} ({start_date} to {end_date}).

## Data sources (pre-fetched)

### Crypto news headlines
<start_of_news>
{news_block}
<end_of_news>

### LunarCrush social metrics
<start_of_lunarcrush>
{lunarcrush_block}
<end_of_lunarcrush>

### Reddit — r/CryptoCurrency, r/Bitcoin, r/ethereum
<start_of_reddit>
{reddit_block}
<end_of_reddit>

## Analysis guidelines
1. Weight LunarCrush galaxy score and social volume when available.
2. Cross-check news narrative vs social sentiment for divergences.
3. Reddit engagement (upvotes/comments) signals community attention.
4. Flag NO_DATA_AVAILABLE blocks explicitly in confidence scoring.
5. Crypto sentiment is 24/7 — no market-close effects.

## Output fields
- **overall_band**: Bullish / Mildly Bullish / Neutral / Mixed / Mildly Bearish / Bearish
- **overall_score**: 0–10 (5 = neutral)
- **confidence**: low / medium / high
- **narrative**: source breakdown + summary table

{get_language_instruction()}"""


def create_social_media_analyst(llm):
    import warnings
    warnings.warn(
        "create_social_media_analyst is deprecated; use create_sentiment_analyst.",
        DeprecationWarning,
        stacklevel=2,
    )
    return create_sentiment_analyst(llm)
