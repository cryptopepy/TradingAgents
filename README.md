<p align="center">
  <img src="assets/TauricResearch.png" style="width: 60%; height: auto;">
</p>

<div align="center" style="line-height: 1;">
  <a href="https://arxiv.org/abs/2412.20138" target="_blank"><img alt="arXiv" src="https://img.shields.io/badge/arXiv-2412.20138-B31B1B?logo=arxiv"/></a>
  <a href="https://discord.com/invite/hk9PGKShPK" target="_blank"><img alt="Discord" src="https://img.shields.io/badge/Discord-TradingResearch-7289da?logo=discord&logoColor=white&color=7289da"/></a>
  <a href="./assets/wechat.png" target="_blank"><img alt="WeChat" src="https://img.shields.io/badge/WeChat-TauricResearch-brightgreen?logo=wechat&logoColor=white"/></a>
  <a href="https://x.com/TauricResearch" target="_blank"><img alt="X Follow" src="https://img.shields.io/badge/X-TauricResearch-white?logo=x&logoColor=white"/></a>
  <br>
  <a href="https://github.com/TauricResearch/" target="_blank"><img alt="Community" src="https://img.shields.io/badge/Join_GitHub_Community-TauricResearch-14C290?logo=discourse"/></a>
</div>

<div align="center">
  <!-- Keep these links. Translations will automatically update with the README. -->
  <a href="https://www.readme-i18n.com/TauricResearch/TradingAgents?lang=de">Deutsch</a> | 
  <a href="https://www.readme-i18n.com/TauricResearch/TradingAgents?lang=es">Español</a> | 
  <a href="https://www.readme-i18n.com/TauricResearch/TradingAgents?lang=fr">français</a> | 
  <a href="https://www.readme-i18n.com/TauricResearch/TradingAgents?lang=ja">日本語</a> | 
  <a href="https://www.readme-i18n.com/TauricResearch/TradingAgents?lang=ko">한국어</a> | 
  <a href="https://www.readme-i18n.com/TauricResearch/TradingAgents?lang=pt">Português</a> | 
  <a href="https://www.readme-i18n.com/TauricResearch/TradingAgents?lang=ru">Русский</a> | 
  <a href="https://www.readme-i18n.com/TauricResearch/TradingAgents?lang=zh">中文</a>
</div>

---

# TradingAgents: Multi-Agents LLM Crypto Research & Trading Framework

## News
- [2026-06] **TradingAgents v0.3.0** — crypto-only refactor: CoinGecko/Binance/CryptoCompare data layer, crypto-native analyst prompts (perps, on-chain, LunarCrush sentiment), Historic-Crypto backtest engine with four TA strategies, AtlasCloud and Local LLM providers, and BTC/ETH alpha benchmarks. See [PLAN.md](PLAN.md) for implementation status.
- [2026-05] **TradingAgents v0.2.5** — grounded Sentiment Analyst, GPT-5.5 model coverage, Qwen/GLM/MiniMax dual-region support, `TRADINGAGENTS_*` env-var configurability, remote Ollama support, and ticker path-traversal hardening. See [CHANGELOG.md](CHANGELOG.md) for the full list.
- [2026-04] **TradingAgents v0.2.4** — structured-output agents, LangGraph checkpoint resume, persistent decision log, DeepSeek/Qwen/GLM/Azure provider support, Docker, and a Windows UTF-8 encoding fix.
- [2026-02] **TradingAgents v0.2.0** — multi-provider LLM support and improved system architecture.
- [2026-01] **Trading-R1** [Technical Report](https://arxiv.org/abs/2509.11420) released, with [Terminal](https://github.com/TauricResearch/Trading-R1) expected to land soon.

<div align="center">
<a href="https://www.star-history.com/#TauricResearch/TradingAgents&Date">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=TauricResearch/TradingAgents&type=Date&theme=dark" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/svg?repos=TauricResearch/TradingAgents&type=Date" />
   <img alt="TradingAgents Star History" src="https://api.star-history.com/svg?repos=TauricResearch/TradingAgents&type=Date" style="width: 80%; height: auto;" />
 </picture>
</a>
</div>

> 🎉 **TradingAgents** officially released! We have received numerous inquiries about the work, and we would like to express our thanks for the enthusiasm in our community.
>
> So we decided to fully open-source the framework. Looking forward to building impactful projects with you!

<div align="center">

🚀 [TradingAgents](#tradingagents-framework) | ⚡ [Installation & CLI](#installation-and-cli) | 📈 [Backtesting](#backtesting) | 🎬 [Demo](https://www.youtube.com/watch?v=90gr5lwjIho) | 📦 [Package Usage](#tradingagents-package) | 🤝 [Contributing](#contributing) | 📄 [Citation](#citation)

</div>

## TradingAgents Framework

TradingAgents is a multi-agent cryptocurrency research and trading framework that mirrors the dynamics of real-world crypto trading desks. By deploying specialized LLM-powered agents — from market and on-chain analysts to sentiment and news researchers, through trader and risk management teams — the platform collaboratively evaluates 24/7 crypto markets and informs trading decisions. Agents engage in dynamic discussions to pinpoint the optimal strategy.

<p align="center">
  <img src="assets/schema.png" style="width: 100%; height: auto;">
</p>

> TradingAgents is designed for research purposes. Trading performance may vary based on many factors, including the chosen backbone language models, model temperature, trading periods, data quality, and other non-deterministic factors. [It is not intended as financial, investment, or trading advice.](https://tauric.ai/disclaimer/)

Our framework decomposes complex crypto trading tasks into specialized roles.

### Analyst Team
- **Market Analyst**: Covers perpetual and spot markets — funding rates, open interest, basis vs spot, and technical indicators (RSI, MACD, Bollinger, ATR) on crypto OHLCV. Flags extreme funding and squeeze risk.
- **Fundamentals Analyst**: Evaluates on-chain and token-level metrics — TVL, FDV, market cap rank, tokenomics, and protocol revenue. No equity fundamentals (no P/E, EPS, or SEC filings).
- **Sentiment Analyst**: Aggregates LunarCrush galaxy score and social volume, crypto news headlines, and Reddit crypto communities into a grounded sentiment read.
- **News Analyst**: Monitors protocol upgrades, regulatory headlines, ETF flows, exchange events, hacks/exploits, and macro drivers (rates, USD liquidity) relevant to the target pair.

<p align="center">
  <img src="assets/analyst.png" width="100%" style="display: inline-block; margin: 0 2%;">
</p>

### Researcher Team
- Comprises both bullish and bearish researchers who critically assess the insights provided by the Analyst Team. Through structured debates, they balance potential gains against inherent risks.

<p align="center">
  <img src="assets/researcher.png" width="70%" style="display: inline-block; margin: 0 2%;">
</p>

### Trader Agent
- Composes reports from the analysts and researchers to make informed trading decisions, determining the timing and magnitude of trades.

<p align="center">
  <img src="assets/trader.png" width="70%" style="display: inline-block; margin: 0 2%;">
</p>

### Risk Management and Portfolio Manager
- Continuously evaluates portfolio risk by assessing market volatility, liquidity, and other risk factors. The risk management team evaluates and adjusts trading strategies, providing assessment reports to the Portfolio Manager for final decision.
- The Portfolio Manager approves/rejects the transaction proposal. A programmatic risk guard can veto proposals that breach configured limits (stop distance, position size, VaR, concentration).

<p align="center">
  <img src="assets/risk.png" width="70%" style="display: inline-block; margin: 0 2%;">
</p>

## Installation and CLI

### Installation

Clone TradingAgents:
```bash
git clone https://github.com/TauricResearch/TradingAgents.git
cd TradingAgents
```

Create a virtual environment in any of your favorite environment managers:
```bash
conda create -n tradingagents python=3.13
conda activate tradingagents
```

Install the package and its dependencies:
```bash
pip install .
```

### Docker

Alternatively, run with Docker:
```bash
cp .env.example .env  # add your API keys
docker compose run --rm tradingagents
```

For local models with Ollama:
```bash
docker compose --profile ollama run --rm tradingagents-ollama
```

### Required APIs

TradingAgents supports multiple LLM providers. Set the API key for your chosen provider:

```bash
export OPENAI_API_KEY=...          # OpenAI (GPT)
export GOOGLE_API_KEY=...          # Google (Gemini)
export ANTHROPIC_API_KEY=...       # Anthropic (Claude)
export XAI_API_KEY=...             # xAI (Grok)
export DEEPSEEK_API_KEY=...        # DeepSeek
export DASHSCOPE_API_KEY=...       # Qwen — International (dashscope-intl.aliyuncs.com)
export DASHSCOPE_CN_API_KEY=...    # Qwen — China (dashscope.aliyuncs.com)
export ZHIPU_API_KEY=...           # GLM via Z.AI (international)
export ZHIPU_CN_API_KEY=...        # GLM via BigModel (China, open.bigmodel.cn)
export MINIMAX_API_KEY=...         # MiniMax — Global (api.minimax.io, M2.x, 204K ctx)
export MINIMAX_CN_API_KEY=...      # MiniMax — China (api.minimaxi.com, M2.x, 204K ctx)
export OPENROUTER_API_KEY=...      # OpenRouter
export ATLASCLOUD_API_KEY=...      # AtlasCloud (DeepSeek V4 and more)
```

**AtlasCloud** — set `TRADINGAGENTS_LLM_PROVIDER=atlascloud` and `ATLASCLOUD_API_KEY`. Default endpoint: `https://api.atlascloud.ai/v1`.

**Local / custom OpenAI-compatible endpoint** — set `TRADINGAGENTS_LLM_PROVIDER=local` plus:
```bash
export LOCAL_LLM_BASE_URL=http://localhost:11434/v1   # Ollama, LM Studio, vLLM, etc.
export LOCAL_LLM_API_KEY=local                       # placeholder if the server ignores auth
export LOCAL_LLM_MODEL_NAME=qwen3:latest             # used for both quick and deep agents
```

For enterprise providers (e.g. Azure OpenAI, AWS Bedrock), copy `.env.enterprise.example` to `.env.enterprise` and fill in your credentials.

For Ollama via the dedicated provider, configure `llm_provider: "ollama"`. The default endpoint is `http://localhost:11434/v1`; set `OLLAMA_BASE_URL` to point at a remote `ollama-serve`. Pull models with `ollama pull <name>`, and pick "Custom model ID" in the CLI for any model not listed by default.

Alternatively, copy `.env.example` to `.env` and fill in your keys:
```bash
cp .env.example .env
```

`.env.example` also documents optional crypto data keys (`COINGECKO_API_KEY`, `LUNARCRUSH_API_KEY`, `CRYPTOCOMPARE_API_KEY`) and `TRADINGAGENTS_*` overrides. Binance public REST endpoints require no key for spot OHLCV and USD-M perps data.

### CLI Usage

Launch the interactive analysis CLI:
```bash
tradingagents analyze          # installed command
python -m cli.main analyze     # alternative: run directly from source
```

You will see a screen where you can select your crypto pair, analysis date, LLM provider, research depth, and more.

Skip the post-analysis backtest with `--no-backtest`:
```bash
tradingagents analyze --no-backtest
```

Enable checkpoint resume or clear saved checkpoints:
```bash
tradingagents analyze --checkpoint
tradingagents analyze --clear-checkpoints
```

### Crypto pairs

TradingAgents accepts normalized crypto pair symbols. Examples:

- `BTC/USDT`, `ETH/USDT` — spot-style pairs (Binance routing)
- `ETH/USDC`, `SOL/USD` — alternate quote currencies

<p align="center">
  <img src="assets/cli/cli_init.png" width="100%" style="display: inline-block; margin: 0 2%;">
</p>

An interface will appear showing results as they load, letting you track the agent's progress as it runs.

<p align="center">
  <img src="assets/cli/cli_news.png" width="100%" style="display: inline-block; margin: 0 2%;">
</p>

<p align="center">
  <img src="assets/cli/cli_transaction.png" width="100%" style="display: inline-block; margin: 0 2%;">
</p>

## Backtesting

TradingAgents includes a pure-code backtest engine (no LLM) that complements the multi-agent analysis pipeline. It fetches intraday crypto history via [Historic-Crypto](https://github.com/AminHP/gym-mtsim) (Coinbase candles), caches CSV locally, and evaluates four technical strategies across **8h**, **24h**, and **7d** lookback horizons:

| Strategy | Description |
|---|---|
| EMA crossover | Fast vs slow exponential moving average cross |
| RSI mean reversion | Oversold/overbought RSI thresholds |
| MACD crossover | MACD line vs signal line |
| Bollinger mean reversion | Price vs upper/lower bands |

The optimization loop runs every strategy on every horizon, scores each run by **net profit ratio**, and reports **profit factor**, **Sharpe ratio**, **max drawdown**, and trade count for the winner. After analysis completes, the CLI automatically runs this optimization and appends a **Backtest Optimization** section to the report (disable with `--no-backtest`).

### Standalone backtest command

Run optimization without the full LLM analysis:
```bash
tradingagents backtest --ticker BTC/USDT --date 2026-01-15
tradingagents backtest -t ETH/USDT -d 2026-01-15
```

Omit `--date` to use today.

### Live price bridge

After optimization, the engine can bridge the winning strategy to a current price feed:

- **Paper mode (default)** — `dummy_feed` mutates from the last historical bar.
- **Live mode** — ccxt Binance ticker for real-time prices.

Enable live mode via CLI flag or environment:
```bash
tradingagents backtest --ticker BTC/USDT --date 2026-01-15 --live
export LIVE_MODE=1
# or
export TRADINGAGENTS_LIVE_MODE=true
```

## TradingAgents Package

### Implementation Details

We built TradingAgents with LangGraph to ensure flexibility and modularity. Analyst nodes fan out in parallel (configurable via `analyst_concurrency_limit`). The framework supports multiple LLM providers: OpenAI, Google, Anthropic, xAI, DeepSeek, Qwen (Alibaba DashScope, international and China endpoints), GLM (Zhipu), MiniMax (global + China), OpenRouter, **AtlasCloud**, **Local** (any OpenAI-compatible endpoint), Ollama for local models, and Azure OpenAI for enterprise.

### Data vendors

Crypto market data routes through a vendor layer (`route_to_vendor` in `tradingagents/dataflows/`):

| Category | Default vendors | Notes |
|---|---|---|
| OHLCV / indicators | Binance, CryptoCompare | CryptoCompare as fallback; optional `CRYPTOCOMPARE_API_KEY` |
| Fundamentals / tokenomics | CoinGecko | Optional `COINGECKO_API_KEY` for Pro rate limits |
| News | CryptoCompare, LunarCrush | Optional keys for higher limits and galaxy-score sentiment |
| Perps (funding, OI) | Binance | Public USD-M endpoints, no key required |

Override defaults in `DEFAULT_CONFIG["data_vendors"]` or per-tool via `tool_vendors`.

### Python Usage

To use TradingAgents inside your code, import the `tradingagents` module and initialize a `TradingAgentsGraph()` object. The `.propagate()` function will return a decision:

```python
from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG

ta = TradingAgentsGraph(debug=True, config=DEFAULT_CONFIG.copy())

# forward propagate
_, decision = ta.propagate("BTC/USDT", "2026-01-15", asset_type="crypto")
print(decision)
```

You can also adjust the default configuration to set your own choice of LLMs, debate rounds, etc.

```python
from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG

config = DEFAULT_CONFIG.copy()
config["llm_provider"] = "openai"        # openai, google, anthropic, xai, deepseek, qwen, qwen-cn, glm, glm-cn, minimax, minimax-cn, openrouter, atlascloud, local, ollama, azure
config["deep_think_llm"] = "gpt-5.5"     # Model for complex reasoning
config["quick_think_llm"] = "gpt-5.4-mini" # Model for quick tasks
config["max_debate_rounds"] = 2

ta = TradingAgentsGraph(debug=True, config=config)
_, decision = ta.propagate("ETH/USDT", "2026-01-15", asset_type="crypto")
print(decision)
```

Run backtest optimization programmatically:
```python
from tradingagents.backtest import optimize_strategies, deploy_winning_strategy, format_optimization_summary
from tradingagents.default_config import DEFAULT_CONFIG

result = optimize_strategies("BTC/USDT", "2026-01-15")
result = deploy_winning_strategy(result, DEFAULT_CONFIG)
print(format_optimization_summary(result))
```

See `tradingagents/default_config.py` for all configuration options.

## Persistence and Recovery

TradingAgents persists two kinds of state across runs.

### Decision log

The decision log is always on. Each completed run appends its decision to `~/.tradingagents/memory/trading_memory.md`. On the next run for the same ticker, TradingAgents fetches the realised return (raw and alpha vs the crypto benchmark — e.g. ETH/USDT when analyzing BTC), generates a one-paragraph reflection, and injects the most recent same-ticker decisions plus recent cross-ticker lessons into the Portfolio Manager prompt, so each analysis carries forward what worked and what didn't.

Override the path with `TRADINGAGENTS_MEMORY_LOG_PATH`. Override the benchmark with `TRADINGAGENTS_BENCHMARK_TICKER`.

### Checkpoint resume

Checkpoint resume is opt-in via `--checkpoint`. When enabled, LangGraph saves state after each node so a crashed or interrupted run resumes from the last successful step instead of starting over. On a resume run you will see `Resuming from step N for <TICKER> on <date>` in the logs; on a new run you will see `Starting fresh`. Checkpoints are cleared automatically on successful completion.

Per-ticker SQLite databases live at `~/.tradingagents/cache/checkpoints/<TICKER>.db` (override the base with `TRADINGAGENTS_CACHE_DIR`). Use `--clear-checkpoints` to reset all of them before a run.

```bash
tradingagents analyze --checkpoint           # enable for this run
tradingagents analyze --clear-checkpoints    # reset before running
```

```python
config = DEFAULT_CONFIG.copy()
config["checkpoint_enabled"] = True
ta = TradingAgentsGraph(config=config)
_, decision = ta.propagate("BTC/USDT", "2026-01-15", asset_type="crypto")
```

## Reproducibility

TradingAgents is LLM-driven, so two runs of the same ticker and date can differ. This is expected for a research tool built on language models, not a defect. The variation comes from a few distinct sources, and it helps to separate them.

Language model sampling is non-deterministic. Even at a fixed temperature, providers do not guarantee byte-identical output across calls, and reasoning models (the default GPT-5.x family, and any thinking-mode model) vary the most because their internal reasoning is itself sampled.

Live data moves. Crypto news, LunarCrush sentiment, and Reddit posts return different content as time passes, so a run today sees different inputs than a run last week even for the same historical trade date. Pin the analysis date to hold the price and indicator window fixed, but the social and news sources still reflect "now".

To reduce variation you can lower the sampling temperature. Set `temperature` in your config (or `TRADINGAGENTS_TEMPERATURE` in `.env`); lower values make models that honor it more repeatable. Reasoning models largely ignore temperature, so for tighter reproducibility pair a low temperature with a non-reasoning model such as `gpt-4.1`.

```python
config = DEFAULT_CONFIG.copy()
config["llm_provider"] = "openai"
config["deep_think_llm"] = "gpt-4.1"      # non-reasoning model honors temperature
config["quick_think_llm"] = "gpt-4.1"
config["temperature"] = 0.0
```

What does not vary anymore: the analyzed instrument identity is resolved deterministically from the ticker before any agent runs, and the market analyst grounds exact price and indicator claims in a verified data snapshot.

Backtest results are not guaranteed to match any published figure. Returns depend on the model, the temperature, the date range, data quality, and the sampling above. Treat the framework as a research scaffold for studying multi-agent crypto analysis, not as a strategy with a fixed, replicable return.

## Contributing

Contributions are welcome: bug fixes, documentation, and feature ideas; past contributions are credited per release in [`CHANGELOG.md`](CHANGELOG.md).

## Citation

Please reference our work if you find *TradingAgents* provides you with some help :)

```
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
