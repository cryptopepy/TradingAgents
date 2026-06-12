# TradingAgents Optimization Manifest

## System State
- Current Version: 0.2.5
- Global Concurrency Strategy: Parallel Fan-Out
- Last Active Task: Task-6

## Implementation Checklist
- [ ] Task-1: Core Path Unification & CLI Streaming Restructuring
- [ ] Task-2: Parallelizing Analyst Execution Nodes via LangGraph Fan-Out
- [ ] Task-3: Point-In-Time Historical Data Pipeline Correction (Fixing Look-Ahead Bias)
- [ ] Task-4: Mathematical Strategy Backtesting Engine Implementation (Placeholder API)
- [ ] Task-5: Programmatic Risk Guard and Veto Layer Enforcer
- [ ] Task-6: Structural Cleanup, Error Resilience, & Test Coverage Verification

## Active Task Logs

### Task-1: Core Path Unification & CLI Streaming Restructuring
- Refactor `cli/main.py` to call `TradingAgentsGraph.propagate()` with streaming callback
- Add `stream_callback` and `callbacks` parameters to `propagate()` / `_run_graph()`
- Ensure `past_context`, `memory_log.store_decision()`, JSON full-state logging work from CLI

### Task-2: Parallelizing Analyst Execution Nodes via LangGraph Fan-Out
- Fan-out from START via LangGraph `Send` API to selected analysts
- Add `Analyst Join` barrier node before Bull Researcher
- Honor `analyst_concurrency_limit` via threading semaphore on analyst agent nodes

### Task-3: Point-In-Time Historical Data Pipeline Correction
- Add publication lag (45d 10-Q, 90d 10-K) to `filter_financials_by_date`
- Guard StockTwits/Reddit/sentiment analyst for historical trade dates

### Task-4: Mathematical Strategy Backtesting Engine
- Create `tradingagents/backtest/engine.py` with placeholder price API and RSI/MACD rules

### Task-5: Programmatic Risk Guard and Veto Layer
- Create `tradingagents/risk/guard.py` and wire after Portfolio Manager

### Task-6: Structural Cleanup, Error Resilience, & Test Coverage
- Remove unused `redis`/`backtrader` deps
- Extend `yf_retry` and `structured.py` fallback formatting
- Add `tests/test_graph_e2e_integration.py`
