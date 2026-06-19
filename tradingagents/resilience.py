"""Shared retry/backoff helpers for long-running paper trading and data vendors."""

from __future__ import annotations

import logging
import time
from typing import Callable, Optional, Sequence, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

DEFAULT_API_RETRY_DELAYS: tuple[float, ...] = (10.0, 30.0, 180.0)
QUICK_RETRY_DELAYS: tuple[float, ...] = (1.0, 2.0, 4.0)


def retry_delays_from_config(config: dict | None, *, quick: bool = False) -> tuple[float, ...]:
    """Resolve retry schedule from config (paper uses long delays by default)."""
    if config is None:
        return QUICK_RETRY_DELAYS if quick else DEFAULT_API_RETRY_DELAYS
    raw = config.get("api_retry_delays_seconds")
    if raw is None:
        return QUICK_RETRY_DELAYS if quick else DEFAULT_API_RETRY_DELAYS
    if isinstance(raw, (list, tuple)):
        return tuple(float(x) for x in raw)
    return DEFAULT_API_RETRY_DELAYS


def retry_with_backoff(
    fn: Callable[[], T],
    *,
    delays: Sequence[float] = DEFAULT_API_RETRY_DELAYS,
    on_retry: Optional[Callable[[int, float, Exception], None]] = None,
    on_give_up: Optional[Callable[[Exception], None]] = None,
    label: str = "operation",
) -> T:
    """Call ``fn``; on failure wait through ``delays`` and retry. Raises on final failure."""
    last_exc: Exception | None = None
    attempts = len(delays) + 1
    for attempt in range(attempts):
        try:
            return fn()
        except Exception as exc:
            last_exc = exc
            if attempt >= attempts - 1:
                break
            wait = float(delays[attempt])
            logger.warning(
                "%s failed (attempt %d/%d): %s — retrying in %.0fs",
                label,
                attempt + 1,
                attempts,
                exc,
                wait,
            )
            if on_retry is not None:
                on_retry(attempt + 1, wait, exc)
            time.sleep(wait)
    assert last_exc is not None
    if on_give_up is not None:
        on_give_up(last_exc)
    raise last_exc


def retry_with_backoff_optional(
    fn: Callable[[], T],
    *,
    delays: Sequence[float] = DEFAULT_API_RETRY_DELAYS,
    on_retry: Optional[Callable[[int, float, Exception], None]] = None,
    on_give_up: Optional[Callable[[Exception], None]] = None,
    label: str = "operation",
) -> Optional[T]:
    """Like ``retry_with_backoff`` but returns ``None`` after all attempts fail."""
    try:
        return retry_with_backoff(
            fn,
            delays=delays,
            on_retry=on_retry,
            on_give_up=on_give_up,
            label=label,
        )
    except Exception:
        return None
