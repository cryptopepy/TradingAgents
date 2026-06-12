"""CryptoCompare API — fallback OHLCV and news."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Annotated

import pandas as pd
import requests

from .crypto_common import env_api_key, http_get_json, no_data_message
from .date_window import article_date_in_range
from .symbol_utils import NoMarketDataError, parse_crypto_pair

logger = logging.getLogger(__name__)

_BASE_URL = "https://min-api.cryptocompare.com"


def _headers() -> dict:
    key = env_api_key("CRYPTOCOMPARE_API_KEY", "TRADINGAGENTS_CRYPTOCOMPARE_API_KEY")
    return {"authorization": f"Apikey {key}"} if key else {}


def fetch_spot_price(symbol: str) -> float | None:
    """Latest spot price for a crypto pair via CryptoCompare /data/price."""
    try:
        pair = parse_crypto_pair(symbol)
    except ValueError:
        return None
    fsym = pair.base
    tsym = pair.quote if pair.quote not in ("USDT", "USDC", "BUSD") else "USD"
    try:
        data = http_get_json(
            f"{_BASE_URL}/data/price",
            params={"fsym": fsym, "tsyms": tsym},
            headers=_headers(),
        )
        price = data.get(tsym)
        return float(price) if price is not None else None
    except requests.HTTPError as exc:
        if exc.response is not None and exc.response.status_code == 429:
            raise
        logger.debug("CryptoCompare spot price failed for %s: %s", symbol, exc)
        return None
    except Exception as exc:
        logger.debug("CryptoCompare spot price failed for %s: %s", symbol, exc)
        return None


def fetch_ohlcv(symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
    """Daily OHLCV from CryptoCompare histoday endpoint."""
    pair = parse_crypto_pair(symbol)
    fsym = pair.base
    tsym = pair.quote if pair.quote != "USDT" else "USD"

    try:
        end_ts = int(datetime.strptime(end_date, "%Y-%m-%d").timestamp())
        data = http_get_json(
            f"{_BASE_URL}/data/v2/histoday",
            params={"fsym": fsym, "tsym": tsym, "limit": 2000, "toTs": end_ts},
            headers=_headers(),
        )
    except Exception as exc:
        raise NoMarketDataError(symbol, pair.display, str(exc)) from exc

    raw = (data.get("Data") or {}).get("Data") or []
    if not raw:
        raise NoMarketDataError(symbol, pair.display, "CryptoCompare returned no rows")

    df = pd.DataFrame(raw)
    df["Date"] = pd.to_datetime(df["time"], unit="s")
    df = df.rename(columns={"open": "Open", "high": "High", "low": "Low", "close": "Close", "volumeto": "Volume"})
    start_dt = pd.to_datetime(start_date)
    end_dt = pd.to_datetime(end_date)
    df = df[(df["Date"] >= start_dt) & (df["Date"] <= end_dt)]
    for col in ("Open", "High", "Low", "Close", "Volume"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df[["Date", "Open", "High", "Low", "Close", "Volume"]].dropna(subset=["Close"])


def get_cryptocompare_ohlcv_csv(
    symbol: Annotated[str, "crypto pair"],
    start_date: Annotated[str, "start YYYY-MM-DD"],
    end_date: Annotated[str, "end YYYY-MM-DD"],
) -> str:
    df = fetch_ohlcv(symbol, start_date, end_date)
    pair = parse_crypto_pair(symbol)
    header = (
        f"# Crypto OHLCV for {pair.display} (CryptoCompare)\n"
        f"# Range: {start_date} to {end_date}\n"
        f"# Records: {len(df)}\n\n"
    )
    return header + df.to_csv(index=False)


def get_cryptocompare_news(
    symbol: Annotated[str, "crypto pair or base symbol"],
    start_date: Annotated[str, "start YYYY-MM-DD"],
    end_date: Annotated[str, "end YYYY-MM-DD"],
) -> str:
    try:
        pair = parse_crypto_pair(symbol)
        fsym = pair.base
    except ValueError:
        fsym = symbol.upper()

    try:
        data = http_get_json(
            f"{_BASE_URL}/data/v2/news/",
            params={"lang": "EN", "categories": fsym},
            headers=_headers(),
        )
    except Exception as exc:
        return no_data_message(symbol, f"CryptoCompare news: {exc}")

    articles = data.get("Data") or []

    lines = [f"# Crypto news for {fsym} ({start_date} to {end_date})", ""]
    count = 0
    for art in articles:
        published = datetime.utcfromtimestamp(art.get("published_on", 0))
        if not article_date_in_range(published, start_date, end_date):
            continue
        lines.append(f"## {art.get('title', 'Untitled')}")
        lines.append(f"Source: {art.get('source', 'N/A')} | {published.strftime('%Y-%m-%d')}")
        body = (art.get("body") or "")[:500]
        if body:
            lines.append(body)
        lines.append("")
        count += 1
        if count >= 20:
            break

    if count == 0:
        return no_data_message(symbol, "no news articles in date range")
    return "\n".join(lines)
