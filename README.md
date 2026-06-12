# Crypto TradingAgents

**v0.4.x** — Algorithmic crypto paper-trading platform with optional multi-agent LLM research. Crypto-only: no equities, no yfinance/Alpha Vantage paths.

Qualitative research → **10-strategy historical optimization** (8h / 24h / 7d) → **live paper simulation** with stop-loss / take-profit → **autonomous re-optimization** on drawdown breach.

<div align="center">

[Overview](#overview) · [Installation](#installation) · [CLI](#cli) · [Backtesting](#backtesting) · [Paper Trading](#paper-trading) · [Python API](#python-api) · [Configuration](#configuration)

</div>

> Research tool only — not financial advice. See [Tauric disclaimer](https://tauric.ai/disclaimer/).

---

## Overview

TradingAgents mirrors a crypto trading desk: LLM agents gather market, on-chain, sentiment, and news context; researchers debate; a trader proposes action; risk analysts stress-test it; a portfolio manager decides. A programmatic risk guard can veto proposals that breach limits.

<p align="center">
  <img src="assets/schema.png" alt="Agent pipeline" style="width: 100%; height: auto;">
</p>

| Stage | Agents | Role |
|-------|--------|------|
| **Analysts** | Market, Fundamentals, Sentiment, News | Perps/OHLCV, on-chain, LunarCrush/Reddit, crypto news |
| **Research** | Bull & Bear → Research Manager | Structured debate |
| **Trading** | Trader | Timing, direction, sizing |
| **Risk** | Aggressive, Neutral, Conservative → PM | Final approve/reject |

Built on **LangGraph** with configurable analyst fan-out (`analyst_concurrency_limit`).

### Crypto data vendors

| Category | Vendors | Env / notes |
|----------|---------|-------------|
| OHLCV & indicators | Binance, CryptoCompare | `CRYPTOCOMPARE_API_KEY` optional |
| Fundamentals | CoinGecko | `COINGECKO_API_KEY` optional |
| News & sentiment | CryptoCompare, LunarCrush | `LUNARCRUSH_API_KEY` optional |
| Perps (funding, OI) | Binance | Public REST — no key |

Routing: `route_to_vendor` in `tradingagents/dataflows/`. **Pairs:** `BTC/USDT`, `ETH/USDC`, `SOL/USD`, etc.

**News date window:** sentiment and news tools filter articles via `date_window.py` (`article_date_in_range`, `lookback_start`) so lookbacks end on the analysis date — no future-dated headlines.

---

## Installation

```bash
git clone https://github.com/TauricResearch/TradingAgents.git
cd TradingAgents
python -m venv .venv && source .venv/bin/activate
pip install .
cp .env.example .env   # add API keys
```

**Docker:** `docker compose run --rm tradingagents` (add `--profile ollama` for local Ollama).

---

## CLI

```bash
tradingagents analyze                    # interactive full pipeline
python -m cli.main analyze               # run from source
```

| Flag | Purpose |
|------|---------|
| `--no-backtest` | Hide post-analysis backtest and paper-trade menu options (main menu + exit only) |
| `--checkpoint` | LangGraph checkpoint/resume after each node |
| `--clear-checkpoints` | Delete saved checkpoints before run |

### Post-analysis menu

After the Portfolio Manager report (unless `--no-backtest`), an interactive loop offers:

1. **Run Historical Optimization Backtest** — 10 strategies × 8h/24h/7d; Rich table ranked by profit factor / drawdown / net return (WINNER highlighted)
2. **Customize Backtest Horizon & Risk Parameters** — horizons, stop-loss %, take-profit % (default 2× stop-loss), fees
3. **Deploy Optimal Strategy to Live Paper Trading Simulator** — polls prices, tracks P&L, optional adaptive re-optimization
4. Return to main menu / exit

Standalone commands work without running analysts:

```bash
# Backtest (no LLM)
tradingagents backtest                                      # interactive TTY prompts
tradingagents backtest --ticker BTC/USDT --date 2026-01-15
tradingagents backtest --no-interactive -t ETH/USDT -d 2026-01-15 --paper

# Paper trading (no LLM)
tradingagents paper
tradingagents paper --ticker BTC/USDT
tradingagents paper -t ETH/USDT --strategy rsi_mean_reversion --equity 5000
tradingagents paper -t SOL/USDT --live --no-adaptive --ticks 20
```

Bare `backtest` / `paper` on a TTY walk through pair, date/horizons, equity, stop-loss, and adaptive settings. Use `--no-interactive` when all flags are provided.

### Demo script (`main.py`)

`main.py` runs a single `propagate()` without the full CLI menu. **Requires** `--ticker` and `--date`, or env vars `DEMO_TICKER` / `DEMO_DATE`:

```bash
python main.py --ticker BTC/USDT --date 2026-06-11
export DEMO_TICKER=ETH/USDC DEMO_DATE=2026-06-11 && python main.py
```

---

## Backtesting

Pure-code engine: intraday OHLCV via **CryptoCompare** → **Binance klines** → **ccxt** when `LIVE_MODE=1` or `--live`. Runs **24/7** (no equity session gaps). On fetch failure: `BacktestDataError` with vendor diagnostics (`TRADINGAGENTS_DEBUG=1` for traceback).

### Strategies (A–J)

| ID | Name | Description |
|----|------|-------------|
| **A** | `ema_crossover` | Fast vs slow EMA cross |
| **B** | `rsi_mean_reversion` | RSI &lt;30 / &gt;70 |
| **C** | `macd_crossover` | MACD vs signal line |
| **D** | `bollinger_mean_reversion` | Price vs Bollinger bands |
| **E** | `cmo_mean_reversion` | Chande Momentum extremes |
| **F** | `adx_trend_filter` | ADX + DI direction |
| **G** | `vwap_band_mean_reversion` | VWAP volume-band re-entry |
| **H** | `cci_breakout` | CCI ±100 cross |
| **I** | `trix_momentum` | TRIX vs signal |
| **J** | `apo_crossover` | APO zero-line cross |

Registry: `STRATEGY_REGISTRY` in `tradingagents/backtest/strategies.py`.

### Optimization loop

For each strategy × lookback (**8h**, **24h**, **7d**): backtest on window ending at analysis date → score by net profit ratio → report profit factor, Sharpe, max drawdown. Programmatic: `optimize_strategies()` → `deploy_winning_strategy()` → `format_optimization_summary()`.

---

## Paper trading

Simulated trading — no real orders. Signals map **1 = long**, **-1 = short**, **0 = flat** (also accepts `long`/`short`/`flat` strings).

### Tick evaluation (`evaluate_live_market_tick`)

Each price tick:

1. **`mark_to_market`** — update unrealized P&L
2. **Stop-loss** — close and realize loss when adverse move ≥ `stop_loss_pct` (default 2%)
3. **Take-profit** — close and realize gain when in profit and move ≥ `take_profit_pct` (default 2× stop-loss; override via config or custom backtest prompt)
4. **Signal entries/exits** — enter/flip/exit per strategy signal when risk limits not hit

### Components

| Component | Role |
|-----------|------|
| **`VirtualPortfolio`** | Cash, equity, long/short positions, fees, margin |
| **`SimulatedMatcher`** | Market fills with slippage; no exchange orders |
| **`PaperTradingEngine`** | Polls prices, refreshes signals, runs tick evaluation |
| **`AdaptiveStrategyMonitor`** | Drawdown watchdog; halts signals during re-optimization |
| **`persistence.py`** | JSON session state under `~/.tradingagents/cache/paper_sessions/` |

### Price feed

| Mode | Mechanism |
|------|-----------|
| **Default** | CryptoCompare → CoinGecko → Binance (`live_feed.py`) |
| **`LIVE_MODE=1` / `--live`** | ccxt Binance fallback for spot ticks |
| **Resilient mock** | On 429/network errors, `dummy_feed` mutates from last anchor |

```bash
export LIVE_MODE=1
export TRADINGAGENTS_LIVE_MODE=true
```

### Adaptive strategy switching

When `paper_adaptive_enabled` is on, sustained drawdown triggers `optimize_strategies()` on a fresh slice. Signals halt during re-test; on swap:

`[AUTONOMOUS ROTATION]: Strategy changed from [Old] to [New] due to threshold violation.`

Thresholds via post-analysis paper prompts or env (`TRADINGAGENTS_MAX_ALLOWED_DRAWDOWN_PCT`, `TRADINGAGENTS_DRAWDOWN_TIME_WINDOW`).

### Python API

```python
from tradingagents.simulator import PaperTradingEngine, session_from_optimization
from tradingagents.backtest import optimize_strategies, deploy_winning_strategy
from tradingagents.default_config import DEFAULT_CONFIG

config = DEFAULT_CONFIG.copy()
config["paper_initial_equity"] = 100_000.0
config["paper_stop_loss_pct"] = 0.02
config["paper_take_profit_pct"] = 0.04  # optional; None → 2× stop-loss

opt = deploy_winning_strategy(optimize_strategies("BTC/USDT", "2026-06-12"), config)
session = session_from_optimization(opt, config)
engine = PaperTradingEngine(session, config)
engine.run_loop(max_ticks=10)
print(engine.get_state())
```

---

## Python API

### Multi-agent analysis

```python
from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG

config = DEFAULT_CONFIG.copy()
config["llm_provider"] = "openai"
ta = TradingAgentsGraph(debug=True, config=config)
_, decision = ta.propagate("BTC/USDT", "2026-01-15", asset_type="crypto")
print(decision)
```

### Backtest optimization

```python
from tradingagents.backtest import optimize_strategies, deploy_winning_strategy, format_optimization_summary

result = optimize_strategies("BTC/USDT", "2026-01-15")
result = deploy_winning_strategy(result, DEFAULT_CONFIG)
print(format_optimization_summary(result))
```

See `tradingagents/default_config.py` for all options.

---

## Configuration

### LLM providers

Set `TRADINGAGENTS_LLM_PROVIDER` and the matching API key:

| Provider | Value | API key env |
|----------|-------|-------------|
| OpenAI | `openai` | `OPENAI_API_KEY` |
| Anthropic | `anthropic` | `ANTHROPIC_API_KEY` |
| Google | `google` | `GOOGLE_API_KEY` |
| AtlasCloud | `atlascloud` | `ATLASCLOUD_API_KEY` |
| Local OpenAI-compatible | `local` | `LOCAL_LLM_API_KEY` + `LOCAL_LLM_BASE_URL` + `LOCAL_LLM_MODEL_NAME` |

Additional keys in `.env.example`: `XAI_API_KEY`, `DEEPSEEK_API_KEY`, Qwen, GLM, MiniMax, `OPENROUTER_API_KEY`.

### `TRADINGAGENTS_*` overrides

Any `TRADINGAGENTS_*` in `.env.example` replaces the matching `default_config.py` key (types coerced automatically). Examples:

```bash
TRADINGAGENTS_LLM_PROVIDER=openai
TRADINGAGENTS_LIVE_MODE=false
TRADINGAGENTS_PAPER_INITIAL_EQUITY=100000
TRADINGAGENTS_PAPER_STOP_LOSS_PCT=0.02
TRADINGAGENTS_PAPER_TAKE_PROFIT_PCT=0.04
TRADINGAGENTS_PAPER_ADAPTIVE_ENABLED=true
TRADINGAGENTS_MAX_ALLOWED_DRAWDOWN_PCT=5.0
TRADINGAGENTS_DRAWDOWN_TIME_WINDOW=60
TRADINGAGENTS_TEMPERATURE=0.0
```

### Crypto data keys (optional)

`COINGECKO_API_KEY`, `LUNARCRUSH_API_KEY`, `CRYPTOCOMPARE_API_KEY` — Binance public endpoints need no key.

---

## Persistence & recovery

**Decision log** (always on): `~/.tradingagents/memory/trading_memory.md`. Override: `TRADINGAGENTS_MEMORY_LOG_PATH`.

**Checkpoints** (opt-in, `--checkpoint`): SQLite per ticker at `~/.tradingagents/cache/checkpoints/<TICKER>.db`.

---

## Reproducibility

LLM runs are non-deterministic (sampling, reasoning models, live news). Lower `TRADINGAGENTS_TEMPERATURE` for tighter repeatability. Backtest and paper tick math are deterministic given the same candle cache and price feed.

---

## Contributing

Bug fixes, docs, and features welcome. See [`CHANGELOG.md`](CHANGELOG.md) and [`PLAN.md`](PLAN.md).

## Citation

```bibtex
@misc{xiao2025tradingagentsmultiagentsllmfinancial,
      title={TradingAgents: Multi-Agents LLM Financial Trading Framework},
      author={Yijia Xiao and Edward Sun and Di Luo and Wei Wang},
      year={2025},
      eprint={2412.20138},
      archivePrefix={arXiv},
      primaryClass={q-fin.TR},
      url={https://arxiv.org/abs/2412.20138},
}
```
