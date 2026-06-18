"""Per-symbol optimization presets — filters for all, richer search for alts."""

from __future__ import annotations

from tradingagents.dataflows.symbol_utils import parse_crypto_pair

_MAJOR_BASES = frozenset({"BTC", "ETH"})


def is_major_symbol(symbol: str) -> bool:
    try:
        return parse_crypto_pair(symbol).base in _MAJOR_BASES
    except ValueError:
        base = symbol.split("/")[0].upper()
        return base in _MAJOR_BASES


def is_alt_symbol(symbol: str) -> bool:
    return not is_major_symbol(symbol)


def enrich_optimization_config(config: dict | None, symbol: str) -> dict:
    """Apply default filters/ATR stops and alt-only richer optimization knobs."""
    cfg = dict(config or {})

    # Universal quality filters (majors + alts)
    cfg.setdefault("regime_filter_enabled", True)
    cfg.setdefault("min_bars_between_trades", 2)
    cfg.setdefault("atr_stops_enabled", True)
    cfg.setdefault("min_edge_filter_enabled", True)
    cfg.setdefault("winner_score_mode", "composite")
    cfg.setdefault("winner_selection_mode", "multi_horizon")
    cfg.setdefault("winner_require_long_horizon", True)

    if is_alt_symbol(symbol) and cfg.get("alt_auto_rich_optimization", True):
        cfg.setdefault("optimize_strategy_params", True)
        cfg.setdefault("alt_expand_risk_variants", True)
        samples = int(cfg.get("alt_param_search_samples", 12))
        cfg["param_search_samples"] = max(
            samples,
            int(cfg.get("param_search_samples", 0) or 0),
        )
        if cfg.get("alt_walk_forward_enabled", True):
            cfg.setdefault("walk_forward_enabled", True)
    else:
        cfg.setdefault("optimize_strategy_params", False)
        cfg.setdefault("major_risk_variants_enabled", True)

    return cfg
