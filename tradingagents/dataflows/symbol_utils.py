"""Crypto pair normalization and validation.

Supported user formats:
  BTC/USDT, BTC-USDT, BTCUSDT, ETH/USDC, SOL/USD

Binance symbols are derived as concatenated uppercase base+quote (e.g. BTCUSDT).
CoinGecko lookups use the base asset symbol (BTC, ETH, SOL).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)


class NoMarketDataError(Exception):
    """Raised when a vendor returns no rows/records for a symbol."""

    def __init__(self, symbol: str, canonical: str | None = None, detail: str = ""):
        self.symbol = symbol
        self.canonical = canonical or symbol
        self.detail = detail
        msg = f"No market data for {symbol!r}"
        if canonical and canonical != symbol:
            msg += f" (queried as {canonical!r})"
        if detail:
            msg += f": {detail}"
        super().__init__(msg)


_KNOWN_BASES = frozenset(
    {
        "BTC", "ETH", "SOL", "XRP", "ADA", "DOGE", "LTC", "BCH", "DOT", "AVAX",
        "LINK", "MATIC", "POL", "UNI", "ATOM", "NEAR", "APT", "ARB", "OP", "SUI",
        "BNB", "TRX", "TON", "SHIB", "PEPE", "FIL", "ICP", "HBAR", "VET", "ALGO",
    }
)

_KNOWN_QUOTES = frozenset({"USDT", "USDC", "USD", "BTC", "ETH", "EUR", "GBP", "BUSD"})

# Map display quotes to exchange-native symbols where needed.
_QUOTE_ALIASES = {"USD": "USDT"}

_PAIR_RE = re.compile(
    r"^([A-Za-z0-9]{2,10})[/\-]([A-Za-z0-9]{2,10})$"
)


@dataclass(frozen=True)
class CryptoPair:
    """Normalized crypto trading pair."""

    raw: str
    base: str
    quote: str

    @property
    def display(self) -> str:
        return f"{self.base}/{self.quote}"

    @property
    def binance_symbol(self) -> str:
        quote = _QUOTE_ALIASES.get(self.quote, self.quote)
        return f"{self.base}{quote}"

    @property
    def cache_key(self) -> str:
        return self.binance_symbol


def parse_crypto_pair(raw: str) -> CryptoPair:
    """Parse and validate a crypto pair string."""
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError(f"Invalid crypto pair: {raw!r}")

    s = raw.strip().upper()

    if "/" in s or "-" in s:
        match = _PAIR_RE.match(s)
        if not match:
            raise ValueError(f"Invalid crypto pair format: {raw!r}")
        base, quote = match.group(1), match.group(2)
    elif len(s) >= 6:
        # Concatenated form: try known base + quote suffixes longest-first.
        for quote in sorted(_KNOWN_QUOTES, key=len, reverse=True):
            if s.endswith(quote) and len(s) > len(quote):
                base = s[: -len(quote)]
                if base in _KNOWN_BASES or len(base) >= 2:
                    break
        else:
            raise ValueError(f"Cannot parse concatenated pair: {raw!r}")
    else:
        raise ValueError(f"Invalid crypto pair: {raw!r}")

    if quote not in _KNOWN_QUOTES:
        raise ValueError(f"Unsupported quote currency {quote!r} in pair {raw!r}")

    pair = CryptoPair(raw=raw.strip(), base=base, quote=quote)
    if pair.display != s and "/" not in s and "-" not in s:
        logger.info("Resolved pair %r to %s", raw, pair.display)
    return pair


def normalize_symbol(raw: str) -> str:
    """Return canonical display form ``BASE/QUOTE`` for a crypto pair."""
    return parse_crypto_pair(raw).display


def is_valid_crypto_pair(raw: str) -> bool:
    try:
        parse_crypto_pair(raw)
        return True
    except ValueError:
        return False


def is_cache_safe(symbol: str) -> bool:
    """True when symbol is safe to interpolate into a filesystem path."""
    return bool(symbol) and re.fullmatch(r"^[A-Za-z0-9]+$", symbol) is not None


def safe_path_key(raw: str) -> str:
    """Filesystem-safe cache/results key for a crypto pair (no slashes)."""
    return parse_crypto_pair(raw).cache_key
