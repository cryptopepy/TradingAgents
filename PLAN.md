# TradingAgents Optimization Manifest

## System State
- Current Version: 0.3.0
- Global Concurrency Strategy: Parallel Fan-Out
- Asset Class: Crypto-only (no equities)
- Last Active Task: Task-5 — Unified Custom LLM Providers (AtlasCloud, Local)

## High-Priority Epic: Crypto-Only Framework Transition

Pure cryptocurrency research and trading engine — no equities, no yfinance/Alpha Vantage stock paths.

- [x] CRYPTO-1: Crypto data vendor layer (CoinGecko, Binance, CryptoCompare fallback via `route_to_vendor`)
- [x] CRYPTO-2: Symbol normalization for crypto pairs (`BTC/USDT`, `ETH/USDC`, `SOL/USD`)
- [x] CRYPTO-3: State & CLI — `asset_type` defaults to `crypto`, remove stock/crypto mode selection
- [x] CRYPTO-4: Analyst prompts & tools — perps/funding/OI, on-chain fundamentals, crypto sentiment/news
- [x] CRYPTO-5: Backtest engine — 24/7/365 continuous tracking, no market-hours gaps
- [x] CRYPTO-6: Tests — replace AAPL/NVDA/SPY fixtures with BTC/ETH/SOL pairs; pytest green
- [x] CRYPTO-7: Dependencies — remove yfinance; keep stockstats for indicator math on crypto OHLCV
- [x] CRYPTO-8: Graph, risk guard, benchmark — BTC vs ETH baseline; end-to-end crypto symbols

### Crypto Epic — Files Touched (commit `ca2944e`)
- **Data:** `coingecko.py`, `binance.py`, `cryptocompare.py`, `crypto_candles.py`, `crypto_news.py`, `lunarcrush.py`, `onchain_metrics.py`, `perps_data.py`, `symbol_utils.py`, `interface.py`
- **Agents:** `market_analyst.py`, `fundamentals_analyst.py`, `sentiment_analyst.py`, `news_analyst.py`, `crypto_price_tools.py`
- **Core:** `default_config.py`, `trading_graph.py`, `backtest/engine.py`, `cli/main.py`, `pyproject.toml`
- **Removed:** Alpha Vantage modules, yfinance paths, `stocktwits.py`, equity `core_stock_tools.py`

### Follow-up / Technical Debt
- [x] CRYPTO-9: Remove residual `asset_type == "stock"` branches in `bull_researcher.py` / `bear_researcher.py`
- [x] CRYPTO-10: Document API keys in `.env.example` (CoinGecko, LunarCrush, CryptoCompare optional keys)

## Implementation Checklist
- [x] Task-1: Core Path Unification & CLI Streaming Restructuring
- [x] Task-2: Parallelizing Analyst Execution Nodes via LangGraph Fan-Out
- [x] Task-3: Point-In-Time Historical Data Pipeline Correction (Fixing Look-Ahead Bias)
- [x] Task-4: Backtest Engine Integration (Historic-Crypto, strategies, optimization, UI)
- [x] Task-5: Unified Custom LLM Providers (AtlasCloud, Local LLM)
- [x] Task-6: Programmatic Risk Guard and Veto Layer Enforcer
- [x] Task-7: Structural Cleanup, Error Resilience, & Test Coverage Verification

## Active Task Logs

### Task-1: Core Path Unification & CLI Streaming Restructuring
- **Status:** Completed
- `cli/main.py` calls `TradingAgentsGraph.propagate()` with `stream_callback` and `callbacks`
- `past_context`, `memory_log.store_decision()`, JSON `full_states_log` on CLI path

### Task-2: Parallelizing Analyst Execution Nodes via LangGraph Fan-Out
- **Status:** Completed
- `setup.py` fans out from `START` via LangGraph `Send`; `Analyst Join` before Bull Researcher
- `analyst_concurrency_limit` enforced with `threading.Semaphore`

### Task-3: Point-In-Time Historical Data Pipeline Correction
- **Status:** Completed (superseded for crypto by `sentiment_pit.py` + historical sentiment guards)
- Legacy equity publication-lag logic removed with stock dataflows

### Task-4: Backtest Engine Integration
- **Status:** Completed
- [x] `Historic-Crypto` dependency + `uv lock`
- [x] `tradingagents/backtest/engine.py` — Historic_Crypto fetch, CSV cache, 8h/24h/7d horizons
- [x] `tradingagents/backtest/strategies.py` — EMA, RSI, MACD, Bollinger (no LLM)
- [x] Optimization loop — profit factor, Sharpe, max drawdown, net profit ratio; Pydantic schemas
- [x] CLI dispatch — `backtest_report` section, `tradingagents backtest` command, post-analysis hook
- [x] Live bridge — `LIVE_MODE` / `live_mode`, ccxt Binance ticker, `dummy_feed.py` fallback
- [x] `tests/test_backtester.py` — synthetic series, strategy scoring

#### Advanced Alpha Strategies (E–J) & Paper Trading Architecture
- **Status:** Completed
- [x] Strategies E–J in `strategies.py` — CMO, ADX, VWAP bands, CCI, TRIX, APO (vectorized, no LLM)
- [x] `STRATEGY_REGISTRY` / `build_strategy` factory — all 10 strategies (A–J) in optimization loop
- [x] `tradingagents/backtest/portfolio.py` — `TransactionIntent`, `VirtualPortfolio`, `signals_to_intents`
- [x] `tradingagents/backtest/matcher.py` — `SimulatedMatcher` with slippage, limit-order stub, live/dummy feed
- [x] Engine wired to `VirtualPortfolio` + `SimulatedMatcher` for position tracking (decoupled from signal math)
- [x] Extended `tests/test_backtester.py` — indicator unit tests, signal boundaries, portfolio intents

### Task-5: Unified Custom LLM Providers
- **Status:** Completed
- [x] AtlasCloud.ai — `atlascloud` provider, `ATLASCLOUD_API_KEY`, `https://api.atlascloud.ai/v1`
- [x] Local / Custom OpenAI — `local` provider, `LOCAL_LLM_BASE_URL`, `LOCAL_LLM_API_KEY`, `LOCAL_LLM_MODEL_NAME`
- [x] `factory.py`, `openai_client.py`, `api_key_env.py`, `model_catalog.py`, CLI provider table
- [x] `.env.example` documentation

### Task-6: Programmatic Risk Guard and Veto Layer
- **Status:** Completed
- `tradingagents/risk/guard.py` wired after Portfolio Manager

### Task-7: Structural Cleanup, Error Resilience, & Test Coverage
- **Status:** Completed
- `structured.py` fallback formatting; `tests/test_graph_e2e_integration.py` and crypto unit tests
