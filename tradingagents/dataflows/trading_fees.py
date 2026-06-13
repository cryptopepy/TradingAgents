"""Paper/backtest transaction-cost helpers."""

from __future__ import annotations

from .symbol_utils import parse_crypto_pair

_MAJOR_BASES = frozenset({"BTC", "ETH"})


def paper_transaction_cost_pct(symbol: str, config: dict | None = None) -> float:
    """Per-side cost fraction; alts use a higher multiplier than BTC/ETH."""
    cfg = config or {}
    base = float(cfg.get("paper_transaction_cost_pct", 0.001))
    try:
        base_asset = parse_crypto_pair(symbol).base
    except ValueError:
        base_asset = symbol.split("/")[0].upper()
    if base_asset in _MAJOR_BASES:
        return base
    mult = float(cfg.get("paper_alt_fee_multiplier", 2.0))
    return base * mult


def paper_fee_bps(symbol: str, config: dict | None = None) -> float:
    return paper_transaction_cost_pct(symbol, config) * 10_000.0
