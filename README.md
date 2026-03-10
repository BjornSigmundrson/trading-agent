# 🤖 AI Trading Signal Bot

> BTC, ETH, SOL trading signals powered by Claude AI + x402 micropayments on Base mainnet

## What it does

Analyzes BTC/USDT, ETH/USDT, SOL/USDT every hour at :00 using 12+ indicators via Claude AI. Sells signals for **$0.50 USDC** per request using the [x402 protocol](https://x402.org) on Base mainnet. No subscriptions, no API keys — just pay per signal.

## Indicators Used

| Category | Indicators |
|----------|-----------|
| **Momentum** | RSI(14), Stochastic RSI, Williams %R, CCI |
| **Trend** | MACD, EMA 9/21/50/200 |
| **Volatility** | Bollinger Bands, ATR |
| **Volume** | Volume ratio vs 20h average |
| **Levels** | 20h Support & Resistance |

## Live Endpoints

| Endpoint | Price | Description |
|----------|-------|-------------|
| `GET /` | Free | Service info |
| `GET /status/BTC` | Free | Latest BTC price + signal |
| `GET /status/ETH` | Free | Latest ETH price + signal |
| `GET /status/SOL` | Free | Latest SOL price + signal |
| `GET /signal/BTC` | $0.50 USDC | Full BTC analysis |
| `GET /signal/ETH` | $0.50 USDC | Full ETH analysis |
| `GET /signal/SOL` | $0.50 USDC | Full SOL analysis |

**Base URL:** `https://trading-agent-production-446d.up.railway.app`

## Example Response

```bash
curl https://trading-agent-production-446d.up.railway.app/status/BTC
```

```json
{
  "status": "running",
  "symbol": "BTC/USDT",
  "price": 67089.7,
  "action": "HOLD",
  "updated": "2026-03-09T12:00:00Z"
}
```

## x402 Payment Flow

```bash
# Without payment → 402 Payment Required
curl https://trading-agent-production-446d.up.railway.app/signal/BTC

# With x402 payment → Full signal with all indicators
curl -H "X-Payment: <payment>" \
  https://trading-agent-production-446d.up.railway.app/signal/BTC
```

## Marketplaces

| Platform | Link |
|----------|------|
| thirdweb Nexus | `https://vwb011k7.nx.link/signal/BTC` |
| RelAI Market | https://relai.fi/market/1773083048448 |
| RelAI API | `https://api.relai.fi/relay/1773083048448/signal/BTC` |

## Tech Stack

- **AI:** Claude Sonnet (Anthropic)
- **Payments:** x402 protocol — USDC on Base mainnet
- **Data:** OKX / Kraken API — hourly OHLCV
- **Hosting:** Railway — 24/7 autonomous
- **Database:** PostgreSQL — persistent storage
- **Framework:** Python + Flask

---

Built on [x402 protocol](https://x402.org) · Payments on [Base](https://base.org)
