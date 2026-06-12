# Crypto TradingAgents

**v0.4.x** — Algorithmic crypto paper-trading platform with optional multi-agent LLM research. Crypto-only: no equities, no yfinance/Alpha Vantage paths.

The product evolved from an **analyst-only** workflow to a full loop: qualitative research → **10-strategy historical optimization** (8h / 24h / 7d) → **live paper simulation** with portfolio tracking → **autonomous re-optimization** when drawdown thresholds are breached.

<div align="center">

[Overview](#overview) · [Installation](#installation) · [CLI](#cli) · [Backtesting](#backtesting) · [Paper Trading](#paper-trading-simulation) · [Python API](#python-api) · [Configuration](#configuration)

</div>

> Research tool only — not financial advice. Outputs vary with model, temperature, and live data. See [Tauric disclaimer](https://tauric.ai/disclaimer/).

---

## Overview

TradingAgents mirrors a crypto trading desk: specialized LLM agents gather market, on-chain, sentiment, and news context; researchers debate; a trader proposes action; risk analysts stress-test it; a portfolio manager decides. A programmatic risk guard can veto proposals that breach limits.

<p align="center">
  <img src="assets/schema.png" alt="Agent pipeline" style="width: 100%; height: auto;">
</p>

### Agent pipeline

| Stage | Agents | Role |
|-------|--------|------|
| **Analysts** (parallel) | Market, Fundamentals, Sentiment, News | Perps/OHLCV, on-chain metrics, LunarCrush/Reddit, crypto news |
| **Research** | Bull & Bear Researchers → Research Manager | Structured debate; balanced thesis |
| **Trading** | Trader | Timing, direction, sizing from upstream reports |
| **Risk** | Aggressive, Neutral, Conservative → Portfolio Manager | Risk debate; final approve/reject |

Built on **LangGraph** with configurable analyst fan-out (`analyst_concurrency_limit`). After analysis, an interactive menu offers **historical optimization backtests** (no LLM tokens), **custom horizons/risk parameters**, and **deploy-to-paper** with a live Rich portfolio table. Standalone `tradingagents backtest` and `tradingagents paper` work without running analysts.

### Crypto data vendors

| Category | Vendors | Env / notes |
|----------|---------|-------------|
| OHLCV & indicators | Binance, CryptoCompare | `CRYPTOCOMPARE_API_KEY` optional (fallback) |
| Fundamentals / tokenomics | CoinGecko | `COINGECKO_API_KEY` optional (Pro limits) |
| News & sentiment | CryptoCompare, LunarCrush | `LUNARCRUSH_API_KEY`, `CRYPTOCOMPARE_API_KEY` optional |
| Perps (funding, OI) | Binance | Public USD-M REST — no key |

Routing: `route_to_vendor` in `tradingagents/dataflows/`. Override via `DEFAULT_CONFIG["data_vendors"]` or per-tool `tool_vendors`.

**Pairs:** `BTC/USDT`, `ETH/USDC`, `SOL/USD`, etc. (`asset_type` defaults to `crypto`).

---

## Installation

```bash
git clone https://github.com/TauricResearch/TradingAgents.git
cd TradingAgents
python -m venv .venv && source .venv/bin/activate   # or conda, etc.
pip install .
cp .env.example .env   # add API keys
```

**Docker** (optional):

```bash
cp .env.example .env
docker compose run --rm tradingagents
# Local Ollama profile:
docker compose --profile ollama run --rm tradingagents-ollama
```

---

## CLI

```bash
tradingagents analyze                    # interactive full pipeline
python -m cli.main analyze               # run from source
```

| Flag | Purpose |
|------|---------|
| `--no-backtest` | Hide post-analysis backtest and paper-trade menu options |
| `--checkpoint` | LangGraph checkpoint/resume after each node |
| `--clear-checkpoints` | Delete saved checkpoints before run |

```bash
tradingagents analyze --no-backtest
tradingagents analyze --checkpoint
tradingagents analyze --clear-checkpoints
```

**Standalone backtest** (no LLM):

```bash
tradingagents backtest                                      # interactive prompts (TTY)
tradingagents backtest --ticker BTC/USDT --date 2026-01-15
tradingagents backtest --no-interactive -t ETH/USDT -d 2026-01-15 --paper
tradingagents backtest -t BTC/USDT --live --equity 100000   # Binance ccxt fallback
```

Bare `tradingagents backtest` on a TTY walks through pair, end date, horizons (8h/24h/7d), stop-loss, fees, and equity. Empty optimization results raise a clear validation error with diagnostics (never silent exit). Use `--no-interactive` in scripts when all flags are provided.

**Standalone paper trading** (no LLM):

```bash
tradingagents paper                                        # interactive prompts (TTY)
tradingagents paper --ticker BTC/USDT                    # backtest picks strategy, then sim
tradingagents paper -t ETH/USDT --strategy rsi_mean_reversion --equity 5000
tradingagents paper -t SOL/USDT --live --no-adaptive --ticks 20
tradingagents paper --no-interactive -t BTC/USDT --equity 100000
```

Bare `tradingagents paper` on a TTY walks through pair, strategy (auto backtest or fixed registry name), starting equity ($100k default), tick count, live-mode fallback, and adaptive drawdown settings. Use `--no-interactive` in scripts when all flags are provided.

Interactive `analyze` prompts for pair, date, analysts, research depth, and LLM provider. After the Portfolio Manager report, the post-analysis menu loops:

1. **> Run Historical Optimization Backtest** — 10 strategies × 8h/24h/7d, Rich table ranked by profit factor / drawdown / net return (WINNER highlighted)
2. **> Customize Backtest Horizon & Risk Parameters**
3. **> Deploy Optimal Strategy to Live Paper Trading Simulator**
4. Return to main menu or exit

---

## Backtesting

Pure-code engine: fetches intraday OHLCV via **CryptoCompare** (`histominute` / `histohour`) → **Binance klines** → **ccxt** when `--live`, caches CSV locally, runs **24/7** (no equity session gaps). Historic-Crypto is not used (its Coinbase Pro dependency was removed). On fetch failure you get a `BacktestDataError` with vendor diagnostics — set `TRADINGAGENTS_DEBUG=1` for a full traceback. Signals are converted to fills through the paper-trading layer below.

### Strategies (A–J)

| ID | Name | Description |
|----|------|-------------|
| **A** | `ema_crossover` | Fast vs slow EMA — long/short by cross |
| **B** | `rsi_mean_reversion` | RSI oversold (&lt;30) / overbought (&gt;70) |
| **C** | `macd_crossover` | MACD line vs signal line |
| **D** | `bollinger_mean_reversion` | Price vs upper/lower Bollinger bands |
| **E** | `cmo_mean_reversion` | Chande Momentum Oscillator extremes |
| **F** | `adx_trend_filter` | ADX &gt; threshold with +DI / −DI direction |
| **G** | `vwap_band_mean_reversion` | Re-entry after breach of VWAP volume bands |
| **H** | `cci_breakout` | CCI cross above +100 / below −100 |
| **I** | `trix_momentum` | TRIX oscillator vs signal-line cross |
| **J** | `apo_crossover` | Absolute Price Oscillator zero-line cross |

Registry: `STRATEGY_REGISTRY` / `build_strategy()` in `tradingagents/backtest/strategies.py`.

### Optimization loop

For each strategy × lookback horizon (**8h**, **24h**, **7d**):

1. Run backtest on historical window ending at the analysis date.
2. Score by **net profit ratio** (primary).
3. Report **profit factor**, **Sharpe ratio**, **max drawdown**, trade count for the winner.
4. Optionally **deploy** the winner to a live/dummy price feed.

Post-analysis hook runs automatically unless `--no-backtest`. Programmatic entry: `optimize_strategies()` → `deploy_winning_strategy()` → `format_optimization_summary()`.

### Paper trading architecture

Decouples signal math from position tracking:

| Component | Role |
|-----------|------|
| **`TransactionIntent`** | Broker-agnostic order intent (asset, direction, leverage, sizing) from `signals_to_intents()` |
| **`VirtualPortfolio`** | In-memory equity, cash, positions, margin |
| **`SimulatedMatcher`** | Market fills with slippage; limit-order stub; uses a price feed |

### Live vs paper price feed

| Mode | Mechanism |
|------|-----------|
| **Live vendors (default)** | CryptoCompare → CoinGecko → Binance (`live_feed.py` router) |
| **Metadata** | CoinGecko — circulating supply, asset & global market cap |
| **Intraday ticks** | CryptoCompare `histominute` / `histohour` REST |
| **Binance fallback** | ccxt when `LIVE_MODE=1` or `--live` |
| **Resilient mock** | On 429/network errors, localized ticker mutates from last anchor (`dummy_feed`) |

Set API keys in `.env` (`CRYPTOCOMPARE_API_KEY`, `COINGECKO_API_KEY`). Enable Binance fallback:

```bash
export LIVE_MODE=1
export TRADINGAGENTS_LIVE_MODE=true
```

---

## Paper trading simulation

Simulated trading program — analysis is optional. No real orders are sent.

### Architecture

| Component | Role |
|-----------|------|
| **`PaperTradingEngine`** | Polls live prices, refreshes strategy signals, tracks equity |
| **`VirtualPortfolio`** | $100k default cash, long/short margin, fee-aware fills, slippage via matcher |
| **`AdaptiveStrategyMonitor`** | Trailing drawdown watchdog; halts signals during re-optimization |
| **`live_feed.py`** | Unified spot, metadata, intraday ticks; `live_prices.py` re-exports |
| **`persistence.py`** | JSON session state under `~/.tradingagents/cache/paper_sessions/` (PAPER-8) |

### Enable in CLI / TUI

1. **After analysis** — post-analysis menu → *Start Paper Trading Simulation*
2. **Standalone** — `tradingagents paper --ticker BTC/USDT`
3. **After backtest** — `tradingagents backtest --paper` or deploy prompt after optimization

The TUI shows a live Rich table: equity, PnL, current strategy, signal, drawdown, and price source.

### Adaptive strategy switching

When `paper_adaptive_enabled` is on (default), sustained drawdown triggers `optimize_strategies()` on a fresh historical slice. Signals are **halted** during re-optimization; on swap the engine logs:

`[AUTONOMOUS ROTATION]: Strategy changed from [Old] to [New] due to threshold violation.`

Logs append to `{results_dir}/paper_rotation.log`. Thresholds are runtime-adjustable via post-analysis paper prompts or env:

```bash
export TRADINGAGENTS_MAX_ALLOWED_DRAWDOWN_PCT=5.0
export TRADINGAGENTS_DRAWDOWN_TIME_WINDOW=30
# Aliases (still supported):
export TRADINGAGENTS_PAPER_LOSS_THRESHOLD_PCT=5.0
export TRADINGAGENTS_PAPER_LOSS_REVIEW_MINUTES=30
```

### Python API

```python
from tradingagents.simulator import PaperTradingEngine, session_from_optimization
from tradingagents.backtest import optimize_strategies, deploy_winning_strategy
from tradingagents.default_config import DEFAULT_CONFIG

config = DEFAULT_CONFIG.copy()
config["paper_initial_equity"] = 100_000.0
config["paper_state_persistence"] = True
config["paper_adaptive_enabled"] = True

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
config["deep_think_llm"] = "gpt-5.5"
config["quick_think_llm"] = "gpt-5.4-mini"
config["max_debate_rounds"] = 2

ta = TradingAgentsGraph(debug=True, config=config)
_, decision = ta.propagate("BTC/USDT", "2026-01-15", asset_type="crypto")
print(decision)
```

### Backtest optimization

```python
from tradingagents.backtest import (
    compute_strategy_signal,
    optimize_strategies,
    deploy_winning_strategy,
    format_optimization_summary,
)
from tradingagents.default_config import DEFAULT_CONFIG

result = optimize_strategies("BTC/USDT", "2026-01-15")
result = deploy_winning_strategy(result, DEFAULT_CONFIG)
print(format_optimization_summary(result))
print(compute_strategy_signal("BTC/USDT", result.winner.strategy_name, result.winner.parameters, result.winner.lookback))
```

See `tradingagents/default_config.py` for all options.

---

## Configuration

### LLM providers

Set `TRADINGAGENTS_LLM_PROVIDER` and the matching API key. Primary providers:

| Provider | `TRADINGAGENTS_LLM_PROVIDER` | API key env |
|----------|------------------------------|-------------|
| OpenAI | `openai` | `OPENAI_API_KEY` |
| Anthropic | `anthropic` | `ANTHROPIC_API_KEY` |
| Google (Gemini) | `google` | `GOOGLE_API_KEY` |
| AtlasCloud | `atlascloud` | `ATLASCLOUD_API_KEY` |
| Local / custom OpenAI-compatible | `local` | `LOCAL_LLM_API_KEY` + `LOCAL_LLM_BASE_URL` + `LOCAL_LLM_MODEL_NAME` |

**AtlasCloud** default endpoint: `https://api.atlascloud.ai/v1`.

**Local** example (Ollama, LM Studio, vLLM):

```bash
export TRADINGAGENTS_LLM_PROVIDER=local
export LOCAL_LLM_BASE_URL=http://localhost:11434/v1
export LOCAL_LLM_API_KEY=local
export LOCAL_LLM_MODEL_NAME=qwen3:latest
```

Additional keys in `.env.example`: `XAI_API_KEY`, `DEEPSEEK_API_KEY`, `DASHSCOPE_API_KEY` / `DASHSCOPE_CN_API_KEY` (Qwen), `ZHIPU_API_KEY` / `ZHIPU_CN_API_KEY` (GLM), `MINIMAX_API_KEY` / `MINIMAX_CN_API_KEY`, `OPENROUTER_API_KEY`. Remote Ollama: `OLLAMA_BASE_URL`.

### `TRADINGAGENTS_*` overrides

Any `TRADINGAGENTS_*` variable in `.env.example` replaces the matching key in `default_config.py` (types coerced automatically). Examples:

```bash
TRADINGAGENTS_LLM_PROVIDER=openai
TRADINGAGENTS_DEEP_THINK_LLM=gpt-5.4
TRADINGAGENTS_QUICK_THINK_LLM=gpt-5.4-mini
TRADINGAGENTS_MAX_DEBATE_ROUNDS=2
TRADINGAGENTS_CHECKPOINT_ENABLED=true
TRADINGAGENTS_LIVE_MODE=false
TRADINGAGENTS_PAPER_INITIAL_EQUITY=100000
TRADINGAGENTS_PAPER_ADAPTIVE_ENABLED=true
TRADINGAGENTS_PAPER_STATE_ENABLED=true
TRADINGAGENTS_DRAWDOWN_TIME_WINDOW=60
TRADINGAGENTS_MAX_ALLOWED_DRAWDOWN_PCT=5.0
TRADINGAGENTS_PAPER_LOSS_REVIEW_MINUTES=60
TRADINGAGENTS_PAPER_LOSS_THRESHOLD_PCT=5.0
TRADINGAGENTS_TEMPERATURE=0.0
TRADINGAGENTS_OUTPUT_LANGUAGE=English
TRADINGAGENTS_BENCHMARK_TICKER=ETH/USDT
```

### Crypto data keys (optional)

```bash
COINGECKO_API_KEY=       # Pro rate limits, fundamentals
LUNARCRUSH_API_KEY=      # Galaxy score, social volume
CRYPTOCOMPARE_API_KEY=   # OHLCV fallback, news
# Binance public endpoints need no key
```

---

## Persistence & recovery

**Decision log** (always on): appends each run to `~/.tradingagents/memory/trading_memory.md`. Prior same-ticker decisions and cross-ticker lessons feed the Portfolio Manager. Override: `TRADINGAGENTS_MEMORY_LOG_PATH`, `TRADINGAGENTS_BENCHMARK_TICKER`.

**Checkpoints** (opt-in, `--checkpoint`): SQLite per ticker at `~/.tradingagents/cache/checkpoints/<TICKER>.db`. Cleared on success; use `--clear-checkpoints` to reset. Override base: `TRADINGAGENTS_CACHE_DIR`.

```python
config = DEFAULT_CONFIG.copy()
config["checkpoint_enabled"] = True
ta = TradingAgentsGraph(config=config)
```

---

## Reproducibility

LLM runs are non-deterministic: sampling, reasoning models, and live news/sentiment change between runs even for a fixed analysis date. Lower `TRADINGAGENTS_TEMPERATURE` and use non-reasoning models for tighter repeatability. Backtest math is deterministic given the same candle cache.

---

## Contributing

Bug fixes, docs, and features welcome. See [`CHANGELOG.md`](CHANGELOG.md) for release history. Implementation status: [`PLAN.md`](PLAN.md).

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
