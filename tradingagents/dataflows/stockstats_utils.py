import socket
import time
import logging

import pandas as pd
import requests
import yfinance as yf
from yfinance.exceptions import YFRateLimitError
from stockstats import wrap
from typing import Annotated
import os
from urllib.error import URLError
from .config import get_config
from .utils import safe_ticker_component
from .symbol_utils import normalize_symbol, NoMarketDataError

logger = logging.getLogger(__name__)


def _is_retryable_http_error(exc: Exception) -> bool:
    response = getattr(exc, "response", None)
    if response is not None and getattr(response, "status_code", 0) >= 500:
        return True
    return False


def yf_retry(func, max_retries=3, base_delay=2.0):
    """Execute a yfinance call with exponential backoff on transient failures.

    Retries on Yahoo rate limits (HTTP 429), socket timeouts, connection drops,
    URLError, and HTTP 5xx responses from the underlying requests session.
    """
    retryable = (
        YFRateLimitError,
        socket.timeout,
        TimeoutError,
        ConnectionError,
        ConnectionResetError,
        URLError,
        requests.exceptions.ConnectionError,
        requests.exceptions.Timeout,
    )
    for attempt in range(max_retries + 1):
        try:
            return func()
        except retryable as exc:
            if attempt < max_retries:
                delay = base_delay * (2 ** attempt)
                logger.warning(
                    "Yahoo Finance transient error (%s), retrying in %.0fs "
                    "(attempt %d/%d)",
                    type(exc).__name__,
                    delay,
                    attempt + 1,
                    max_retries,
                )
                time.sleep(delay)
            else:
                raise
        except requests.HTTPError as exc:
            if _is_retryable_http_error(exc) and attempt < max_retries:
                delay = base_delay * (2 ** attempt)
                logger.warning(
                    "Yahoo Finance HTTP %s, retrying in %.0fs (attempt %d/%d)",
                    getattr(exc.response, "status_code", "?"),
                    delay,
                    attempt + 1,
                    max_retries,
                )
                time.sleep(delay)
            else:
                raise


def _ensure_date_column(data: pd.DataFrame) -> pd.DataFrame:
    """Normalize the date column to ``Date``.

    Some yfinance builds leave the index unnamed (so ``reset_index()`` yields
    ``index``) or use ``Datetime`` for intraday data. Rename the first
    date-like column so indicators don't silently drop when it isn't ``Date``.
    """
    if "Date" in data.columns:
        return data
    for candidate in ("index", "Datetime", "date"):
        if candidate in data.columns:
            return data.rename(columns={candidate: "Date"})
    return data


def _clean_dataframe(data: pd.DataFrame) -> pd.DataFrame:
    """Normalize a stock DataFrame for stockstats: parse dates, drop invalid rows, fill price gaps."""
    data = _ensure_date_column(data)
    data["Date"] = pd.to_datetime(data["Date"], errors="coerce")
    data = data.dropna(subset=["Date"])

    price_cols = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in data.columns]
    data[price_cols] = data[price_cols].apply(pd.to_numeric, errors="coerce")
    data = data.dropna(subset=["Close"])
    data[price_cols] = data[price_cols].ffill().bfill()

    return data


def load_ohlcv(symbol: str, curr_date: str) -> pd.DataFrame:
    """Fetch OHLCV data with caching, filtered to prevent look-ahead bias.

    Downloads 15 years of data up to today and caches per symbol. On
    subsequent calls the cache is reused. Rows after curr_date are
    filtered out so backtests never see future prices.
    """
    # Resolve broker/forex symbols (XAUUSD+ -> GC=F) to Yahoo's convention,
    # then reject values that would escape the cache directory when
    # interpolated into the cache filename (e.g. ``../../tmp/x``).
    canonical = normalize_symbol(symbol)
    safe_symbol = safe_ticker_component(canonical)

    config = get_config()
    curr_date_dt = pd.to_datetime(curr_date)

    # Cache uses a fixed window (15y to today) so one file per symbol
    today_date = pd.Timestamp.today()
    start_date = today_date - pd.DateOffset(years=5)
    start_str = start_date.strftime("%Y-%m-%d")
    end_str = today_date.strftime("%Y-%m-%d")

    os.makedirs(config["data_cache_dir"], exist_ok=True)
    data_file = os.path.join(
        config["data_cache_dir"],
        f"{safe_symbol}-YFin-data-{start_str}-{end_str}.csv",
    )

    # A cached file may be empty if a prior fetch failed (unknown symbol,
    # transient rate limit). Treat an empty/columnless cache as a miss and
    # re-fetch rather than serving the poisoned file forever.
    data = None
    if os.path.exists(data_file):
        cached = pd.read_csv(data_file, on_bad_lines="skip", encoding="utf-8")
        if not cached.empty and "Close" in cached.columns:
            data = cached

    if data is None:
        downloaded = yf_retry(lambda: yf.download(
            canonical,
            start=start_str,
            end=end_str,
            multi_level_index=False,
            progress=False,
            auto_adjust=True,
        ))
        downloaded = _ensure_date_column(downloaded.reset_index())
        # Only cache real data — never persist an empty frame.
        if downloaded.empty or "Close" not in downloaded.columns:
            raise NoMarketDataError(
                symbol, canonical, "Yahoo Finance returned no rows"
            )
        downloaded.to_csv(data_file, index=False, encoding="utf-8")
        data = downloaded

    data = _clean_dataframe(data)

    # Filter to curr_date to prevent look-ahead bias in backtesting
    data = data[data["Date"] <= curr_date_dt]

    return data


def _financial_publication_lag_days(data: pd.DataFrame, statement_type: str = "auto") -> int:
    """Return SEC filing publication lag in days (45 for 10-Q, 90 for 10-K)."""
    if statement_type == "quarterly":
        return 45
    if statement_type == "annual":
        return 90
    col_dates = pd.to_datetime(data.columns, errors="coerce")
    valid_dates = col_dates.dropna().sort_values()
    if len(valid_dates) >= 2:
        median_gap = valid_dates.diff().dropna().median()
        if pd.notna(median_gap) and median_gap.days < 120:
            return 45
    return 90


def filter_financials_by_date(
    data: pd.DataFrame,
    curr_date: str,
    statement_type: str = "auto",
) -> pd.DataFrame:
    """Drop financial statement columns not yet public as of ``curr_date``.

    yfinance financial statements use fiscal period end dates as columns.
    A publication lag is applied before filtering (45 days for quarterly
    10-Q filings, 90 days for annual 10-K) so fiscal periods whose filings
    would not yet be available are excluded, preventing look-ahead bias.
    """
    if not curr_date or data.empty:
        return data
    lag_days = _financial_publication_lag_days(data, statement_type)
    cutoff = pd.Timestamp(curr_date) - pd.Timedelta(days=lag_days)
    col_dates = pd.to_datetime(data.columns, errors="coerce")
    mask = col_dates.isna() | (col_dates <= cutoff)
    return data.loc[:, mask]


class StockstatsUtils:
    @staticmethod
    def get_stock_stats(
        symbol: Annotated[str, "ticker symbol for the company"],
        indicator: Annotated[
            str, "quantitative indicators based off of the stock data for the company"
        ],
        curr_date: Annotated[
            str, "curr date for retrieving stock price data, YYYY-mm-dd"
        ],
    ):
        data = load_ohlcv(symbol, curr_date)
        df = wrap(data)
        df["Date"] = df["Date"].dt.strftime("%Y-%m-%d")
        curr_date_str = pd.to_datetime(curr_date).strftime("%Y-%m-%d")

        df[indicator]  # trigger stockstats to calculate the indicator
        matching_rows = df[df["Date"].str.startswith(curr_date_str)]

        if not matching_rows.empty:
            indicator_value = matching_rows[indicator].values[0]
            return indicator_value
        else:
            return "N/A: Not a trading day (weekend or holiday)"
