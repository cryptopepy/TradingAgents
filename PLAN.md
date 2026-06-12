# TradingAgents Optimization Manifest

## System State
- Current Version: 0.2.5
- Global Concurrency Strategy: Parallel Fan-Out
- Last Active Task: Task-6

## Implementation Checklist
- [x] Task-1: Core Path Unification & CLI Streaming Restructuring
- [x] Task-2: Parallelizing Analyst Execution Nodes via LangGraph Fan-Out
- [x] Task-3: Point-In-Time Historical Data Pipeline Correction (Fixing Look-Ahead Bias)
- [x] Task-4: Mathematical Strategy Backtesting Engine Implementation (Placeholder API)
- [x] Task-5: Programmatic Risk Guard and Veto Layer Enforcer
- [x] Task-6: Structural Cleanup, Error Resilience, & Test Coverage Verification

## Active Task Logs

### Task-1: Core Path Unification & CLI Streaming Restructuring
- `cli/main.py` now calls `TradingAgentsGraph.propagate()` with `stream_callback` and `callbacks`
- `propagate()` / `_run_graph()` accept `stream_callback` for Rich TUI streaming and forward tool callbacks
- `past_context`, `memory_log.store_decision()`, and JSON `full_states_log` run on the CLI path

### Task-2: Parallelizing Analyst Execution Nodes via LangGraph Fan-Out
- `setup.py` fans out from `START` via LangGraph `Send` to all selected analysts
- `Analyst Join` barrier resets messages before Bull Researcher
- `analyst_concurrency_limit` enforced with `threading.Semaphore` on analyst agent nodes

### Task-3: Point-In-Time Historical Data Pipeline Correction
- `filter_financials_by_date` applies 45d (10-Q) / 90d (10-K) publication lag
- `stocktwits.py`, `reddit.py`, `sentiment_analyst.py` return `NO_HISTORICAL_SENTIMENT_DATA` for historical trade dates

### Task-4: Mathematical Strategy Backtesting Engine
- `tradingagents/backtest/engine.py`: `fetch_historical_price_slice`, RSI/MACD `run_strategy_backtest`
- Supports lookback windows `8h`, `24h`, `7d`; long/short, stop-loss, transaction costs

### Task-5: Programmatic Risk Guard and Veto Layer
- `tradingagents/risk/guard.py`: ATR stop, position sizing, VaR/concentration checks
- `Risk Guard` node wired after Portfolio Manager; overrides to Hold on violation

### Task-6: Structural Cleanup, Error Resilience, & Test Coverage
- Removed unused `redis` and `backtrader` from `pyproject.toml`
- `structured.py` appends markdown key suffixes on free-text fallback
- `yf_retry` retries socket timeouts, connection drops, HTTP 5xx
- Added `tests/test_graph_e2e_integration.py` and unit tests for risk, backtest, PIT data
