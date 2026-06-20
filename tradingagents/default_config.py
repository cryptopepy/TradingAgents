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
    "TRADINGAGENTS_PAPER_SPIKE_REVIEW_ENABLED": "paper_spike_review_enabled",
    "TRADINGAGENTS_PAPER_SPIKE_1M_LOSS_PCT": "paper_spike_1m_loss_pct",
    "TRADINGAGENTS_PAPER_SPIKE_5M_LOSS_PCT": "paper_spike_5m_loss_pct",
    "TRADINGAGENTS_PAPER_SPIKE_10M_LOSS_PCT": "paper_spike_10m_loss_pct",
    "TRADINGAGENTS_PAPER_SPIKE_MIN_COOLDOWN_MINUTES": "paper_spike_min_cooldown_minutes",
    "TRADINGAGENTS_PAPER_SPIKE_SWITCH_MIN_NET_PROFIT": "paper_spike_switch_min_net_profit",
    "TRADINGAGENTS_PAPER_SPIKE_INTELLIGENT_TUNING": "paper_spike_intelligent_tuning_enabled",
    "TRADINGAGENTS_DRAWDOWN_TIME_WINDOW": "drawdown_time_window_minutes",
    "TRADINGAGENTS_DRAWDOWN_MAX_LOOKBACK_MINUTES": "drawdown_max_lookback_minutes",
    "TRADINGAGENTS_MAX_ALLOWED_DRAWDOWN_PCT": "max_allowed_drawdown_pct",
    "BACKTEST_CACHE_TTL_SECONDS": "backtest_cache_ttl_seconds",
    "TRADINGAGENTS_PAPER_STATE_ENABLED": "paper_state_persistence",
    "TRADINGAGENTS_PAPER_STOP_LOSS_PCT": "paper_stop_loss_pct",
    "TRADINGAGENTS_PAPER_TAKE_PROFIT_PCT": "paper_take_profit_pct",
    "TRADINGAGENTS_PAPER_LEVERAGE": "paper_leverage",
    "TRADINGAGENTS_WINNER_GATE_ENABLED": "winner_gate_enabled",
    "TRADINGAGENTS_WINNER_MIN_NET_PROFIT": "winner_min_net_profit",
    "TRADINGAGENTS_WINNER_MIN_TRADES": "winner_min_trades",
    "TRADINGAGENTS_WINNER_MAX_DRAWDOWN_PCT": "winner_max_drawdown_pct",
    "TRADINGAGENTS_WINNER_ON_GATE_FAIL": "winner_on_gate_fail",
    "TRADINGAGENTS_OPTIMIZE_RISK_PARAMS": "optimize_risk_params",
    "BACKTEST_PREFER_BINANCE": "backtest_prefer_binance",
    "BACKTEST_SKIP_CRYPTOCOMPARE": "backtest_skip_cryptocompare",
    "BACKTEST_CCXT_EXCHANGES": "backtest_ccxt_exchanges",
    "TRADINGAGENTS_OPTIMIZE_STRATEGY_PARAMS": "optimize_strategy_params",
    "TRADINGAGENTS_PARAM_SEARCH_SAMPLES": "param_search_samples",
    "TRADINGAGENTS_PARAM_SEARCH_MAX_RUNS": "param_search_max_runs",
    "TRADINGAGENTS_WALK_FORWARD_ENABLED": "walk_forward_enabled",
    "TRADINGAGENTS_WALK_FORWARD_VALIDATE_HOURS": "walk_forward_validate_hours",
    "TRADINGAGENTS_POSITION_SIZE_PCT": "position_size_pct",
    "TRADINGAGENTS_ATR_POSITION_SIZING": "atr_position_sizing",
    "TRADINGAGENTS_MIN_BARS_BETWEEN_TRADES": "min_bars_between_trades",
    "TRADINGAGENTS_REGIME_FILTER_ENABLED": "regime_filter_enabled",
    "TRADINGAGENTS_WINNER_SCORE_MODE": "winner_score_mode",
    "TRADINGAGENTS_WINNER_SELECTION_MODE": "winner_selection_mode",
    "TRADINGAGENTS_WINNER_REQUIRE_LONG_HORIZON": "winner_require_long_horizon",
    "TRADINGAGENTS_ATR_STOPS_ENABLED": "atr_stops_enabled",
    "TRADINGAGENTS_MIN_EDGE_FILTER_ENABLED": "min_edge_filter_enabled",
    "TRADINGAGENTS_MIN_EDGE_FEE_MULTIPLE": "min_edge_fee_multiple",
    "TRADINGAGENTS_MAJOR_RISK_VARIANTS_ENABLED": "major_risk_variants_enabled",
    "TRADINGAGENTS_ALT_AUTO_RICH_OPTIMIZATION": "alt_auto_rich_optimization",
    "TRADINGAGENTS_ALT_PARAM_SEARCH_SAMPLES": "alt_param_search_samples",
    "TRADINGAGENTS_ALT_WALK_FORWARD_ENABLED": "alt_walk_forward_enabled",
    "TRADINGAGENTS_ALT_EXPAND_RISK_VARIANTS": "alt_expand_risk_variants",
    "TRADINGAGENTS_PAPER_TRANSACTION_COST_PCT": "paper_transaction_cost_pct",
    "TRADINGAGENTS_PAPER_ALT_FEE_MULTIPLIER": "paper_alt_fee_multiplier",
    "TRADINGAGENTS_MOVERS_DISPLAY_LIMIT": "movers_display_limit",
    "TRADINGAGENTS_MOVERS_MIN_VOLUME_USD": "movers_min_volume_usd",
    "TRADINGAGENTS_MOVERS_CACHE_TTL_SECONDS": "movers_cache_ttl_seconds",
    "TRADINGAGENTS_MOVERS_PROVIDER": "movers_provider",
    "TRADINGAGENTS_FILE_LOGGING_ENABLED": "file_logging_enabled",
    "TRADINGAGENTS_LOG_FILE": "log_file_path",
    "TRADINGAGENTS_LOG_LEVEL": "log_level",
    "TRADINGAGENTS_PAPER_JOURNAL_ENABLED": "paper_journal_enabled",
    "TRADINGAGENTS_PAPER_JOURNAL_FILE": "paper_journal_path",
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


_BASE_CONFIG = {
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
    "paper_tick_interval_seconds": 3.0,
    "paper_initial_equity": 10_000.0,
    "paper_adaptive_enabled": True,
    # Fast-movement early review (requires adaptive on; lookback-aware windows)
    "paper_spike_review_enabled": True,
    "paper_spike_1m_loss_pct": 1.5,
    "paper_spike_5m_loss_pct": 2.0,
    "paper_spike_10m_loss_pct": 2.5,
    "paper_spike_min_cooldown_minutes": None,
    "paper_spike_switch_min_net_profit": 0.005,
    "paper_spike_intelligent_tuning_enabled": True,
    "paper_status_heartbeat_minutes": 10.0,
    "paper_state_persistence": True,
    "paper_stop_loss_pct": 0.02,
    "paper_take_profit_pct": None,
    "paper_leverage": 1.0,
    # Winner gating for optimize_strategies / auto-deploy
    "winner_gate_enabled": True,
    "winner_min_net_profit": 0.0,
    "winner_min_trades": 3,
    "winner_max_drawdown_pct": 0.15,
    "winner_on_gate_fail": "keep",
    # Risk-parameter sweep during optimization (off by default)
    "optimize_risk_params": False,
    "optimize_risk_max_runs": 500,
    # Prefer Binance/ccxt before CryptoCompare for backtest OHLCV (legacy flag; ccxt is always first now).
    "backtest_prefer_binance": False,
    # Omit CryptoCompare from the OHLCV chain entirely (off by default — it runs last as fallback).
    "backtest_skip_cryptocompare": False,
    # ccxt exchange order for OHLCV + live spot (Kraken/Coinbase before Binance).
    "backtest_ccxt_exchanges": "kraken,coinbase,binance",
    # Per-strategy parameter search during optimization (off by default)
    "optimize_strategy_params": False,
    "param_search_samples": 20,
    "param_search_max_runs": 600,
    # Walk-forward validation: train on older slice, require validate hold-out to pass gates
    "walk_forward_enabled": False,
    "walk_forward_validate_hours": 8,
    # Signal filters and sizing (off by default — preserves current behavior)
    "position_size_pct": 1.0,
    "atr_position_sizing": False,
    "atr_target_pct": 0.02,
    "min_bars_between_trades": 0,
    "regime_filter_enabled": False,
    "winner_score_mode": "composite",
    "winner_selection_mode": "multi_horizon",
    "winner_require_long_horizon": True,
    "winner_horizon_weights": {"8h": 0.35, "24h": 1.0, "7d": 2.5},
    # ATR stops, min-edge filter, and risk-knob sweeps (enabled via enrich_optimization_config)
    "atr_stops_enabled": False,
    "atr_period": 14,
    "atr_stop_min_pct": 0.008,
    "atr_stop_max_pct": 0.06,
    "min_edge_filter_enabled": False,
    "min_edge_fee_multiple": 3.0,
    "major_risk_variants_enabled": True,
    "alt_auto_rich_optimization": True,
    "alt_param_search_samples": 12,
    "alt_walk_forward_enabled": True,
    "alt_expand_risk_variants": True,
    # Paper trading fees — majors use base; alts multiply by paper_alt_fee_multiplier
    "paper_transaction_cost_pct": 0.001,
    "paper_alt_fee_multiplier": 2.0,
  # CoinGecko 24h movers board (paper trading pair picker)
    "movers_display_limit": 5,
    "movers_min_volume_usd": 250_000,
    "movers_duration": "24h",
    "movers_top_coins": "500",
    "movers_cache_ttl_seconds": 300,
    "movers_provider": "kraken",
    # Rotating debug log + session/trade journal (both enabled by default)
    "file_logging_enabled": True,
    "log_file_path": None,
    "log_level": "INFO",
    "log_file_max_bytes": 5_000_000,
    "log_file_backup_count": 3,
    # Session start/stop and trade journal (enabled by default)
    "paper_journal_enabled": True,
    "paper_journal_path": None,
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
}

DEFAULT_CONFIG = _apply_env_overrides(_BASE_CONFIG)
