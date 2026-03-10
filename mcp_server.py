"""
AI Trading Signal Bot — MCP Server
Allows Claude Desktop and other AI agents to get trading signals automatically.

Installation:
  pip install mcp httpx

Add to Claude Desktop config (~/.claude/claude_desktop_config.json):
{
  "mcpServers": {
    "trading_signals": {
      "command": "python",
      "args": ["/path/to/mcp_server.py"]
    }
  }
}
"""

import json
import urllib.request
from typing import Optional
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field

AGENT_URL = "https://trading-agent-production-446d.up.railway.app"

mcp = FastMCP("trading_signals_mcp")


class SignalInput(BaseModel):
    coin: str = Field(
        default="BTC",
        description="Coin symbol: BTC, ETH, SOL, AVAX, LINK, DOGE, or XRP"
    )


class StatusInput(BaseModel):
    coin: str = Field(
        default="BTC",
        description="Coin symbol: BTC, ETH, SOL, AVAX, LINK, DOGE, or XRP"
    )


def fetch_url(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "MCP-Trading-Bot/1.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())


@mcp.tool(
    name="trading_get_free_status",
    annotations={
        "title": "Get Free Trading Status",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
async def get_free_status(params: StatusInput) -> str:
    """
    Get free trading status for a coin — no payment required.
    Returns current price, signal action (BUY/SELL/HOLD), confidence,
    and multi-timeframe trend (1h/4h/1d).
    Use this before deciding whether to purchase a full signal.
    """
    coin = params.coin.upper()
    valid = ["BTC", "ETH", "SOL", "AVAX", "LINK", "DOGE", "XRP"]
    if coin not in valid:
        return "Error: unknown coin. Use one of: " + ", ".join(valid)

    try:
        data = fetch_url(AGENT_URL + "/status/" + coin)
        if data.get("status") == "pending":
            return coin + ": signal not ready yet, agent is warming up."

        tf1 = data.get("tf_1h") or {}
        tf4 = data.get("tf_4h") or {}
        tf1d = data.get("tf_1d") or {}
        news = data.get("news") or []

        lines = [
            "=== " + (data.get("symbol") or coin + "/USDT") + " ===",
            "Price: $" + str(data.get("price", "?")),
            "Signal: " + str(data.get("action", "?")) + " (confidence: " + str(int((data.get("confidence") or 0) * 100)) + "%)",
            "",
            "Timeframe trends:",
            "  1H: " + str(tf1.get("trend", "—")) + " | RSI=" + str(tf1.get("rsi", "—")) + " | MACD=" + str(tf1.get("macd", "—")),
            "  4H: " + str(tf4.get("trend", "—")) + " | RSI=" + str(tf4.get("rsi", "—")) + " | MACD=" + str(tf4.get("macd", "—")),
            "  1D: " + str(tf1d.get("trend", "—")) + " | RSI=" + str(tf1d.get("rsi", "—")) + " | MACD=" + str(tf1d.get("macd", "—")),
            "",
            "Reason: " + str(data.get("reason", "—")),
            "Updated: " + str(data.get("updated", "—")),
        ]

        if news:
            lines.append("")
            lines.append("Recent news:")
            for n in news[:3]:
                lines.append("  - " + n)

        return "\n".join(lines)

    except Exception as e:
        return "Error fetching status for " + coin + ": " + str(e)


@mcp.tool(
    name="trading_get_all_signals",
    annotations={
        "title": "Get All Free Trading Signals",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
async def get_all_signals() -> str:
    """
    Get free trading status for ALL 7 coins at once.
    Returns BTC, ETH, SOL, AVAX, LINK, DOGE, XRP signals with price,
    action, confidence and trend. Good for market overview.
    """
    coins = ["BTC", "ETH", "SOL", "AVAX", "LINK", "DOGE", "XRP"]
    results = []

    for coin in coins:
        try:
            data = fetch_url(AGENT_URL + "/status/" + coin)
            if data.get("status") == "pending":
                results.append(coin + ": pending")
                continue
            conf = int((data.get("confidence") or 0) * 100)
            tf1 = (data.get("tf_1h") or {}).get("trend", "—")
            tf4 = (data.get("tf_4h") or {}).get("trend", "—")
            tf1d = (data.get("tf_1d") or {}).get("trend", "—")
            results.append(
                coin + "/USDT | $" + str(data.get("price", "?")) +
                " | " + str(data.get("action", "?")) +
                " (" + str(conf) + "%) | 1H:" + tf1 +
                " 4H:" + tf4 + " 1D:" + tf1d
            )
        except Exception as e:
            results.append(coin + ": error — " + str(e))

    lines = ["=== AI Trading Signals — All Pairs ===", ""]
    lines += results
    lines += ["", "For detailed analysis use trading_get_free_status tool."]
    return "\n".join(lines)


@mcp.tool(
    name="trading_get_service_info",
    annotations={
        "title": "Get Trading Bot Service Info",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
async def get_service_info() -> str:
    """
    Get information about the AI Trading Signal Bot service:
    supported pairs, price per signal, features, and endpoints.
    """
    try:
        data = fetch_url(AGENT_URL + "/")
        lines = [
            "=== AI Trading Signal Bot ===",
            "Version: " + str(data.get("version", "?")),
            "Price per signal: " + str(data.get("price_per_signal", "?")),
            "Network: " + str(data.get("network", "?")),
            "Features: " + ", ".join(data.get("features") or []),
            "",
            "Supported pairs: " + ", ".join(data.get("pairs") or []),
            "",
            "Stats page: " + str(data.get("stats", "")),
            "Agent card: " + str(data.get("agent_card", "")),
        ]
        return "\n".join(lines)
    except Exception as e:
        return "Error: " + str(e)


if __name__ == "__main__":
    print("Starting AI Trading Signals MCP server...")
    mcp.run(transport="stdio")
