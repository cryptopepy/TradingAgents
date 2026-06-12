"""On-chain metrics stub — TVL, active addresses, gas/burn when APIs available."""

from __future__ import annotations

from typing import Annotated

from .coingecko import resolve_coin_id
from .crypto_common import env_api_key, http_get_json, no_data_message
from .symbol_utils import parse_crypto_pair

# DeFiLlama is free and requires no key for public TVL data.
_DEFILLAMA_URL = "https://api.llama.fi"


def get_onchain_metrics(
    symbol: Annotated[str, "crypto pair e.g. ETH/USDC"],
    curr_date: Annotated[str, "analysis date YYYY-MM-DD"],
) -> str:
    """Best-effort on-chain metrics: TVL (DeFiLlama), protocol revenue stubs."""
    try:
        pair = parse_crypto_pair(symbol)
    except ValueError as exc:
        return no_data_message(symbol, str(exc))

    lines = [
        f"# On-chain metrics for {pair.display}",
        f"Analysis date: {curr_date}",
        "",
    ]

    # DeFiLlama chain TVL for L1 assets
    chain_map = {
        "ETH": "Ethereum",
        "SOL": "Solana",
        "AVAX": "Avalanche",
        "BNB": "BSC",
        "MATIC": "Polygon",
        "POL": "Polygon",
        "ARB": "Arbitrum",
        "OP": "Optimism",
    }
    chain = chain_map.get(pair.base)
    if chain:
        try:
            data = http_get_json(f"{_DEFILLAMA_URL}/v2/chains")
            for entry in data:
                if entry.get("name") == chain:
                    tvl = entry.get("tvl")
                    lines.append(f"## Chain TVL ({chain})")
                    lines.append(f"Total value locked: ${tvl:,.0f}" if tvl else "TVL: N/A")
                    lines.append("")
                    break
        except Exception:
            lines.append(f"## Chain TVL ({chain}): unavailable from DeFiLlama")

    coin_id = resolve_coin_id(pair.base)
    if coin_id and pair.base == "ETH":
        lines.extend([
            "## Ethereum network notes",
            "Gas fees and burn rate vary intraday; check an explorer (e.g. etherscan.io) "
            "for live gas and ETH burn metrics at analysis time.",
            "Active addresses: use Glassnode or Nansen when API keys are configured.",
        ])
        glassnode_key = env_api_key("GLASSNODE_API_KEY", "TRADINGAGENTS_GLASSNODE_API_KEY")
        if glassnode_key:
            lines.append("(GLASSNODE_API_KEY is set — extend onchain_metrics.py for live queries.)")
    elif not chain:
        lines.append(
            "No chain-specific TVL mapping for this asset. "
            "Use CoinGecko fundamentals for market-level metrics."
        )

    if len(lines) <= 4:
        return no_data_message(symbol, "no on-chain metrics available for this asset")
    return "\n".join(lines)
