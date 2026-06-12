# Crypto TradingAgents

**v0.3.0** — Multi-agent LLM framework for cryptocurrency research and paper trading. Crypto-only: no equities, no yfinance/Alpha Vantage paths.

<div align="center">

[Overview](#overview) · [Installation](#installation) · [CLI](#cli) · [Backtesting](#backtesting) · [Python API](#python-api) · [Configuration](#configuration)

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

Built on **LangGraph** with configurable analyst fan-out (`analyst_concurrency_limit`). After analysis, the CLI optionally runs a **pure-code backtest** (no LLM) and appends an optimization summary to the report.

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
| `--no-backtest` | Skip post-analysis strategy optimization |
| `--checkpoint` | LangGraph checkpoint/resume after each node |
| `--clear-checkpoints` | Delete saved checkpoints before run |

```bash
tradingagents analyze --no-backtest
tradingagents analyze --checkpoint
tradingagents analyze --clear-checkpoints
```

**Standalone backtest** (no LLM):

```bash
tradingagents backtest --ticker BTC/USDT --date 2026-01-15
tradingagents backtest -t ETH/USDT -d 2026-01-15
tradingagents backtest --ticker BTC/USDT --live    # ccxt live price bridge
```

Omit `--date` for today. Interactive `analyze` prompts for pair, date, analysts, research depth, and LLM provider.

---

## Backtesting

Pure-code engine: fetches intraday history via [Historic-Crypto](https://github.com/AminHP/gym-mtsim) (Coinbase candles), caches CSV locally, runs **24/7** (no equity session gaps). Signals are converted to fills through the paper-trading layer below.

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
| **Paper (default)** | `dummy_feed` — price steps from last historical bar |
| **Live** | ccxt Binance ticker via `fetch_live_price` |

Enable live mode:

```bash
tradingagents backtest --ticker BTC/USDT --date 2026-01-15 --live
export LIVE_MODE=1
export TRADINGAGENTS_LIVE_MODE=true
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
    optimize_strategies,
    deploy_winning_strategy,
    format_optimization_summary,
)
from tradingagents.default_config import DEFAULT_CONFIG

result = optimize_strategies("BTC/USDT", "2026-01-15")
result = deploy_winning_strategy(result, DEFAULT_CONFIG)
print(format_optimization_summary(result))
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
