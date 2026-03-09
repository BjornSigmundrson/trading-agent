# 🤖 AI Trading Signal Bot

> BTC, ETH, SOL trading signals powered by Claude AI + x402 micropayments on Base mainnet

## What it does

Analyzes BTC/USDT, ETH/USDT, SOL/USDT every hour using RSI, MACD, and EMA indicators via Claude AI. Sells signals for **$0.50 USDC** per request using the [x402 protocol](https://x402.org) on Base mainnet. No subscriptions, no API keys — just pay per signal.

## Live Endpoints

| Endpoint | Price | Description |
|----------|-------|-------------|
| `GET /` | Free | Service info |
| `GET /status/BTC` | Free | Latest BTC price + signal |
| `GET /status/ETH` | Free | Latest ETH price + signal |
| `GET /status/SOL` | Free | Latest SOL price + signal |
| `GET /signal/BTC` | $0.50 USDC | Full BTC analysis with SL/TP |
| `GET /signal/ETH` | $0.50 USDC | Full ETH analysis with SL/TP |
| `GET /signal/SOL` | $0.50 USDC | Full SOL analysis with SL/TP |

**Base URL:** `https://trading-agent-production-446d.up.railway.app`

## Example

```bash
# Free status
curl https://trading-agent-production-446d.up.railway.app/status/BTC

# Response
{
  "status": "running",
  "symbol": "BTC/USDT",
  "price": 67089.7,
  "action": "HOLD",
  "updated": "2026-03-08T16:52:02Z"
}

# Paid signal → returns 402 without payment
curl https://trading-agent-production-446d.up.railway.app/signal/ETH
```

## Tech Stack

- **AI:** Claude Sonnet (Anthropic) — RSI + MACD + EMA analysis
- **Payments:** x402 protocol — USDC on Base mainnet
- **Data:** Coinbase API — hourly OHLCV
- **Hosting:** Railway — 24/7 autonomous operation
- **Database:** PostgreSQL — persistent signal storage

## Pairs

| Pair | Status endpoint | Signal endpoint |
|------|----------------|-----------------|
| BTC/USDT | `/status/BTC` | `/signal/BTC` |
| ETH/USDT | `/status/ETH` | `/signal/ETH` |
| SOL/USDT | `/status/SOL` | `/signal/SOL` |

---

Built on [x402 protocol](https://x402.org) · Payments on [Base](https://base.org)
