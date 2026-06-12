# TradingAgents Optimization Manifest

## System State
- Current Version: 0.3.0
- Global Concurrency Strategy: Parallel Fan-Out
- Asset Class: Crypto-only (no equities)
- Last Active Task: Crypto-Only Framework Transition (committed `ca2944e`)

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
- [ ] CRYPTO-9: Remove residual `asset_type == "stock"` branches in `bull_researcher.py` / `bear_researcher.py`
- [ ] CRYPTO-10: Document API keys in `.env.example` (CoinGecko, LunarCrush, CryptoCompare optional keys)

## Implementation Checklist
- [x] Task-1: Core Path Unification & CLI Streaming Restructuring
- [x] Task-2: Parallelizing Analyst Execution Nodes via LangGraph Fan-Out
- [x] Task-3: Point-In-Time Historical Data Pipeline Correction (Fixing Look-Ahead Bias)
- [x] Task-4: Mathematical Strategy Backtesting Engine Implementation (Placeholder API)
- [x] Task-5: Programmatic Risk Guard and Veto Layer Enforcer
- [x] Task-6: Structural Cleanup, Error Resilience, & Test Coverage Verification

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

### Task-4: Mathematical Strategy Backtesting Engine
- **Status:** Completed
- `tradingagents/backtest/engine.py`: RSI/MACD rules, 24/7 continuous bars, lookback `8h`/`24h`/`7d`

### Task-5: Programmatic Risk Guard and Veto Layer
- **Status:** Completed
- `tradingagents/risk/guard.py` wired after Portfolio Manager

### Task-6: Structural Cleanup, Error Resilience, & Test Coverage
- **Status:** Completed
- `structured.py` fallback formatting; `tests/test_graph_e2e_integration.py` and crypto unit tests
