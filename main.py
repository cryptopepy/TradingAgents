"""Demo entry point — propagate analysis for a user-selected crypto pair."""

from __future__ import annotations

import argparse
import os
import sys

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.trading_graph import TradingAgentsGraph

# DEFAULT_CONFIG already applies TRADINGAGENTS_* env-var overrides
# (llm_provider, deep_think_llm, quick_think_llm, backend_url, etc.),
# so users can switch models or endpoints purely via .env without
# editing this script.


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a single TradingAgents propagate() demo for a crypto pair.",
    )
    parser.add_argument(
        "--ticker",
        default=os.environ.get("DEMO_TICKER"),
        metavar="PAIR",
        help="Crypto pair (e.g. BTC/USDT, ETH/USDC). Env: DEMO_TICKER",
    )
    parser.add_argument(
        "--date",
        default=os.environ.get("DEMO_DATE"),
        metavar="YYYY-MM-DD",
        help="Analysis date. Env: DEMO_DATE",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if not args.ticker or not args.date:
        print(
            "Error: --ticker and --date are required (or set DEMO_TICKER / DEMO_DATE).\n"
            "Example: python main.py --ticker BTC/USDT --date 2026-06-11",
            file=sys.stderr,
        )
        return 1

    config = DEFAULT_CONFIG.copy()
    ta = TradingAgentsGraph(debug=True, config=config)
    _, decision = ta.propagate(args.ticker, args.date)
    print(decision)
    return 0


if __name__ == "__main__":
    sys.exit(main())
