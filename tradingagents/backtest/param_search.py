"""Random parameter search bounds for registered strategies."""

from __future__ import annotations

import random
from typing import Any, Dict, List, Tuple

from .strategies import STRATEGY_REGISTRY, build_strategy

# (min, max, type) per field — only listed strategies participate in search.
STRATEGY_PARAM_BOUNDS: Dict[str, Dict[str, Tuple[Any, Any, type]]] = {
    "ema_crossover": {
        "fast_period": (5, 20, int),
        "slow_period": (30, 100, int),
    },
    "rsi_mean_reversion": {
        "period": (10, 21, int),
        "oversold": (20, 40, int),
        "overbought": (60, 80, int),
    },
    "bollinger_mean_reversion": {
        "period": (14, 30, int),
        "std_mult": (1.5, 2.5, float),
    },
    "cmo_mean_reversion": {
        "period": (10, 21, int),
        "oversold": (-60, -40, int),
        "overbought": (40, 60, int),
    },
    "adx_trend_filter": {
        "period": (10, 21, int),
        "adx_threshold": (20, 30, int),
    },
    "cci_breakout": {
        "period": (14, 30, int),
    },
    "apo_crossover": {
        "fast": (5, 15, int),
        "slow": (15, 40, int),
    },
}


def default_params_for(strategy_name: str) -> Dict[str, Any]:
    """Return registry default parameters for a strategy."""
    return dict(build_strategy(strategy_name, {}).parameters)


def _sample_value(rng: random.Random, low: Any, high: Any, cast: type) -> Any:
    if cast is int:
        return rng.randint(int(low), int(high))
    return round(rng.uniform(float(low), float(high)), 4)


def sample_strategy_params(strategy_name: str, rng: random.Random) -> Dict[str, Any]:
    """Draw one random parameter set within bounds (falls back to defaults)."""
    bounds = STRATEGY_PARAM_BOUNDS.get(strategy_name)
    if not bounds:
        return default_params_for(strategy_name)

    params = default_params_for(strategy_name)
    for field, (low, high, cast) in bounds.items():
        params[field] = _sample_value(rng, low, high, cast)

    if strategy_name == "ema_crossover" and params["fast_period"] >= params["slow_period"]:
        params["fast_period"] = 10
        params["slow_period"] = max(50, params["slow_period"])
    if strategy_name == "apo_crossover" and params["fast"] >= params["slow"]:
        params["slow"] = params["fast"] + 5
    if strategy_name == "rsi_mean_reversion" and params["oversold"] >= params["overbought"]:
        params["oversold"], params["overbought"] = 30, 70
    return params


def param_candidates(strategy_name: str, config: dict) -> List[Dict[str, Any]]:
    """Parameter sets to evaluate — defaults only, or defaults + random samples."""
    defaults = default_params_for(strategy_name)
    if not config.get("optimize_strategy_params"):
        return [defaults]

    samples = int(config.get("param_search_samples", 20))
    max_runs = int(config.get("param_search_max_runs", 600))
    rng = random.Random(f"{strategy_name}:{config.get('param_search_seed', 42)}")

    candidates: List[Dict[str, Any]] = [defaults]
    seen = {frozenset(defaults.items())}
    attempts = 0
    while len(candidates) < samples + 1 and attempts < samples * 3:
        attempts += 1
        params = sample_strategy_params(strategy_name, rng)
        key = frozenset(params.items())
        if key in seen:
            continue
        seen.add(key)
        candidates.append(params)
        if len(candidates) >= max_runs:
            break
    return candidates[:max_runs]
