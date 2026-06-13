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

## Epic: Paper Trading & Adaptive Simulation (v0.3.x)

Simulated trading is the primary product surface; LLM analysis feeds optional context.

- [x] PAPER-1: Live price layer — `live_prices.py` (CryptoCompare → CoinGecko → Binance → placeholder)
- [x] PAPER-2: `PaperTradingEngine` — portfolio tracking, signal refresh, trade history
- [x] PAPER-3: `AdaptiveStrategyMonitor` — drawdown window, auto `optimize_strategies`, strategy switch
- [x] PAPER-4: CLI — `tradingagents paper`, `backtest --paper`, post-analysis menu
- [x] PAPER-5: TUI — Rich live portfolio table during paper session
- [x] PAPER-6: Config — `TRADINGAGENTS_PAPER_*` env overrides in `default_config.py`
- [x] PAPER-7: Tests — `test_live_prices`, `test_paper_engine`, `test_adaptive`

### Paper Epic — Key Files
- **Data:** `live_prices.py`, `cryptocompare.fetch_spot_price`, `coingecko.get_simple_price`
- **Engine:** `simulator/paper_engine.py`, `simulator/adaptive.py`, `simulator/core.py`
- **CLI:** `cli/paper_trading.py`, `cli/post_analysis.py`, `cli/main.py` (`paper`, `backtest --paper`)
- **Config:** `.env.example` paper-trading section

### Follow-up
- [ ] PAPER-8: Persist paper session state to disk (resume across restarts) — **done in P3-4**
- [ ] PAPER-9: Web UI (Streamlit) for portfolio dashboard

## Epic: Strategy & Simulation Improvements (IMPROVE)

See **`PLAN-IMPROVE.md`** for the full implementation blueprint (backtest/paper parity, winner gating, unified feed, param search). Spot-only; futures excluded.

- [x] IMPROVE-1: Backtest/paper parity (take-profit, adaptive risk params, lookback refresh)
- [x] IMPROVE-2: Winner gating (min profit, min trades, max drawdown)
- [x] IMPROVE-3: Unified spot price pipeline (`BACKTEST_PREFER_BINANCE`)
- [x] IMPROVE-4: Risk parameter sweep in optimizer
- [x] IMPROVE-5: Per-strategy parameter optimization (opt-in)
- [x] IMPROVE-6: Walk-forward validation (opt-in)

## Epic: Multi-Phase Platform Refinement (v0.4.x)

Atomic commits per phase: `feat/P{n}-*: ...` — do not bundle phases.

### Phase 1 — Interactive UI & Multi-Strategy Backtest Harness (`feat/P1-*`)
- [x] P1-1: Update PLAN.md with full blueprint and task IDs
- [x] P1-2: Fix bare `tradingagents backtest` — validation, no silent empty exits
- [x] P1-3: Interactive prompts (questionary/rich) for ticker, date, horizons, equity, risk
- [x] P1-4: Post-analysis menu — `> Run Historical Optimization Backtest` selection loop
- [x] P1-5: Rich results table sorted by profit factor, max drawdown, net return; WINNER first
- [x] P1-6: Tests — `test_backtest_validation.py`, post-analysis table/menu updates

### Phase 2 — Live Market Feed Integration (`feat/P2-*`)
- [x] P2-1: Unified router `tradingagents/dataflows/live_feed.py` (wrap/refactor `live_prices.py`)
- [x] P2-2: Parse `COINGECKO_API_KEY`, `CRYPTOCOMPARE_API_KEY` from env
- [x] P2-3: CoinGecko — metadata, circulating supply, global market cap
- [x] P2-4: CryptoCompare — minute/hourly REST tickers (WebSocket if feasible)
- [x] P2-5: Resilient 429/network fallback — localized mock ticker from last anchor
- [x] P2-6: Tests — `test_live_feed.py` fallback and vendor routing

### Phase 3 — High-Fidelity Paper Trading (`feat/P3-*`)
- [x] P3-1: `VirtualPortfolio` in `simulator/core.py` — cash ($100k default), long/short margin, slippage, fees
- [x] P3-2: Post-backtest prompt — `> Deploy Optimal Strategy to Live Paper Trading Simulator`
- [x] P3-3: Background async/daemon loop monitoring live feed, executing winning strategy rules
- [x] P3-4: PAPER-8 — persist portfolio state locally (JSON or SQLite)
- [x] P3-5: Tests — `VirtualPortfolio`, paper session persistence

### Phase 4 — Closed-Loop Autonomous Re-Optimization (`feat/P4-*`)
- [x] P4-1: Trailing performance watchdog in simulation loop
- [x] P4-2: Config — `DRAWDOWN_TIME_WINDOW`, `MAX_ALLOWED_DRAWDOWN_PCT` in `default_config.py`
- [x] P4-3: On breach — halt signals, fresh historical slice, re-run 10-strategy optimization, swap strategy
- [x] P4-4: Log `[AUTONOMOUS ROTATION]: Strategy changed from [Old] to [New] due to threshold violation.`
- [x] P4-5: Runtime-adjustable thresholds (CLI prompts + config; LLM override hooks where natural)
- [x] P4-6: Tests — rotation logging, drawdown breach triggers

### Phase 5 — README Alignment (`feat/P5-*`)
- [x] P5-1: README overhaul — analyzer → algorithmic paper trading platform evolution
- [x] P5-2: Document all config keys (required vs optional)
- [x] P5-3: Step-by-step guides — analyst flow, interactive backtester, autonomous re-optimization, virtual portfolio UI

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

#### Task-4.1: UI Pipeline Backtest Trigger
- **Status:** Completed
- Post-analysis questionary menu after Portfolio Manager (no automatic backtest)
- Options: auto multi-horizon backtest, custom parameters, main menu, exit
- `rich.progress` during 10-strategy optimization; results `rich.table` with WINNER
- `--no-backtest` hides backtest menu options; user consent required for optimization

#### Task-4.2: Paper Trading Simulator Scaffolding
- **Status:** Completed
- `tradingagents/simulator/core.py` — `AssetPosition`, `VirtualPortfolio` reuse, `evaluate_live_market_tick`
- LIVE_MODE → ccxt; else `DummyPriceFeed` polling hook
- CLI deploy prompt wires winning strategy params into paper simulator scaffold
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
