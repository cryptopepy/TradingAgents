# Phase 1 Changes — Core Path Unification & Optimization Work

**Status:** Uncommitted working tree (optimization branch work on `main`)  
**Scope:** Primary focus is **Phase 1: Core Path Unification & CLI Streaming Restructuring**. Additional phases from the optimization manifest were also implemented in the same changeset (see [Beyond Phase 1](#beyond-phase-1)).

---

## Executive Summary

The CLI and programmatic entry points previously duplicated graph initialization, streaming, and post-run persistence logic. The CLI built its own initial state, called `graph.stream()` directly, and merged chunks locally—bypassing `TradingAgentsGraph.propagate()`. That meant memory-log writes, JSON full-state logging, checkpoint lifecycle, and `past_context` injection could diverge between the CLI and API paths.

**Phase 1 unifies execution on `propagate()`** by adding optional `stream_callback` and `callbacks` parameters. The CLI now passes a Rich TUI handler as `stream_callback` and receives `(final_state, decision)` from the same code path used by tests and programmatic callers.

In the same optimization pass, the graph was extended with **parallel analyst fan-out**, a **programmatic risk guard**, **point-in-time data guards** for sentiment and financials, a **placeholder backtest engine**, dependency cleanup, and new unit/integration tests.

### Why it matters

| Before | After |
|--------|-------|
| CLI duplicated state init + streaming | Single `propagate()` path for CLI and code |
| Memory log / JSON logs only reliable on `propagate()` | CLI runs get the same persistence guarantees |
| Analysts ran sequentially | Analysts fan out from `START` with semaphore-limited concurrency |
| No post-PM mechanical risk checks | `Risk Guard` node can veto/scale PM output |
| Live sentiment used for historical dates | Historical `trade_date` returns a explicit placeholder |
| Financials filtered by fiscal period only | 45d/90d SEC publication lag applied |

---

## Phase 1: Core Path Unification & CLI Streaming

### `TradingAgentsGraph.propagate()` API

`propagate()` now accepts:

- **`stream_callback`** — Callable receiving each streamed state chunk (`stream_mode="values"`). When provided (or when `debug=True`), `_run_graph()` uses `graph.stream()` instead of `graph.invoke()`.
- **`callbacks`** — LangChain callbacks forwarded to `Propagator.get_graph_args()` for tool-execution tracking (CLI passes `stats_handler`).

Return value is unchanged: **`(final_state, processed_signal)`**.

```python
from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG

graph = TradingAgentsGraph(selected_analysts=["market", "news"], config=DEFAULT_CONFIG)

chunks = []

def on_chunk(chunk):
    chunks.append(chunk)
    # e.g. update UI from chunk["market_report"], chunk["messages"], etc.

final_state, decision = graph.propagate(
    "NVDA",
    "2026-01-10",
    asset_type="stock",
    stream_callback=on_chunk,
    callbacks=[],  # optional LangChain callbacks
)
```

### CLI changes (`cli/main.py`)

- Removed inline `create_initial_state` / `get_graph_args` / `graph.stream()` loop.
- Extracted chunk handling into **`process_stream_chunk()`**, passed as `stream_callback` to `graph.propagate()`.
- Removed unused import `get_initial_analyst_node`.
- **`update_analyst_statuses()`** accepts `parallel=` so all selected analysts show `in_progress` when `analyst_concurrency_limit > 1`.
- On run start, all selected analysts are marked `in_progress` when parallel mode is active.

Streaming behavior for the Rich TUI is unchanged from the user’s perspective; only the underlying execution path changed.

### Persistence guaranteed on CLI path

Because the CLI now calls `propagate()`, every CLI run also:

1. Resolves pending memory-log entries for the ticker (`_resolve_pending_entries`).
2. Injects **`past_context`** from `TradingMemoryLog` into initial state.
3. Writes **`full_states_log_{trade_date}.json`** under `{results_dir}/{TICKER}/TradingAgentsStrategy_logs/`.
4. Appends a **pending** decision to **`trading_memory.md`** via `memory_log.store_decision()`.
5. Clears checkpoints on successful completion when `checkpoint_enabled` is set.

---

## File-by-File Change List

### Phase 1 (core path)

| File | Change |
|------|--------|
| `cli/main.py` | Route analysis through `graph.propagate(..., stream_callback=process_stream_chunk, callbacks=[stats_handler])`; parallel-aware analyst status updates |
| `tradingagents/graph/trading_graph.py` | Add `stream_callback` / `callbacks` to `propagate()` and `_run_graph()`; stream when `debug` or callback present; forward callbacks to propagator |

### Beyond Phase 1

| File | Change |
|------|--------|
| `tradingagents/graph/setup.py` | Parallel fan-out via LangGraph `Send` from `START`; `Analyst Join` barrier; semaphore-wrapped analyst nodes; `Risk Guard` node after Portfolio Manager |
| `tradingagents/graph/analyst_execution.py` | `sync_analyst_tracker_from_chunk(..., parallel=False)` marks all pending analysts started when parallel |
| `tradingagents/default_config.py` | `analyst_concurrency_limit` default **4** (was 1); risk guard config keys added |
| `tradingagents/risk/guard.py` | **New.** Post-PM programmatic risk validation (ATR stop, position %, VaR proxy, concentration) |
| `tradingagents/risk/__init__.py` | **New.** Package init |
| `tradingagents/backtest/engine.py` | **New.** RSI/MACD rule backtest with `LookbackWindow` (8h/24h/7d), stops, transaction costs |
| `tradingagents/backtest/__init__.py` | **New.** Package init |
| `tradingagents/dataflows/sentiment_pit.py` | **New.** `is_historical_trade_date()`, `NO_HISTORICAL_SENTIMENT_DATA` constant |
| `tradingagents/dataflows/reddit.py` | `trade_date` param; skip live fetch for historical dates |
| `tradingagents/dataflows/stocktwits.py` | `trade_date` param; skip live fetch for historical dates |
| `tradingagents/dataflows/stockstats_utils.py` | Extended `yf_retry` for transient network/HTTP errors; `filter_financials_by_date()` applies 45d/90d publication lag |
| `tradingagents/agents/analysts/sentiment_analyst.py` | Pass `trade_date=end_date` to StockTwits/Reddit fetchers |
| `tradingagents/agents/utils/structured.py` | Append fallback markdown markers when structured output degrades to free text |
| `pyproject.toml` | Removed unused dependencies `backtrader`, `redis` |
| `tests/test_graph_e2e_integration.py` | **New.** Unified `propagate()` path, parallel join + risk guard nodes |
| `tests/test_filter_financials_lag.py` | **New.** Publication lag filtering |
| `tests/test_sentiment_pit.py` | **New.** Historical sentiment guards |
| `tests/test_risk_guard.py` | **New.** Risk guard approval/veto behavior |
| `tests/test_backtest_engine.py` | **New.** Backtest engine smoke tests |

---

## Usage Hints

### Running the CLI

```bash
# Standard interactive analysis
tradingagents analyze

# Enable checkpoint/resume (SQLite per ticker under data_cache_dir)
tradingagents analyze --checkpoint

# Force fresh run (delete saved checkpoints first)
tradingagents analyze --clear-checkpoints --checkpoint
```

Entry point: `tradingagents = "cli.main:app"` in `pyproject.toml`.

### `propagate()` behavior

| Concern | Behavior |
|---------|----------|
| **Streaming** | Uses `graph.stream()` when `stream_callback` is set or `debug=True`; otherwise `graph.invoke()` |
| **Callbacks** | `callbacks` argument overrides instance `self.callbacks` for that run |
| **Checkpoints** | When `config["checkpoint_enabled"]` is true, recompiles with SqliteSaver; thread ID = hash of `{ticker}:{date}`; cleared on success |
| **Memory log** | Default path: `~/.tradingagents/memory/trading_memory.md` (override: `TRADINGAGENTS_MEMORY_LOG_PATH`) |
| **Results JSON** | `{results_dir}/{TICKER}/TradingAgentsStrategy_logs/full_states_log_{date}.json` |
| **Return** | `(final_state: dict, decision: str)` where `decision` is `process_signal(final_trade_decision)` |

### Parallel analysts

Set in config or environment (if exposed):

```python
config["analyst_concurrency_limit"] = 4  # default in DEFAULT_CONFIG
```

- Graph fans out to all selected analysts from `START`.
- A threading semaphore limits concurrent analyst LLM calls to this value.
- Branches converge at **`Analyst Join`** before Bull Researcher.

### Risk guard

Configured via `DEFAULT_CONFIG` keys:

- `max_stop_atr_multiple` (default 3.0)
- `max_position_pct` (10.0)
- `max_var_pct` (5.0)
- `max_concentration_pct` (15.0)
- `assumed_daily_vol_pct` (2.0)

Runs after Portfolio Manager; on violation may override `final_trade_decision` to Hold (Buy/Overweight) or append a notice.

### Backtest engine (programmatic)

```python
from tradingagents.backtest.engine import LookbackWindow, run_strategy_backtest

result = run_strategy_backtest(
    "NVDA",
    end_date="2026-01-10",
    lookback=LookbackWindow.D7,
    allow_short=True,
    stop_loss_pct=0.02,
)
print(result.total_return_pct, result.num_trades, result.win_rate)
```

Uses daily OHLCV via `load_ohlcv`; intraday windows are approximated from hour counts.

### Historical sentiment

For `trade_date` before yesterday, StockTwits and Reddit return:

```
<NO_HISTORICAL_SENTIMENT_DATA: StockTwits and Reddit APIs provide live data only; ...>
```

---

## Migration Notes / Breaking Changes

### Behavioral changes

1. **`analyst_concurrency_limit` default is now `4`** (was `1`). Sequential-only behavior requires explicitly setting `analyst_concurrency_limit: 1` in config.
2. **Graph topology changed:** analysts no longer chain sequentially; they run in parallel (subject to semaphore). Downstream agents still start only after `Analyst Join`.
3. **Risk Guard** may modify `final_trade_decision` after Portfolio Manager when constraints fail.
4. **Historical backtests/analysis:** live sentiment APIs are blocked for past dates; financial statement columns use publication lag, so fewer recent fiscal periods may appear than before.
5. **Removed dependencies:** `backtrader` and `redis` dropped from `pyproject.toml`. Install separately if external code still imports them.

### Non-breaking for most callers

- `propagate(ticker, date)` signature remains backward compatible; new parameters are optional.
- CLI command name and flags unchanged (`analyze`, `--checkpoint`, `--clear-checkpoints`).

### Programmatic streaming migration

If you previously called `graph.graph.stream()` directly, migrate to:

```python
graph.propagate(ticker, date, stream_callback=your_handler)
```

This ensures memory log, JSON logging, and checkpoint cleanup stay consistent.

---

## How to Verify Phase 1

### 1. Run targeted tests

```bash
cd /Users/dn/codeai/TradingAgents
pytest tests/test_graph_e2e_integration.py -v
pytest tests/test_memory_log.py -v
pytest tests/test_checkpoint_resume.py -v
```

`test_graph_e2e_integration.py::TestPropagateUnifiedPath::test_propagate_stream_callback_and_memory_log` specifically asserts the unified path writes memory log entries and JSON state logs.

### 2. Smoke-test CLI (requires LLM API keys)

```bash
tradingagents analyze
```

During the run, confirm the Rich dashboard streams analyst/research/risk sections. After completion, check:

**Memory log** (`~/.tradingagents/memory/trading_memory.md` or `TRADINGAGENTS_MEMORY_LOG_PATH`):

- New block with `[{date} | {TICKER} | ... | pending]`
- `DECISION:` section containing the PM rating text
- `REFLECTION:` empty or placeholder until a later run resolves the entry

**Full state JSON:**

```bash
ls ~/.tradingagents/logs/{TICKER}/TradingAgentsStrategy_logs/full_states_log_*.json
```

Verify `company_of_interest`, `trade_date`, analyst reports, and `final_trade_decision` are populated.

### 3. Verify checkpoint path (optional)

```bash
tradingagents analyze --checkpoint
# Interrupt mid-run (Ctrl+C), then re-run same ticker+date — should resume
```

Checkpoint DB location: `{data_cache_dir}/checkpoints/{TICKER}.db`.

### 4. Confirm parallel + risk nodes exist

```bash
pytest tests/test_graph_e2e_integration.py::TestPropagateUnifiedPath::test_graph_has_parallel_join_and_risk_guard -v
```

Expect graph nodes **`Analyst Join`** and **`Risk Guard`**.

---

## Beyond Phase 1

The optimization manifest (`PLAN.md`) lists six tasks. Based on the current diff, **Tasks 2–6 were also implemented** in this changeset:

| Task | Status in codebase |
|------|-------------------|
| Task-1: Core path unification & CLI streaming | Done |
| Task-2: Parallel analyst fan-out + semaphore | Done |
| Task-3: Point-in-time sentiment & financials lag | Done |
| Task-4: Backtest engine placeholder API | Done |
| Task-5: Programmatic risk guard | Done |
| Task-6: Cleanup, resilience, tests | Partially done (deps removed, `yf_retry`/`structured` improved, new tests; full suite not re-run in this doc) |

---

## Known Limitations & Follow-Ups

1. **Historical sentiment** — No archived StockTwits/Reddit feed; historical runs get an explicit placeholder, not reconstructed sentiment.
2. **Backtest engine** — Daily bars only; `8h`/`24h` windows approximate bar count from hours. Not wired into the LangGraph pipeline yet.
3. **Risk guard** — Heuristic parsing of trader markdown (stop/entry/position %); ATR fetch can fail silently; VaR is a simple proxy, not a full portfolio model.
4. **Parallel analysts** — Higher `analyst_concurrency_limit` increases concurrent LLM/API load and may hit provider rate limits.
5. **Checkpoint resume** — Requires `--checkpoint` or `TRADINGAGENTS_CHECKPOINT_ENABLED=true`; CLI must use `propagate()` (now satisfied).
6. **PLAN.md checklist** — Task checkboxes in `PLAN.md` are not updated to reflect completion.
7. **Changes uncommitted** — This document describes the working tree; commit and release notes are still pending.

---

## Quick Reference: Config Paths

| Key | Default |
|-----|---------|
| `results_dir` | `~/.tradingagents/logs` |
| `data_cache_dir` | `~/.tradingagents/cache` |
| `memory_log_path` | `~/.tradingagents/memory/trading_memory.md` |
| `analyst_concurrency_limit` | `4` |
| `checkpoint_enabled` | `false` (env: `TRADINGAGENTS_CHECKPOINT_ENABLED`) |
