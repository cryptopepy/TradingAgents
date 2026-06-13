"""Kraken REST + ccxt helpers — public market data and optional API-key auth."""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import time
import urllib.parse
from typing import Any

import requests

from .crypto_common import env_api_key, http_get_json

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.kraken.com"
_PRIVATE_PATH = "/0/private"


def kraken_credentials() -> tuple[str | None, str | None]:
    """Return (api_key, api_secret) from env, or (None, None) when unset."""
    key = env_api_key("KRAKEN_API_KEY", "TRADINGAGENTS_KRAKEN_API_KEY")
    secret = env_api_key("KRAKEN_API_SECRET", "TRADINGAGENTS_KRAKEN_API_SECRET")
    if key and secret:
        return key, secret
    return None, None


def kraken_ccxt_config() -> dict[str, Any]:
    """ccxt.kraken() config with optional API credentials."""
    cfg: dict[str, Any] = {"enableRateLimit": True}
    key, secret = kraken_credentials()
    if key and secret:
        cfg["apiKey"] = key
        cfg["secret"] = secret
    return cfg


def _sign_private(path: str, data: dict[str, Any], secret: str) -> str:
    postdata = urllib.parse.urlencode(data)
    encoded = (str(data["nonce"]) + postdata).encode()
    message = path.encode() + hashlib.sha256(encoded).digest()
    mac = hmac.new(base64.b64decode(secret), message, hashlib.sha512)
    return base64.b64encode(mac.digest()).decode()


def _private_post(endpoint: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    key, secret = kraken_credentials()
    if not key or not secret:
        raise RuntimeError("Kraken API key and secret are required for private endpoints")

    path = f"{_PRIVATE_PATH}/{endpoint}"
    payload = dict(data or {})
    payload["nonce"] = int(time.time() * 1000)

    headers = {
        "API-Key": key,
        "API-Sign": _sign_private(path, payload, secret),
        "Content-Type": "application/x-www-form-urlencoded",
    }
    resp = requests.post(
        f"{_BASE_URL}{path}",
        data=payload,
        headers=headers,
        timeout=30,
    )
    resp.raise_for_status()
    body = resp.json()
    errors = body.get("error") or []
    if errors:
        raise RuntimeError(f"Kraken API error: {errors}")
    return body.get("result") or {}


def fetch_api_key_info() -> dict[str, Any]:
    """Inspect the configured key's permissions (no funds/orders required to call)."""
    return _private_post("GetApiKeyInfo")


def fetch_public_ticker(pair: str) -> dict[str, Any]:
    """Spot ticker (bid/ask/last/volume) — public, no API key required."""
    data = http_get_json(f"{_BASE_URL}/0/public/Ticker", params={"pair": pair})
    errors = data.get("error") or []
    if errors:
        raise RuntimeError(f"Kraken public Ticker error: {errors}")
    return data.get("result") or {}


def fetch_public_ohlc(
    pair: str,
    *,
    interval: int = 5,
    since: int | None = None,
) -> tuple[list[list], int]:
    """OHLC candles — public. Returns (rows, last_id). Up to 720 recent bars."""
    params: dict[str, Any] = {"pair": pair, "interval": interval}
    if since is not None:
        params["since"] = since
    data = http_get_json(f"{_BASE_URL}/0/public/OHLC", params=params)
    errors = data.get("error") or []
    if errors:
        raise RuntimeError(f"Kraken public OHLC error: {errors}")
    result = data.get("result") or {}
    last_id = int(result.get("last", 0))
    rows: list[list] = []
    for key, value in result.items():
        if key == "last":
            continue
        if isinstance(value, list):
            rows = value
            break
    return rows, last_id


def kraken_status_summary() -> str:
    """Compact Kraken auth status for the market panel (row is already labeled Kraken)."""
    key, secret = kraken_credentials()
    if not key or not secret:
        return "public only"
    try:
        info = fetch_api_key_info()
    except Exception as exc:
        msg = str(exc).strip()
        if len(msg) > 48:
            msg = msg[:45] + "…"
        return f"key error — {msg}"
    label = str(info.get("apiKeyName") or info.get("desc") or "").strip()
    if label and label.lower() not in {"api key", "apikey"}:
        return f"authenticated · {label}"
    return "authenticated"


def create_ccxt_kraken():
    """Instantiated ccxt.kraken exchange with env credentials when set."""
    import ccxt

    return ccxt.kraken(kraken_ccxt_config())


_QUOTE_SUFFIXES = ("/USD", "/USDT", "/USDC")


def _normalize_kraken_ticker(symbol: str, ticker: dict[str, Any]) -> dict[str, Any] | None:
    """Map a ccxt Kraken ticker to a mover row, or None when unsuitable."""
    if not any(symbol.endswith(sfx) for sfx in _QUOTE_SUFFIXES):
        return None
    if symbol.endswith(".d"):  # dark pool variants
        return None

    change = ticker.get("percentage")
    if change is None:
        open_price = ticker.get("open")
        last = ticker.get("last")
        if open_price and last and float(open_price) > 0:
            change = (float(last) - float(open_price)) / float(open_price) * 100.0
    if change is None:
        return None

    volume = ticker.get("quoteVolume")
    if volume is None:
        base_vol = ticker.get("baseVolume")
        last = ticker.get("last")
        if base_vol is not None and last is not None:
            volume = float(base_vol) * float(last)
    if volume is None:
        return None

    last_price = float(ticker.get("last") or 0.0)
    if last_price <= 0:
        return None

    base = symbol.split("/")[0]
    if base.startswith("X") and len(base) == 4:
        base = base[1:]
    if base == "XBT":
        base = "BTC"
    if base == "XDG":
        base = "DOGE"

    return {
        "symbol": base,
        "pair": symbol,
        "name": base,
        "change_pct": float(change),
        "volume_usd": float(volume),
        "price_usd": last_price,
    }


def _normalize_rest_ticker(pair_code: str, row: dict[str, Any]) -> dict[str, Any] | None:
    """Parse Kraken REST /public/Ticker row (legacy pair codes)."""
    try:
        last = float(row["c"][0])
        open_today = float(row["o"])
        vol_base_24h = float(row["v"][1])
    except (KeyError, IndexError, TypeError, ValueError):
        return None
    if last <= 0 or open_today <= 0:
        return None
    change = (last - open_today) / open_today * 100.0
    volume_usd = vol_base_24h * last
    code = pair_code.upper()
    if code.endswith("ZUSD") or code.endswith("USD"):
        quote = "USD"
        base_raw = code.replace("ZUSD", "").replace("USD", "")
    elif code.endswith("USDT"):
        quote = "USDT"
        base_raw = code.replace("USDT", "")
    else:
        return None
    base = base_raw.replace("X", "", 1) if base_raw.startswith("X") else base_raw
    if base == "XBT":
        base = "BTC"
    if base == "XDG":
        base = "DOGE"
    pair = f"{base}/{quote}"
    return {
        "symbol": base,
        "pair": pair,
        "name": base,
        "change_pct": change,
        "volume_usd": volume_usd,
        "price_usd": last,
    }


def fetch_kraken_mover_rows(*, min_volume_usd: float) -> list[dict[str, Any]]:
    """Liquid Kraken spot pairs ranked by today's % move (ccxt, REST fallback)."""
    rows: list[dict[str, Any]] = []
    try:
        exchange = create_ccxt_kraken()
        exchange.load_markets()
        tickers = exchange.fetch_tickers()
        for symbol, ticker in tickers.items():
            row = _normalize_kraken_ticker(symbol, ticker)
            if row and row["volume_usd"] >= min_volume_usd:
                rows.append(row)
    except Exception as exc:
        logger.info("ccxt Kraken tickers failed (%s) — trying REST", exc)
        data = http_get_json(f"{_BASE_URL}/0/public/Ticker")
        errors = data.get("error") or []
        if errors:
            raise RuntimeError(f"Kraken Ticker error: {errors}") from exc
        for pair_code, payload in (data.get("result") or {}).items():
            row = _normalize_rest_ticker(pair_code, payload)
            if row and row["volume_usd"] >= min_volume_usd:
                rows.append(row)

    # Deduplicate BTC/USD vs XBT/USD style aliases — keep higher volume row per base
    best: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = row["pair"]
        prev = best.get(key)
        if prev is None or row["volume_usd"] > prev["volume_usd"]:
            best[key] = row
    return list(best.values())
