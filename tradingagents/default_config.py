import os

_TRADINGAGENTS_HOME = os.path.join(os.path.expanduser("~"), ".tradingagents")

# Single source of truth for env-var → config-key overrides. To expose
# a new config key for environment-based override, add a row here — no
# entry-point script changes required. Coercion is driven by the type
# of the existing default, so users can keep writing plain strings in
# their .env file.
_ENV_OVERRIDES = {
    "TRADINGAGENTS_LLM_PROVIDER":         "llm_provider",
    "TRADINGAGENTS_DEEP_THINK_LLM":       "deep_think_llm",
    "TRADINGAGENTS_QUICK_THINK_LLM":      "quick_think_llm",
    "TRADINGAGENTS_LLM_BACKEND_URL":      "backend_url",
    "TRADINGAGENTS_OUTPUT_LANGUAGE":      "output_language",
    "TRADINGAGENTS_MAX_DEBATE_ROUNDS":    "max_debate_rounds",
    "TRADINGAGENTS_MAX_RISK_ROUNDS":      "max_risk_discuss_rounds",
    "TRADINGAGENTS_CHECKPOINT_ENABLED":   "checkpoint_enabled",
    "TRADINGAGENTS_BENCHMARK_TICKER":     "benchmark_ticker",
    "TRADINGAGENTS_TEMPERATURE":          "temperature",
    "TRADINGAGENTS_LIVE_MODE":            "live_mode",
    "TRADINGAGENTS_PAPER_TRADE_ENABLED":  "paper_trade_enabled",
    "TRADINGAGENTS_PAPER_LOSS_REVIEW_MINUTES": "paper_loss_review_minutes",
    "TRADINGAGENTS_PAPER_LOSS_THRESHOLD_PCT": "paper_loss_threshold_pct",
    "TRADINGAGENTS_PAPER_TICK_INTERVAL_SECONDS": "paper_tick_interval_seconds",
    "TRADINGAGENTS_PAPER_INITIAL_EQUITY": "paper_initial_equity",
    "TRADINGAGENTS_PAPER_ADAPTIVE_ENABLED": "paper_adaptive_enabled",
    "TRADINGAGENTS_DRAWDOWN_TIME_WINDOW": "drawdown_time_window_minutes",
    "TRADINGAGENTS_DRAWDOWN_MAX_LOOKBACK_MINUTES": "drawdown_max_lookback_minutes",
    "TRADINGAGENTS_MAX_ALLOWED_DRAWDOWN_PCT": "max_allowed_drawdown_pct",
    "BACKTEST_CACHE_TTL_SECONDS": "backtest_cache_ttl_seconds",
    "TRADINGAGENTS_PAPER_STATE_ENABLED": "paper_state_persistence",
    "TRADINGAGENTS_PAPER_STOP_LOSS_PCT": "paper_stop_loss_pct",
    "TRADINGAGENTS_PAPER_TAKE_PROFIT_PCT": "paper_take_profit_pct",
    "TRADINGAGENTS_WINNER_GATE_ENABLED": "winner_gate_enabled",
    "TRADINGAGENTS_WINNER_MIN_NET_PROFIT": "winner_min_net_profit",
    "TRADINGAGENTS_WINNER_MIN_TRADES": "winner_min_trades",
    "TRADINGAGENTS_WINNER_MAX_DRAWDOWN_PCT": "winner_max_drawdown_pct",
    "TRADINGAGENTS_WINNER_ON_GATE_FAIL": "winner_on_gate_fail",
    "TRADINGAGENTS_OPTIMIZE_RISK_PARAMS": "optimize_risk_params",
    "BACKTEST_PREFER_BINANCE": "backtest_prefer_binance",
    "TRADINGAGENTS_OPTIMIZE_STRATEGY_PARAMS": "optimize_strategy_params",
    "TRADINGAGENTS_PARAM_SEARCH_SAMPLES": "param_search_samples",
    "TRADINGAGENTS_PARAM_SEARCH_MAX_RUNS": "param_search_max_runs",
    "TRADINGAGENTS_WALK_FORWARD_ENABLED": "walk_forward_enabled",
    "TRADINGAGENTS_WALK_FORWARD_VALIDATE_HOURS": "walk_forward_validate_hours",
}


def _coerce(value: str, reference):
    """Coerce env-var string to the type of the existing default value."""
    if isinstance(reference, bool):
        return value.strip().lower() in ("true", "1", "yes", "on")
    if isinstance(reference, int) and not isinstance(reference, bool):
        return int(value)
    if isinstance(reference, float):
        return float(value)
    return value


def _apply_env_overrides(config: dict) -> dict:
    """Apply TRADINGAGENTS_* env vars to the config dict in-place."""
    for env_var, key in _ENV_OVERRIDES.items():
        raw = os.environ.get(env_var)
        if raw is None or raw == "":
            continue
        config[key] = _coerce(raw, config.get(key))
    return config


DEFAULT_CONFIG = _apply_env_overrides({
    "project_dir": os.path.abspath(os.path.join(os.path.dirname(__file__), ".")),
    "results_dir": os.getenv("TRADINGAGENTS_RESULTS_DIR", os.path.join(_TRADINGAGENTS_HOME, "logs")),
    "data_cache_dir": os.getenv("TRADINGAGENTS_CACHE_DIR", os.path.join(_TRADINGAGENTS_HOME, "cache")),
    "memory_log_path": os.getenv("TRADINGAGENTS_MEMORY_LOG_PATH", os.path.join(_TRADINGAGENTS_HOME, "memory", "trading_memory.md")),
    # Optional cap on the number of resolved memory log entries. When set,
    # the oldest resolved entries are pruned once this limit is exceeded.
    # Pending entries are never pruned. None disables rotation entirely.
    "memory_log_max_entries": None,
    # LLM settings
    "llm_provider": "openai",
    "deep_think_llm": "gpt-5.5",
    "quick_think_llm": "gpt-5.4-mini",
    # When None, each provider's client falls back to its own default endpoint
    # (api.openai.com for OpenAI, generativelanguage.googleapis.com for Gemini, ...).
    # The CLI overrides this per provider when the user picks one. Keeping a
    # provider-specific URL here would leak (e.g. OpenAI's /v1 was previously
    # being forwarded to Gemini, producing malformed request URLs).
    "backend_url": None,
    # Provider-specific thinking configuration
    "google_thinking_level": None,      # "high", "minimal", etc.
    "openai_reasoning_effort": None,    # "medium", "high", "low"
    "anthropic_effort": None,           # "high", "medium", "low"
    # Sampling temperature, forwarded to every provider when set. None leaves
    # each provider at its own default. Lower values reduce run-to-run
    # variation on models that honor it; reasoning models largely ignore it
    # and no setting makes LLM output bit-identical across runs (see README).
    "temperature": None,
    # Checkpoint/resume: when True, LangGraph saves state after each node
    # so a crashed run can resume from the last successful step.
    "checkpoint_enabled": False,
    # Live execution: when True (or LIVE_MODE=1), backtest bridge uses ccxt
    # for real-time prices; otherwise dummy_feed mutates from last historical bar.
    "live_mode": False,
    # Paper trading simulation (no real orders)
    "paper_trade_enabled": False,
    "paper_loss_review_minutes": 60,
    "paper_loss_threshold_pct": 5.0,
    "paper_tick_interval_seconds": 10.0,
    "paper_initial_equity": 10_000.0,
    "paper_adaptive_enabled": True,
    "paper_state_persistence": True,
    "paper_stop_loss_pct": 0.02,
    "paper_take_profit_pct": None,
    # Winner gating for optimize_strategies / auto-deploy
    "winner_gate_enabled": True,
    "winner_min_net_profit": 0.0,
    "winner_min_trades": 3,
    "winner_max_drawdown_pct": 0.15,
    "winner_on_gate_fail": "keep",
    # Risk-parameter sweep during optimization (off by default)
    "optimize_risk_params": False,
    "optimize_risk_max_runs": 500,
    # Prefer Binance/ccxt before CryptoCompare for backtest OHLCV
    "backtest_prefer_binance": False,
    # Per-strategy parameter search during optimization (off by default)
    "optimize_strategy_params": False,
    "param_search_samples": 20,
    "param_search_max_runs": 600,
    # Walk-forward validation: train on older slice, require validate hold-out to pass gates
    "walk_forward_enabled": False,
    "walk_forward_validate_hours": 8,
    # Autonomous re-optimization (aliases used by adaptive monitor + CLI prompts)
    "drawdown_time_window_minutes": 60,
    "drawdown_max_lookback_minutes": 60,
    "backtest_cache_ttl_seconds": 0,
    "max_allowed_drawdown_pct": 5.0,
    # Output language for analyst reports and final decision
    # Internal agent debate stays in English for reasoning quality
    "output_language": "English",
    # Debate and discussion settings
    "max_debate_rounds": 1,
    "max_risk_discuss_rounds": 1,
    "max_recur_limit": 100,
    "analyst_concurrency_limit": 4,
    # Programmatic risk guard (post-PM veto layer)
    "max_stop_atr_multiple": 3.0,
    "max_position_pct": 10.0,
    "max_var_pct": 5.0,
    "max_concentration_pct": 15.0,
    "assumed_daily_vol_pct": 2.0,
    # News / data fetching parameters
    # Increase for longer lookback strategies or to broaden macro coverage;
    # decrease to reduce token usage in agent prompts.
    "news_article_limit": 20,             # max articles per ticker (ticker-news)
    "global_news_article_limit": 10,      # max articles for global/macro news
    "global_news_lookback_days": 7,       # macro news lookback window
    # Search queries used by get_global_news for macro headlines. Extend or
    # replace to broaden geographic / sector coverage.
    "global_news_queries": [
        "bitcoin ETF flows regulation SEC",
        "ethereum L2 DeFi protocol upgrades",
        "crypto macro Fed liquidity stablecoin",
        "altcoin season market structure dominance",
        "exchange hack exploit security incident",
    ],
    # Crypto data vendor configuration (category defaults; tool_vendors overrides per tool)
    "data_vendors": {
        "core_crypto_apis": "binance,cryptocompare",
        "technical_indicators": "binance",
        "fundamental_data": "coingecko",
        "news_data": "cryptocompare,lunarcrush",
    },
    "tool_vendors": {},
    # Benchmark for alpha calculation in the reflection layer (crypto pairs).
    # ``benchmark_ticker`` overrides auto-detection when set.
    "benchmark_ticker": None,
    "benchmark_map": {
        "BTC": "ETH/USDT",
        "ETH": "BTC/USDT",
        "SOL": "BTC/USDT",
        "": "BTC/USDT",
    },
})
