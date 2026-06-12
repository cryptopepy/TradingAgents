"""Shared helpers for crypto data vendors."""

from __future__ import annotations

import logging
import os
import socket
import time
from typing import Callable, TypeVar

import requests

logger = logging.getLogger(__name__)

NO_DATA_AVAILABLE = "NO_DATA_AVAILABLE"

T = TypeVar("T")


def env_api_key(*names: str) -> str | None:
    """Return the first non-empty API key from env var names."""
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return None


def http_get_json(url: str, *, params: dict | None = None, headers: dict | None = None, timeout: int = 30) -> dict | list:
    """GET JSON with basic retry on transient failures."""
    retryable = (
        requests.exceptions.ConnectionError,
        requests.exceptions.Timeout,
        socket.timeout,
        TimeoutError,
    )
    last_exc: Exception | None = None
    for attempt in range(4):
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=timeout)
            if resp.status_code == 429 and attempt < 3:
                time.sleep(2 ** attempt)
                continue
            resp.raise_for_status()
            return resp.json()
        except retryable as exc:
            last_exc = exc
            if attempt < 3:
                time.sleep(2 ** attempt)
            else:
                raise
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code >= 500 and attempt < 3:
                time.sleep(2 ** attempt)
                last_exc = exc
                continue
            raise
    if last_exc:
        raise last_exc
    raise RuntimeError(f"Failed to fetch {url}")


def no_data_message(symbol: str, detail: str = "") -> str:
    suffix = f" ({detail})" if detail else ""
    return (
        f"{NO_DATA_AVAILABLE}: No crypto market data found for '{symbol}'{suffix} "
        f"from any configured vendor. The pair may be invalid or unsupported. "
        f"Do not estimate or fabricate values — report that data is unavailable."
    )
