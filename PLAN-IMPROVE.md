# TradingAgents — Strategy & Simulation Improvement Plan

## Purpose

Close the gap between **backtest winners** and **paper trading outcomes** for spot crypto pairs (e.g. `BTC/USDT`). Today the pipeline picks a “winner” from 30 fixed-parameter runs on short windows (`8h` / `24h` / `7d`) using `net_profit_ratio` only — even when all runs lose money. Paper execution then diverges from backtest math (take-profit, feeds, risk params), so the same strategy can keep “winning” re-backtests while equity drifts down.

This plan implements the advisory recommendations from the BTC/USDT paper-trading review. **Spot only** — futures/perps execution is explicitly out of scope (analyst perps context may remain).

**Related docs:** `PLAN.md` (platform manifest), `README.md`, advisory analysis in agent transcript.

---

## Goals

| Goal | Success criterion |
|------|-------------------|
| **Parity** | Backtest and paper use the same exit rules (SL/TP), fees, and slippage model |
| **Honest selection** | No strategy deploys when all candidates fail quality gates |
| **Consistent re-optimization** | Adaptive re-backtest uses session risk params and refreshes lookback even when name unchanged |
| **Reduced overfitting** | Walk-forward validation before deploy; optional parameter search behind flags |
| **Unified marks** | OHLCV and live fills prefer the same venue/quote where possible |

## Non-Goals (this plan)

- BTC/USDT-M **futures** simulation (funding, margin, liquidation, `fapi` klines)
- Leverage > 1.0 on spot (infrastructure exists but misleading without perps model)
- Guaranteed profitability or production trading readiness
- LLM-driven strategy generation

---

## Problem Summary

### Winner selection (`optimize_strategies`)

- Picks `max(net_profit_ratio)` across 10 strategies × 3 horizons (`engine.py` ~721–733).
- Sharpe, profit factor, drawdown are **computed but not used** for selection.
- **No min-trades filter** — 1–2 lucky trades can win on ~96-bar windows.
- **No parameter search** — only default dataclass fields in `strategies.py`.
- Rich table sorts by profit factor for display (`cli/post_analysis.py`); that does **not** choose the winner.

### Adaptive re-backtest drift

- Re-runs same 30 configs with **default** `stop_loss_pct=0.02`, `transaction_cost_pct=0.001` — not paper session values (`paper_engine.py` ~367–374).
- Strategy switch only when **name** changes; lookback/parameters not refreshed when same strategy re-wins (`paper_engine.py` ~393).

### Backtest vs paper execution

| Dimension | Backtest | Paper |
|-----------|----------|-------|
| Take-profit | Not in `run_strategy_on_frame` | `evaluate_live_market_tick` (TP default 2× SL) |
| Fill price | Bar close on signal change | Live spot tick |
| OHLCV vs live | CryptoCompare → Binance → ccxt | CryptoCompare → CoinGecko → Binance |
| Quote | `BTC/USDT` → `BTC-USD` cache key | Actual pair ticker |
| Signal refresh | One historical pass | Last bar every tick (~10s) |

### Signal frequency

- Horizons map to bar sizes: 8h→5m, 24h→15m, 7d→1h (`engine.py` ~41–45).
- Lowering tick interval speeds SL/TP detection only; **does not** create more bar-level entries.

---

## Implementation Phases

Atomic commits per phase: `feat/IMPROVE-{n}-*: ...` — do not bundle unrelated phases.

Recommended sequence: **IMPROVE-1 → IMPROVE-2 → IMPROVE-3 → IMPROVE-4 → IMPROVE-5 → IMPROVE-6 → IMPROVE-7**.

```
IMPROVE-1 (parity)     ──► IMPROVE-2 (gating)     ──► deploy safely
        │                        │
        └────────────────────────┴──► IMPROVE-3 (unified feed)
                                          │
IMPROVE-4 (risk sweep) ◄──────────────────┘
        │
        ▼
IMPROVE-5 (param search) ──► IMPROVE-6 (walk-forward)
        │
        ▼
IMPROVE-7 (medium — optional)
```

---

## Phase IMPROVE-1 — Backtest / Paper Parity

**Impact:** High | **Effort:** Moderate | **Priority:** P0

Fix the largest sim mismatch: backtest does not simulate take-profit; paper does.

### Tasks

- [ ] **IMPROVE-1.1** — Add `take_profit_pct` to `run_strategy_on_frame` (`engine.py` ~483–506)
  - Mirror paper logic in `simulator/core.py` (`evaluate_live_market_tick` ~126–132, ~231–237).
  - Long: exit when price ≥ entry × (1 + TP); short: exit when price ≤ entry × (1 − TP).
  - Accept `take_profit_pct: Optional[float]`; default `None` → 2× `stop_loss_pct` (match paper).
  - Thread through `optimize_strategies(..., take_profit_pct=...)`.

- [ ] **IMPROVE-1.2** — Align fee and slippage constants
  - Document single source of truth: `transaction_cost_pct` → matcher slippage + `VirtualPortfolio.fee_bps`.
  - Ensure paper session `slippage_bps` and backtest `transaction_cost_pct` derive from same config helper.
  - Optional: `TRADINGAGENTS_SLIPPAGE_BPS` in `.env.example` (currently code-derived).

- [ ] **IMPROVE-1.3** — Pass paper risk params into adaptive re-backtest
  - `_run_adaptive_rebacktest` in `paper_engine.py` passes `stop_loss_pct`, `take_profit_pct`, `transaction_cost_pct` from session/config into `optimize_strategies()`.
  - Initial paper deploy (post-analysis) uses same params.

- [ ] **IMPROVE-1.4** — Refresh lookback/parameters when same strategy re-wins
  - In `paper_engine.py` ~391–408: always update `session.lookback`, `session.parameters`, `session.granularity` from `optimization.winner` even when `new_name == old_name`.
  - Log `[AUTONOMOUS ROTATION]: lookback refreshed` when only lookback/params change.

### Files

| Area | Path |
|------|------|
| Backtest sim | `tradingagents/backtest/engine.py` |
| Paper engine | `tradingagents/simulator/paper_engine.py` |
| Live tick math | `tradingagents/simulator/core.py` |
| Config | `tradingagents/default_config.py`, `.env.example` |

### Tests

- [ ] Backtest with TP exits earlier than SL-only baseline on synthetic series.
- [ ] Adaptive re-backtest passes session SL/TP into optimizer (mock `optimize_strategies`).
- [ ] Same-strategy re-win updates `lookback` on session.

### Acceptance

- Custom backtest with `stop_loss_pct=0.015`, `take_profit_pct=0.03` matches paper session defaults in simulation outcomes (same trade count ±0 on fixed seed data).

---

## Phase IMPROVE-2 — Winner Gating

**Impact:** High | **Effort:** Moderate | **Priority:** P0

Stop deploying “winners” that are all losers or statistically meaningless.

### Tasks

- [ ] **IMPROVE-2.1** — `WinnerGate` criteria in `engine.py` or `validation.py`
  - `min_net_profit_ratio` (default `0.0` — must be profitable).
  - `min_trades` (default `3` for 8h/5m; scale by horizon or configurable).
  - `max_drawdown_pct` (optional cap, e.g. `0.10`).
  - Optional: `min_profit_factor` (e.g. `1.0`).

- [ ] **IMPROVE-2.2** — Filter `all_metrics` before `max()`; return `winner=None` + `rejection_reason` when no candidate passes.
  - Extend `OptimizationResult` / `WinningStrategySummary` schema with `deployable: bool`, `gate_failures: list[str]`.

- [ ] **IMPROVE-2.3** — Paper deploy behavior when not deployable
  - Auto mode: stay **FLAT** or keep previous strategy with warning (config flag `on_gate_fail: flat | keep | prompt`).
  - Activity log: `"No deployable strategy — best loser: cci_breakout (7d) net=-1.2%"`.

- [ ] **IMPROVE-2.4** — CLI / post-analysis messaging
  - Rich table marks gated-out rows; WINNER only if deployable.
  - `cli/post_analysis.py`, `cli/paper_interactive.py`.

### Config keys

```bash
# Winner gating (optimizer)
TRADINGAGENTS_WINNER_MIN_NET_PROFIT=0.0
TRADINGAGENTS_WINNER_MIN_TRADES=3
TRADINGAGENTS_WINNER_MAX_DRAWDOWN_PCT=0.15
TRADINGAGENTS_WINNER_ON_GATE_FAIL=flat   # flat | keep | prompt
```

### Tests

- [ ] All-negative metrics → `winner=None`, `deployable=False`.
- [ ] Strategy with 1 trade and +5% loses to strategy with 5 trades and +2% when `min_trades=3`.
- [ ] Paper auto-deploy does not switch on failed gate.

### Acceptance

- User running auto backtest on a losing day sees explicit “no deployable winner” instead of least-bad loser deployed.

---

## Phase IMPROVE-3 — Unified Spot Price Pipeline

**Impact:** High | **Effort:** Moderate–High | **Priority:** P1

Reduce BTC/USDT vs BTC-USD basis noise between signal candles and live fills.

### Tasks

- [ ] **IMPROVE-3.1** — `PricePipelineConfig` — preferred vendor order for **both** OHLCV and spot.
  - Default: `binance` (ccxt `BTC/USDT`) when `LIVE_MODE=1` or `BACKTEST_PREFER_BINANCE=1`.
  - Fallback chain unchanged for geo-blocked regions.

- [ ] **IMPROVE-3.2** — Live feed prefers same quote as backtest
  - `live_feed.py`: when backtest session uses `BTC/USDT`, fetch `BTC/USDT` not `BTC-USD` where vendor supports it.
  - Align cache keys in `engine.py` ~103–109 with live pair normalization.

- [ ] **IMPROVE-3.3** — Paper signal OHLCV refresh
  - Shorten or bypass stale cache for **signal** computation in paper mode (separate from backtest disk TTL).
  - Env: `TRADINGAGENTS_PAPER_SIGNAL_CACHE_TTL_SECONDS` (default `60` or `0` = fetch each signal refresh).

- [ ] **IMPROVE-3.4** — Remove or gate placeholder/mock prices in paper
  - When all vendors fail, halt signals + log error instead of silent mock ticker (`paper_engine.py` ~136–143).

### Files

| Area | Path |
|------|------|
| OHLCV | `tradingagents/backtest/historical_data.py` |
| Live | `tradingagents/dataflows/live_feed.py` |
| Engine | `tradingagents/backtest/engine.py`, `simulator/paper_engine.py` |

### Tests

- [ ] Backtest and live feed resolve same normalized symbol for `BTC/USDT`.
- [ ] Mock vendor failure → paper signals halted, no mock price fill.

### Acceptance

- Activity log shows same primary provider for backtest OHLCV and live price when Binance/ccxt available.

---

## Phase IMPROVE-4 — Risk Parameter Sweep in Optimizer

**Impact:** Medium–High | **Effort:** Low–Moderate | **Priority:** P1

`stop_loss_pct`, `take_profit_pct`, and `transaction_cost_pct` are already accepted by `run_strategy_on_frame` / `optimize_strategies` but never swept.

### Tasks

- [ ] **IMPROVE-4.1** — Optional grid in `optimize_strategies`
  - Flag: `TRADINGAGENTS_OPTIMIZE_RISK_PARAMS=1` or CLI prompt “Sweep SL/TP/fees?”.
  - Small grid: e.g. SL ∈ {0.01, 0.015, 0.02}, TP ∈ {2×SL, 3×SL}, cost ∈ {0.001, 0.002}.
  - Cartesian product per (strategy, horizon) — cap total runs (e.g. max 500) with early exit.

- [ ] **IMPROVE-4.2** — Winner carries best risk params in `WinningStrategySummary.parameters`.
  - Paper session applies optimized SL/TP on deploy and adaptive rotation.

- [ ] **IMPROVE-4.3** — Activity log reports swept params for winner.

### Tests

- [ ] Grid produces different winner SL/TP than defaults on synthetic whipsaw series.
- [ ] Run count respects cap.

### Acceptance

- Custom backtest menu offers risk sweep; winner row shows `sl=0.015 tp=0.03`.

---

## Phase IMPROVE-5 — Per-Strategy Parameter Optimization

**Impact:** High | **Effort:** High | **Priority:** P2

Biggest alpha lever in architecture — **increases overfitting risk**; must ship with IMPROVE-6 or strong gating.

### Tasks

- [ ] **IMPROVE-5.1** — `StrategyParamSpace` per strategy in `strategies.py`
  - Example: RSI `oversold` 20–40, `overbought` 60–80; EMA `fast_period` 5–20, `slow_period` 30–100.
  - Dataclass metadata or `PARAM_BOUNDS: dict[str, tuple[int,int]]`.

- [ ] **IMPROVE-5.2** — Search driver in `engine.py`
  - Phase 1: random search (N=20 samples per strategy per horizon).
  - Phase 2 (optional): grid for 2-param strategies only.
  - Score with gated `net_profit_ratio` or composite: `net_profit - λ * max_drawdown`.

- [ ] **IMPROVE-5.3** — CLI flag `--optimize-params` / env `TRADINGAGENTS_OPTIMIZE_STRATEGY_PARAMS=1`.
  - Default **off** to preserve current fast 30-run behavior.

- [ ] **IMPROVE-5.4** — Cache param search results keyed by (symbol, window, end_date).

### Config keys

```bash
TRADINGAGENTS_OPTIMIZE_STRATEGY_PARAMS=false
TRADINGAGENTS_PARAM_SEARCH_SAMPLES=20
TRADINGAGENTS_PARAM_SEARCH_MAX_RUNS=600
```

### Tests

- [ ] Random search finds better RSI thresholds on synthetic mean-reverting series.
- [ ] Default off → identical behavior to pre-IMPROVE-5.

### Acceptance

- Enabled param search completes within reasonable time for BTC/USDT (target < 2 min with cache).

---

## Phase IMPROVE-6 — Walk-Forward Validation

**Impact:** High | **Effort:** High | **Priority:** P2

Reduce in-sample lottery: optimize on older slice, validate on recent hold-out.

### Tasks

- [ ] **IMPROVE-6.1** — Split windows in `optimize_strategies`
  - **Train:** e.g. `T - 7d` … `T - 24h` (or per-horizon train span).
  - **Validate:** last `8h` or `24h` hold-out (configurable).
  - Pick winner only if **both** train and validate pass IMPROVE-2 gates.

- [ ] **IMPROVE-6.2** — `WalkForwardResult` in schemas
  - `train_metrics`, `validate_metrics`, `deployable`.

- [ ] **IMPROVE-6.3** — CLI / activity log
  - `"Winner cci_breakout: train +2.1% / validate +0.8% — deployable"`.
  - `"Rejected: train +5% / validate -3%"`.

- [ ] **IMPROVE-6.4** — Adaptive re-backtest uses walk-forward when enabled.

### Config keys

```bash
TRADINGAGENTS_WALK_FORWARD_ENABLED=false
TRADINGAGENTS_WALK_FORWARD_VALIDATE_HOURS=8
```

### Tests

- [ ] Winner that fails validate window is not deployable.
- [ ] Walk-forward off → single-window behavior unchanged.

### Acceptance

- Auto mode with walk-forward enabled reduces “same strategy every re-backtest” on regime change (manual QA on BTC/USDT paper session).

---

## Phase IMPROVE-7 — Medium-Impact Enhancements (Optional)

**Impact:** Medium | **Effort:** Variable | **Priority:** P3

Implement after P0–P2 stable. Pick sub-tasks incrementally.

### Tasks

- [ ] **IMPROVE-7.1** — Position sizing (`sizing_pct`, vol scaling)
  - Use `TransactionIntent.sizing_pct` (`portfolio.py` ~106–108); default 100%, optional ATR-based scale.
  - Env: `TRADINGAGENTS_POSITION_SIZE_PCT=1.0`.

- [ ] **IMPROVE-7.2** — Min trade interval / cooldown
  - Suppress signal flip within N bars after exit (reduce EMA churn on 5m).
  - Env: `TRADINGAGENTS_MIN_BARS_BETWEEN_TRADES=3`.

- [ ] **IMPROVE-7.3** — Regime filter (meta-strategy)
  - ADX gate: mean-revert only when ADX < 20; trend only when ADX > 25.
  - New strategy `regime_switch` or filter wrapper in `build_strategy`.

- [ ] **IMPROVE-7.4** — Shorter horizons / 1m bars (research only)
  - New `LookbackWindow.H1 = "1h"` with 1m granularity — **high overfitting risk**.
  - Requires vendor support audit in `historical_data.py`.
  - Ship behind `TRADINGAGENTS_ENABLE_1M_BARS=false`.

- [ ] **IMPROVE-7.5** — Composite winner score (optional alternative to pure `net_profit_ratio`)
  - e.g. `score = net_profit_ratio * min(profit_factor, 3) / (1 + max_drawdown)`.
  - Env-selectable: `TRADINGAGENTS_WINNER_SCORE=net_profit` | `composite`.

### Explicitly low priority (document only)

- Lower `paper_tick_interval_seconds` below 10s — marginal SL/TP benefit, higher API load.
- More strategies (K–Z) without param search — adds selection noise.

---

## Documentation & UX Updates

Cross-cutting tasks after each phase:

- [ ] **DOC-1** — `README.md` — “Backtest vs paper” section, winner gating, walk-forward flag.
- [ ] **DOC-2** — `.env.example` — all new `TRADINGAGENTS_*` keys with defaults.
- [ ] **DOC-3** — `PLAN.md` — link to `PLAN-IMPROVE.md`; add IMPROVE epic checklist.
- [ ] **DOC-4** — Activity log messages for gate failures, walk-forward, param sweep (extends `cli/activity_log.py`).

---

## Testing Strategy

| Layer | Scope |
|-------|--------|
| Unit | TP in backtest, winner gates, param bounds, walk-forward split math |
| Integration | `optimize_strategies` end-to-end with mocked OHLCV |
| Paper | Adaptive re-backtest with session params; same-name refresh |
| Regression | Existing `tests/test_backtester.py`, `test_paper_engine.py`, `test_adaptive.py` stay green |

Target: no reduction in current pytest count; add `tests/test_improve_gating.py`, `tests/test_improve_parity.py` per phase.

---

## Rollout & Flags

All behavioral changes default to **backward-compatible** where possible:

| Feature | Default | Safe production path |
|---------|---------|----------------------|
| Take-profit in backtest | on after IMPROVE-1 | matches paper |
| Winner gating | on after IMPROVE-2 | `min_trades=3`, `min_profit=0` |
| Walk-forward | **off** | opt-in |
| Param search | **off** | opt-in |
| Risk sweep | **off** | opt-in |
| Unified Binance pipeline | **off** | `BACKTEST_PREFER_BINANCE=1` |

---

## Effort Estimates

| Phase | Focus | Est. dev time |
|-------|--------|---------------|
| IMPROVE-1 | Parity | 1–2 days |
| IMPROVE-2 | Gating | 1 day |
| IMPROVE-3 | Unified feed | 2–3 days |
| IMPROVE-4 | Risk sweep | 1 day |
| IMPROVE-5 | Param search | 3–5 days |
| IMPROVE-6 | Walk-forward | 3–4 days |
| IMPROVE-7 | Optional extras | 2–5 days (pick items) |

**Minimum viable improvement (P0):** IMPROVE-1 + IMPROVE-2 (~2–3 days).

**Recommended before trusting auto-deploy overnight:** IMPROVE-1 + IMPROVE-2 + IMPROVE-3.

---

## Current Workarounds (until IMPROVE-* ships)

Users can improve behavior today without code changes:

1. Run **custom backtest** with realistic `transaction_cost_pct` (0.001–0.002); inspect `num_trades` and `max_drawdown`.
2. **Fix a strategy manually** (`--strategy rsi_mean_reversion`) — avoids 30-way lottery.
3. Set **`TRADINGAGENTS_PAPER_TAKE_PROFIT_PCT`** explicitly; know backtest lacks TP until IMPROVE-1.
4. **`LIVE_MODE=1`** + `BACKTEST_CCXT_EXCHANGES=kraken,coinbase` for vendor resilience.
5. **Disable adaptive** until IMPROVE-2 — `--no-adaptive` or prompt “No”.
6. **`--fresh`** when evaluating a new config.

---

## Task Checklist (rollup)

### P0 — Do first
- [x] IMPROVE-1: Backtest/paper parity (TP, fees, adaptive params, same-name refresh)
- [x] IMPROVE-2: Winner gating

### P1 — Do next
- [x] IMPROVE-3: Unified spot price pipeline (`BACKTEST_PREFER_BINANCE`, no mock fills)
- [x] IMPROVE-4: Risk parameter sweep (opt-in via `TRADINGAGENTS_OPTIMIZE_RISK_PARAMS`)

### P2 — Validation & search
- [ ] IMPROVE-5: Per-strategy parameter optimization
- [ ] IMPROVE-6: Walk-forward validation

### P3 — Optional
- [ ] IMPROVE-7: Sizing, cooldown, regime, 1m bars, composite score

### Docs
- [ ] DOC-1 through DOC-4

---

## Revision Log

| Date | Change |
|------|--------|
| 2026-06-12 | Initial plan from BTC/USDT paper trading advisory; futures excluded |
