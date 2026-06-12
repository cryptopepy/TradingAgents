"""Crypto OHLCV loading, caching, and technical indicators."""

from __future__ import annotations

import logging
import os
from typing import Annotated

import pandas as pd
from stockstats import wrap

from .binance import fetch_klines
from .config import get_config
from .cryptocompare import fetch_ohlcv as fetch_cryptocompare_ohlcv
from .symbol_utils import NoMarketDataError, parse_crypto_pair
from .utils import safe_ticker_component

logger = logging.getLogger(__name__)


def _ensure_date_column(data: pd.DataFrame) -> pd.DataFrame:
    if "Date" in data.columns:
        return data
    for candidate in ("index", "Datetime", "date", "open_time"):
        if candidate in data.columns:
            return data.rename(columns={candidate: "Date"})
    return data


def _clean_dataframe(data: pd.DataFrame) -> pd.DataFrame:
    data = _ensure_date_column(data)
    data["Date"] = pd.to_datetime(data["Date"], errors="coerce")
    data = data.dropna(subset=["Date"])
    price_cols = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in data.columns]
    data[price_cols] = data[price_cols].apply(pd.to_numeric, errors="coerce")
    data = data.dropna(subset=["Close"])
    data[price_cols] = data[price_cols].ffill().bfill()
    return data


def _fetch_ohlcv_from_vendors(symbol: str, start_str: str, end_str: str) -> pd.DataFrame:
    """Try Binance first, then CryptoCompare."""
    errors: list[str] = []
    for fetcher, name in (
        (lambda: fetch_klines(symbol, start_str, end_str), "Binance"),
        (lambda: fetch_cryptocompare_ohlcv(symbol, start_str, end_str), "CryptoCompare"),
    ):
        try:
            df = fetcher()
            if not df.empty and "Close" in df.columns:
                return df
        except NoMarketDataError as exc:
            errors.append(f"{name}: {exc.detail}")
        except Exception as exc:
            errors.append(f"{name}: {exc}")
    detail = "; ".join(errors) or "no vendor returned rows"
    pair = parse_crypto_pair(symbol)
    raise NoMarketDataError(symbol, pair.display, detail)


def load_ohlcv(symbol: str, curr_date: str) -> pd.DataFrame:
    """Fetch crypto OHLCV with caching, filtered to prevent look-ahead bias."""
    pair = parse_crypto_pair(symbol)
    safe_symbol = safe_ticker_component(pair.cache_key)

    config = get_config()
    curr_date_dt = pd.to_datetime(curr_date)
    today_date = pd.Timestamp.today()
    start_date = today_date - pd.DateOffset(years=2)
    start_str = start_date.strftime("%Y-%m-%d")
    end_str = today_date.strftime("%Y-%m-%d")

    os.makedirs(config["data_cache_dir"], exist_ok=True)
    data_file = os.path.join(
        config["data_cache_dir"],
        f"{safe_symbol}-crypto-ohlcv-{start_str}-{end_str}.csv",
    )

    data = None
    if os.path.exists(data_file):
        cached = pd.read_csv(data_file, on_bad_lines="skip", encoding="utf-8")
        if not cached.empty and "Close" in cached.columns:
            data = cached

    if data is None:
        downloaded = _fetch_ohlcv_from_vendors(symbol, start_str, end_str)
        downloaded = _ensure_date_column(downloaded)
        if downloaded.empty or "Close" not in downloaded.columns:
            raise NoMarketDataError(symbol, pair.display, "no rows after fetch")
        downloaded.to_csv(data_file, index=False, encoding="utf-8")
        data = downloaded

    data = _clean_dataframe(data)
    return data[data["Date"] <= curr_date_dt]


_INDICATOR_DOCS = {
    "close_50_sma": "50 SMA — medium-term trend",
    "close_200_sma": "200 SMA — long-term trend benchmark",
    "close_10_ema": "10 EMA — short-term momentum",
    "macd": "MACD — momentum crossover",
    "macds": "MACD signal line",
    "macdh": "MACD histogram",
    "rsi": "RSI — overbought/oversold (70/30)",
    "boll": "Bollinger middle band (20 SMA)",
    "boll_ub": "Bollinger upper band",
    "boll_lb": "Bollinger lower band",
    "atr": "ATR — volatility for stop placement",
    "vwma": "VWMA — volume-weighted moving average",
}


def get_crypto_indicators_window(
    symbol: Annotated[str, "crypto pair e.g. BTC/USDT"],
    indicator: Annotated[str, "indicator name e.g. rsi, macd"],
    curr_date: Annotated[str, "analysis date YYYY-MM-DD"],
    look_back_days: Annotated[int, "lookback days"] = 30,
) -> str:
    """Compute a single technical indicator on crypto OHLCV."""
    ind = indicator.strip().lower()
    if ind not in _INDICATOR_DOCS:
        return f"Unknown indicator '{indicator}'. Supported: {', '.join(_INDICATOR_DOCS)}"

    data = load_ohlcv(symbol, curr_date)
    df = wrap(data.copy())
    df["Date"] = df["Date"].dt.strftime("%Y-%m-%d")
    curr_date_str = pd.to_datetime(curr_date).strftime("%Y-%m-%d")

    df[ind]  # trigger stockstats calculation
    window = df[df["Date"] <= curr_date_str].tail(look_back_days)
    matching = window[window["Date"].str.startswith(curr_date_str)]

    if matching.empty:
        # Crypto trades 24/7 — use latest row on or before curr_date
        latest = window.tail(1)
        if latest.empty:
            return f"N/A: No OHLCV data on or before {curr_date}"
        value = latest[ind].values[0]
        used_date = latest["Date"].values[0]
    else:
        value = matching[ind].values[0]
        used_date = curr_date_str

    doc = _INDICATOR_DOCS[ind]
    return (
        f"# {ind.upper()} for {normalize_pair_display(symbol)}\n"
        f"Date: {used_date}\n"
        f"Value: {value}\n"
        f"Description: {doc}\n"
        f"Lookback: {look_back_days} days"
    )


def normalize_pair_display(symbol: str) -> str:
    return parse_crypto_pair(symbol).display


class CryptoIndicatorUtils:
    """Static accessor for risk guard ATR lookups."""

    @staticmethod
    def get_indicator(symbol: str, indicator: str, curr_date: str):
        data = load_ohlcv(symbol, curr_date)
        df = wrap(data)
        df["Date"] = df["Date"].dt.strftime("%Y-%m-%d")
        curr_date_str = pd.to_datetime(curr_date).strftime("%Y-%m-%d")
        df[indicator]
        matching = df[df["Date"].str.startswith(curr_date_str)]
        if not matching.empty:
            return matching[indicator].values[0]
        latest = df[df["Date"] <= curr_date_str].tail(1)
        if latest.empty:
            return "N/A: No OHLCV data"
        return latest[indicator].values[0]
