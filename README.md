# 🤖 AI Trading Signal Bot

> BTC/USDT trading signals powered by Claude AI + x402 micropayments on Base mainnet

## What it does

Analyzes BTC/USDT every hour using RSI, MACD, and EMA indicators via Claude AI (Sonnet). Sells signals for **$0.50 USDC** per request using the [x402 protocol](https://x402.org) on Base mainnet. No subscriptions, no API keys — just pay per signal.

## Live Endpoints

| Endpoint | Price | Description |
|----------|-------|-------------|
| `GET /` | Free | Service info |
| `GET /status` | Free | Latest BTC price + signal |
| `GET /signal` | $0.50 USDC | Full AI analysis with SL/TP |

**Base URL:** `https://trading-agent-production-446d.up.railway.app`

## Example Response

```bash
curl https://trading-agent-production-446d.up.railway.app/status
```

```json
{
  "status": "running",
  "symbol": "BTC/USDT",
  "price": 67089.7,
  "action": "HOLD",
  "updated": "2026-03-08T16:52:02Z"
}
```

## x402 Payment Flow

```bash
# Without payment → 402 Payment Required
curl https://trading-agent-production-446d.up.railway.app/signal

# With x402 payment header → Full signal
curl -H "X-Payment: <payment>" \
  https://trading-agent-production-446d.up.railway.app/signal
```

## Tech Stack

- **AI:** Claude Sonnet (Anthropic) — RSI + MACD + EMA analysis
- **Payments:** x402 protocol — USDC on Base mainnet
- **Data:** Kraken API — hourly BTC/USDT OHLCV
- **Hosting:** Railway — 24/7 autonomous operation
- **Database:** PostgreSQL — persistent signal storage

## Built with

- Python + Flask
- LangChain + Anthropic
- ccxt + pandas + ta
- x402 protocol

---

Built on [x402 protocol](https://x402.org) · Payments on [Base](https://base.org)
