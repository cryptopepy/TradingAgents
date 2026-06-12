from langchain_core.tools import tool
from typing import Annotated
from tradingagents.dataflows.interface import route_to_vendor


@tool
def get_indicators(
    symbol: Annotated[str, "crypto pair e.g. BTC/USDT"],
    indicator: Annotated[str, "technical indicator e.g. rsi, macd"],
    curr_date: Annotated[str, "analysis date YYYY-mm-dd"],
    look_back_days: Annotated[int, "how many days to look back"] = 30,
) -> str:
    """
    Retrieve a technical indicator computed on crypto OHLCV candles.
    Call once per indicator name.
    """
    indicators = [i.strip().lower() for i in indicator.split(",") if i.strip()]
    results = []
    for ind in indicators:
        try:
            results.append(
                route_to_vendor("get_indicators", symbol, ind, curr_date, look_back_days)
            )
        except ValueError as e:
            results.append(str(e))
    return "\n\n".join(results)
