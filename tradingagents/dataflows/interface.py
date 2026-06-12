from typing import Annotated

from .binance import get_binance_ohlcv_csv
from .coingecko import get_crypto_fundamentals, get_tokenomics
from .crypto_candles import get_crypto_indicators_window
from .crypto_news import get_crypto_global_news, get_crypto_news
from .cryptocompare import get_cryptocompare_ohlcv_csv
from .lunarcrush import fetch_lunarcrush_sentiment
from .onchain_metrics import get_onchain_metrics
from .perps_data import get_perps_snapshot
from .symbol_utils import NoMarketDataError
from .config import get_config

TOOLS_CATEGORIES = {
    "core_crypto_apis": {
        "description": "Crypto OHLCV price data",
        "tools": ["get_crypto_ohlcv"],
    },
    "technical_indicators": {
        "description": "Technical analysis indicators on crypto candles",
        "tools": ["get_indicators"],
    },
    "fundamental_data": {
        "description": "On-chain and token fundamentals",
        "tools": ["get_fundamentals", "get_onchain_metrics", "get_tokenomics"],
    },
    "news_data": {
        "description": "Crypto news and sentiment",
        "tools": ["get_news", "get_global_news", "get_sentiment", "get_perps_data"],
    },
}

VENDOR_LIST = [
    "binance",
    "coingecko",
    "cryptocompare",
    "lunarcrush",
]

VENDOR_METHODS = {
    "get_crypto_ohlcv": {
        "binance": get_binance_ohlcv_csv,
        "cryptocompare": get_cryptocompare_ohlcv_csv,
    },
    "get_indicators": {
        "binance": get_crypto_indicators_window,
        "cryptocompare": get_crypto_indicators_window,
    },
    "get_fundamentals": {
        "coingecko": get_crypto_fundamentals,
    },
    "get_onchain_metrics": {
        "coingecko": get_onchain_metrics,
    },
    "get_tokenomics": {
        "coingecko": get_tokenomics,
    },
    "get_news": {
        "cryptocompare": get_crypto_news,
        "coingecko": get_crypto_news,
    },
    "get_global_news": {
        "cryptocompare": get_crypto_global_news,
    },
    "get_sentiment": {
        "lunarcrush": fetch_lunarcrush_sentiment,
    },
    "get_perps_data": {
        "binance": get_perps_snapshot,
    },
}


def get_category_for_method(method: str) -> str:
    for category, info in TOOLS_CATEGORIES.items():
        if method in info["tools"]:
            return category
    raise ValueError(f"Method '{method}' not found in any category")


def get_vendor(category: str, method: str | None = None) -> str:
    config = get_config()
    if method:
        tool_vendors = config.get("tool_vendors", {})
        if method in tool_vendors:
            return tool_vendors[method]
    return config.get("data_vendors", {}).get(category, "binance")


def route_to_vendor(method: str, *args, **kwargs):
    """Route method calls to appropriate crypto vendor with fallback support."""
    category = get_category_for_method(method)
    vendor_config = get_vendor(category, method)
    primary_vendors = [v.strip() for v in vendor_config.split(",")]

    if method not in VENDOR_METHODS:
        raise ValueError(f"Method '{method}' not supported")

    all_available_vendors = list(VENDOR_METHODS[method].keys())
    fallback_vendors = primary_vendors.copy()
    for vendor in all_available_vendors:
        if vendor not in fallback_vendors:
            fallback_vendors.append(vendor)

    last_no_data: NoMarketDataError | None = None
    first_error: Exception | None = None
    for vendor in fallback_vendors:
        if vendor not in VENDOR_METHODS[method]:
            continue
        impl_func = VENDOR_METHODS[method][vendor]
        try:
            return impl_func(*args, **kwargs)
        except NoMarketDataError as e:
            last_no_data = e
            continue
        except Exception as e:
            if first_error is None:
                first_error = e
            continue

    if last_no_data is not None:
        sym = last_no_data.symbol
        canonical = last_no_data.canonical
        resolved = "" if canonical == sym else f" (resolved to '{canonical}')"
        return (
            f"NO_DATA_AVAILABLE: No crypto market data found for '{sym}'{resolved} from "
            f"any configured vendor. The pair may be invalid or unsupported. "
            f"Do not estimate or fabricate values — report that data is unavailable."
        )

    if first_error is not None:
        raise first_error

    raise RuntimeError(f"No available vendor for '{method}'")
