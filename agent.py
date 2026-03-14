import os
import json
import time
import threading
import websocket
import json as _json_ws
import datetime
import urllib.request
import xml.etree.ElementTree as ET
import pandas as pd
import ta
import ccxt
import psycopg2
from dotenv import load_dotenv
from langchain_anthropic import ChatAnthropic

load_dotenv(override=False)

SYMBOLS = [
    "BTC/USDT", "ETH/USDT", "SOL/USDT",
    "AVAX/USDT", "LINK/USDT", "DOGE/USDT", "XRP/USDT"
]

# RSS feeds — filter by coin keyword
NEWS_FEEDS = [
    "https://cointelegraph.com/rss",
    "https://coindesk.com/arc/outboundfeeds/rss/",
    "https://decrypt.co/feed",
    "https://cryptopotato.com/feed/",
    "https://beincrypto.com/feed/",
]

api_key = os.getenv("ANTHROPIC_API_KEY")
if not api_key:
    print("ANTHROPIC_API_KEY not found")
    exit(1)
print("Anthropic API key found")


EXCHANGES = None

def init_exchanges():
    global EXCHANGES
    exs = []
    # coinbaseadvanced removed — causes hangs; bybit geo-blocked on Railway
    for cls in [ccxt.okx, ccxt.kucoin, ccxt.kraken]:
        try:
            ex = cls()
            ex.load_markets()
            exs.append(ex)
            print("Exchange loaded: " + ex.id)
        except Exception as e:
            print("Exchange skip " + cls.__name__ + ": " + str(e))
    if not exs:
        raise Exception("No exchanges available")
    EXCHANGES = exs
    print("Total exchanges: " + str(len(EXCHANGES)))


def fetch_ohlcv_hyperliquid(coin, timeframe, limit=200):
    """Fetch OHLCV candles from Hyperliquid — free, no geo-block."""
    # Hyperliquid timeframe map
    tf_map = {
        "1h": "1h", "4h": "4h", "1d": "1d",
        "15m": "15m", "5m": "5m", "1m": "1m"
    }
    hl_tf = tf_map.get(timeframe, timeframe)
    try:
        now_ms = int(time.time() * 1000)
        # startTime = now - limit * tf_ms
        tf_ms = {"1m": 60000, "5m": 300000, "15m": 900000,
                 "1h": 3600000, "4h": 14400000, "1d": 86400000}
        start_ms = now_ms - limit * tf_ms.get(hl_tf, 3600000)

        body = json.dumps({
            "type": "candleSnapshot",
            "req": {
                "coin": coin,
                "interval": hl_tf,
                "startTime": start_ms,
                "endTime": now_ms
            }
        })
        req = urllib.request.Request(
            "https://api.hyperliquid.xyz/info",
            data=body.encode(),
            headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            candles = json.loads(resp.read().decode())

        if not candles or len(candles) < 10:
            return None

        # Convert to OHLCV format: [timestamp, open, high, low, close, volume]
        ohlcv = []
        for c in candles:
            ohlcv.append([
                int(c.get("t", 0)),
                float(c.get("o", 0)),
                float(c.get("h", 0)),
                float(c.get("l", 0)),
                float(c.get("c", 0)),
                float(c.get("v", 0))
            ])
        return ohlcv

    except Exception as e:
        print("HL OHLCV error " + coin + " " + timeframe + ": " + str(e))
        return None


def fetch_ohlcv_with_fallback(symbol, timeframe, limit=200):
    """Fetch OHLCV — Hyperliquid first (free, fast), then CEX fallback."""
    coin = symbol.split("/")[0].upper()

    # Try Hyperliquid first
    ohlcv = fetch_ohlcv_hyperliquid(coin, timeframe, limit)
    if ohlcv and len(ohlcv) >= 50:
        print("  " + symbol + " " + timeframe + " from hyperliquid")
        return ohlcv

    # Fallback to CEX exchanges
    errors = []
    for ex in EXCHANGES:
        try:
            if symbol not in ex.markets:
                continue
            ohlcv = ex.fetch_ohlcv(symbol, timeframe, limit=limit)
            if ohlcv and len(ohlcv) >= 50:
                print("  " + symbol + " " + timeframe + " from " + ex.id)
                return ohlcv
        except Exception as e:
            errors.append(ex.id + ": " + str(e))
            continue

    raise Exception("All sources failed for " + symbol + " " + timeframe + ": " + str(errors))


def fetch_news(coin):
    """Fetch coin-specific news from multiple RSS feeds filtered by keyword."""
    coin_name = coin.split("/")[0].lower()
    name_map = {
        "btc": ["bitcoin", "btc"],
        "eth": ["ethereum", "eth", "ether"],
        "sol": ["solana", "sol"],
        "avax": ["avalanche", "avax"],
        "link": ["chainlink", "link"],
        "doge": ["dogecoin", "doge"],
        "xrp": ["xrp", "ripple"],
    }
    keywords = name_map.get(coin_name, [coin_name])
    headlines = []
    seen = set()

    for feed_url in NEWS_FEEDS:
        try:
            req = urllib.request.Request(feed_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=8) as resp:
                raw = resp.read()
            root = ET.fromstring(raw)
            for item in root.iter("item"):
                title_el = item.find("title")
                if title_el is not None and title_el.text:
                    title = title_el.text.strip()
                    if title in seen:
                        continue
                    if any(kw in title.lower() for kw in keywords):
                        seen.add(title)
                        headlines.append(title)
                    if len(headlines) >= 8:
                        break
        except Exception:
            continue
        if len(headlines) >= 8:
            break

    # If fewer than 3 coin-specific headlines, add general crypto news
    if len(headlines) < 3:
        for feed_url in NEWS_FEEDS[:2]:
            try:
                req = urllib.request.Request(feed_url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=8) as resp:
                    raw = resp.read()
                root = ET.fromstring(raw)
                for item in root.iter("item"):
                    title_el = item.find("title")
                    if title_el is not None and title_el.text:
                        title = title_el.text.strip()
                        if title not in seen:
                            seen.add(title)
                            headlines.append(title)
                    if len(headlines) >= 5:
                        break
            except Exception:
                continue
            if len(headlines) >= 5:
                break

    return headlines[:8]


def fetch_fear_greed():
    """Fetch Fear & Greed Index from alternative.me — free, no key needed."""
    try:
        req = urllib.request.Request(
            "https://api.alternative.me/fng/?limit=2",
            headers={"User-Agent": "Mozilla/5.0"}
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode())
        today = data["data"][0]
        yesterday = data["data"][1]
        value = int(today["value"])
        label = today["value_classification"]
        change = value - int(yesterday["value"])
        direction = "↑" if change > 0 else "↓" if change < 0 else "→"
        print("Fear&Greed: " + str(value) + " (" + label + ") " + direction + str(abs(change)))
        return {
            "value": value,
            "label": label,
            "change": change,
            "direction": direction
        }
    except Exception as e:
        print("Fear&Greed error: " + str(e))
        return None


def fetch_liquidations(symbol):
    """Fetch liquidation data from Hyperliquid — free, no key, no geo-block."""
    coin = symbol.split("/")[0].upper()
    result = {}

    try:
        # Get liquidation levels (open interest by price level)
        body = json.dumps({"type": "clearinghouseState", "user": "0x0000000000000000000000000000000000000000"}).encode()
        # Use metaAndAssetCtxs for funding + OI data
        body2 = json.dumps({"type": "metaAndAssetCtxs"}).encode()
        req = urllib.request.Request(
            "https://api.hyperliquid.xyz/info",
            data=body2,
            headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())

        # data[0] = meta (universe list), data[1] = asset contexts
        if isinstance(data, list) and len(data) >= 2:
            universe = data[0].get("universe", [])
            asset_ctxs = data[1]

            # Find our coin index
            coin_idx = None
            for i, u in enumerate(universe):
                if u.get("name") == coin:
                    coin_idx = i
                    break

            if coin_idx is not None and coin_idx < len(asset_ctxs):
                ctx = asset_ctxs[coin_idx]
                funding = float(ctx.get("funding", 0)) * 100
                open_interest = float(ctx.get("openInterest", 0))
                mark_price = float(ctx.get("markPx", 0))
                oi_usd = open_interest * mark_price

                result["funding_rate"] = round(funding, 4)
                result["open_interest_usd"] = round(oi_usd / 1e9, 3)
                result["mark_price"] = round(mark_price, 4)

                # Premium = funding rate signal
                if funding > 0.01:
                    result["funding_signal"] = "LONGS_PAYING — перегрев лонгов, риск коррекции"
                elif funding < -0.005:
                    result["funding_signal"] = "SHORTS_PAYING — возможен шорт-сквиз"
                else:
                    result["funding_signal"] = "NEUTRAL — баланс позиций"

                print(coin + " Hyperliquid: funding=" + str(funding) + "% OI=$" + str(round(oi_usd/1e6, 1)) + "M")

    except Exception as e:
        print("Hyperliquid metaAndAssetCtxs error for " + coin + ": " + str(e))

    try:
        # Get recent liquidations
        body3 = json.dumps({
            "type": "recentTrades",
            "coin": coin
        }).encode()
        # Actually use funding history for trend
        body4 = json.dumps({
            "type": "fundingHistory",
            "coin": coin,
            "startTime": int(__import__("time").time() * 1000) - 24 * 3600 * 1000
        }).encode()
        req4 = urllib.request.Request(
            "https://api.hyperliquid.xyz/info",
            data=body4,
            headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"},
            method="POST"
        )
        with urllib.request.urlopen(req4, timeout=10) as resp4:
            hist = json.loads(resp4.read().decode())

        if hist and len(hist) >= 2:
            rates = [float(h.get("fundingRate", 0)) * 100 for h in hist[-8:]]
            avg_rate = sum(rates) / len(rates) if rates else 0
            trend = "РАСТЁТ" if rates[-1] > rates[0] else "ПАДАЕТ"
            result["funding_24h_avg"] = round(avg_rate, 4)
            result["funding_trend"] = trend
            print(coin + " funding 24h avg=" + str(round(avg_rate, 4)) + "% trend=" + trend)

    except Exception as e:
        print("Hyperliquid funding history error for " + coin + ": " + str(e))

    return result


def fetch_cryptocompare_sentiment(coin_name):
    """Fetch social sentiment from CryptoCompare — free, no key needed."""
    try:
        symbol = coin_name.upper()
        url = "https://min-api.cryptocompare.com/data/social/coin/latest?fsym=" + symbol
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode())
        if data.get("Response") == "Error":
            return None
        reddit = data.get("Data", {}).get("Reddit", {})
        twitter = data.get("Data", {}).get("Twitter", {})
        result = {}
        if reddit:
            result["reddit_posts_24h"] = reddit.get("posts_per_day", 0)
            result["reddit_comments_24h"] = reddit.get("comments_per_day", 0)
        if twitter:
            result["twitter_followers"] = twitter.get("followers", 0)
            result["twitter_statuses_24h"] = twitter.get("statuses", 0)
        print(coin_name.upper() + " CryptoCompare: reddit=" + str(result.get("reddit_posts_24h", 0)) + " posts/day")
        return result
    except Exception as e:
        print("CryptoCompare error for " + coin_name + ": " + str(e))
        return None


_market_ctx_cache = {"data": None, "ts": 0}

def fetch_market_context():
    """Fetch S&P500 from Alpha Vantage — free tier 25 req/day.
    Cached for 1 hour to avoid exceeding limits (7 coins x fetch = 7 req/cycle max).
    """
    import time as _time
    global _market_ctx_cache
    # Return cached if less than 55 minutes old
    if _market_ctx_cache["data"] and (_time.time() - _market_ctx_cache["ts"]) < 3300:
        return _market_ctx_cache["data"]
    try:
        key = os.getenv("ALPHA_VANTAGE_KEY", "")
        if not key:
            return None
        # S&P500 ETF (SPY) as proxy
        url = "https://www.alphavantage.co/query?function=GLOBAL_QUOTE&symbol=SPY&apikey=" + key
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode())
        quote = data.get("Global Quote", {})
        if not quote:
            return None
        spy_price = float(quote.get("05. price", 0))
        spy_change = float(quote.get("10. change percent", "0%").replace("%", ""))
        result = {
            "spy_price": round(spy_price, 2),
            "spy_change_pct": round(spy_change, 2),
        }
        if spy_change > 1.5:
            result["signal"] = "S&P500 сильно растёт +" + str(spy_change) + "% — риск-аппетит высокий, позитивно для крипто"
        elif spy_change < -1.5:
            result["signal"] = "S&P500 падает " + str(spy_change) + "% — risk-off настроение, негативно для крипто"
        else:
            result["signal"] = "S&P500 нейтрален " + str(spy_change) + "%"
        print("Alpha Vantage SPY: " + str(spy_price) + " (" + str(spy_change) + "%)")
        _market_ctx_cache["data"] = result
        _market_ctx_cache["ts"] = _time.time()
        return result
    except Exception as e:
        print("Alpha Vantage error: " + str(e))
        return None




def fetch_onchain_metrics(coin_name):
    """
    Fetch market metrics from CoinMarketCap — 10k req/month free.
    Gives: price changes, volume, market cap, dominance, circulating supply.
    """
    cmc_key = os.getenv("CMC_API_KEY", "")
    if not cmc_key:
        return None

    symbol_map = {
        "btc": "BTC", "eth": "ETH", "sol": "SOL",
        "avax": "AVAX", "link": "LINK", "doge": "DOGE", "xrp": "XRP"
    }
    symbol = symbol_map.get(coin_name.lower())
    if not symbol:
        return None

    try:
        url = ("https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest"
               "?symbol=" + symbol + "&convert=USD")
        req = urllib.request.Request(url, headers={
            "X-CMC_PRO_API_KEY": cmc_key,
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0"
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())

        coin_data = data.get("data", {}).get(symbol, {})
        if not coin_data:
            return None

        quote = coin_data.get("quote", {}).get("USD", {})
        result = {}

        # Price changes
        c1h  = quote.get("percent_change_1h", 0) or 0
        c24h = quote.get("percent_change_24h", 0) or 0
        c7d  = quote.get("percent_change_7d", 0) or 0
        c30d = quote.get("percent_change_30d", 0) or 0
        result["change_1h"]  = round(c1h, 2)
        result["change_24h"] = round(c24h, 2)
        result["change_7d"]  = round(c7d, 1)
        result["change_30d"] = round(c30d, 1)

        # Volume and market cap
        vol_24h = quote.get("volume_24h", 0) or 0
        mcap    = quote.get("market_cap", 0) or 0
        if mcap > 0 and vol_24h > 0:
            vol_mcap = round(vol_24h / mcap * 100, 1)
            result["vol_mcap_ratio"] = vol_mcap
            if vol_mcap > 20:
                result["vol_signal"] = "Очень высокий объём/mcap " + str(vol_mcap) + "% — возможна аномальная активность"
            elif vol_mcap < 2:
                result["vol_signal"] = "Низкий объём/mcap " + str(vol_mcap) + "% — слабый интерес рынка"

        # Market dominance (only BTC/ETH)
        dom = coin_data.get("market_cap_dominance", 0) or 0
        if dom > 0:
            result["dominance"] = round(dom, 1)

        # Circulating vs max supply
        circ  = coin_data.get("circulating_supply", 0) or 0
        total = coin_data.get("total_supply", 0) or 0
        if circ and total and total > 0:
            supply_pct = round(circ / total * 100, 1)
            result["supply_pct"] = supply_pct
            if supply_pct < 50:
                result["supply_signal"] = "Только " + str(supply_pct) + "% в обращении — большая часть заблокирована"

        # Market rank
        rank = coin_data.get("cmc_rank", 0)
        if rank:
            result["rank"] = rank

        # Trend signals
        if c7d > 15:
            result["trend_7d"] = "Сильный рост за 7д: +" + str(round(c7d,1)) + "% — импульс сохраняется"
        elif c7d < -20:
            result["trend_7d"] = "Сильное падение за 7д: " + str(round(c7d,1)) + "% — возможная перепроданность"

        if c24h > 5:
            result["trend_24h"] = "Рост за 24ч: +" + str(round(c24h,1)) + "% — краткосрочный импульс"
        elif c24h < -5:
            result["trend_24h"] = "Падение за 24ч: " + str(round(c24h,1)) + "% — краткосрочное давление продавцов"

        print(coin_name.upper() + " CMC: 24h=" + str(round(c24h,1)) +
              "% 7d=" + str(round(c7d,1)) +
              "% vol/mcap=" + str(result.get("vol_mcap_ratio", "?")) + "%")
        return result if result else None

    except Exception as e:
        print("CoinMarketCap error for " + coin_name + ": " + str(e))
        return None


def analyze_timeframe(df):
    rsi = float(ta.momentum.RSIIndicator(df["close"], window=14).rsi().iloc[-1])
    stoch_rsi = ta.momentum.StochRSIIndicator(df["close"], window=14)
    stoch_k = float(stoch_rsi.stochrsi_k().iloc[-1])
    stoch_d = float(stoch_rsi.stochrsi_d().iloc[-1])
    macd_obj = ta.trend.MACD(df["close"])
    macd_val = float(macd_obj.macd().iloc[-1])
    macd_signal_val = float(macd_obj.macd_signal().iloc[-1])
    macd_hist = float(macd_obj.macd_diff().iloc[-1])
    macd_bullish = macd_val > macd_signal_val
    ema9 = float(df["close"].ewm(span=9).mean().iloc[-1])
    ema21 = float(df["close"].ewm(span=21).mean().iloc[-1])
    ema50 = float(df["close"].ewm(span=50).mean().iloc[-1])
    ema200 = float(df["close"].ewm(span=200).mean().iloc[-1])
    price = float(df["close"].iloc[-1])
    if ema9 > ema21 > ema50:
        trend = "STRONG_UP"
    elif ema9 > ema21:
        trend = "UP"
    elif ema9 < ema21 < ema50:
        trend = "STRONG_DOWN"
    elif ema9 < ema21:
        trend = "DOWN"
    else:
        trend = "FLAT"
    bb = ta.volatility.BollingerBands(df["close"], window=20, window_dev=2)
    bb_upper = float(bb.bollinger_hband().iloc[-1])
    bb_lower = float(bb.bollinger_lband().iloc[-1])
    bb_mid = float(bb.bollinger_mavg().iloc[-1])
    bb_width = round((bb_upper - bb_lower) / bb_mid * 100, 2)
    if price >= bb_upper:
        bb_position = "ABOVE_UPPER"
    elif price <= bb_lower:
        bb_position = "BELOW_LOWER"
    elif price > bb_mid:
        bb_position = "UPPER_HALF"
    else:
        bb_position = "LOWER_HALF"
    atr = float(ta.volatility.AverageTrueRange(
        df["high"], df["low"], df["close"], window=14
    ).average_true_range().iloc[-1])
    atr_pct = round(atr / price * 100, 2)
    williams_r = float(ta.momentum.WilliamsRIndicator(
        df["high"], df["low"], df["close"], lbp=14
    ).williams_r().iloc[-1])
    cci = float(ta.trend.CCIIndicator(
        df["high"], df["low"], df["close"], window=20
    ).cci().iloc[-1])
    vol_avg = float(df["vol"].tail(20).mean())
    vol_current = float(df["vol"].iloc[-1])
    vol_ratio = round(vol_current / vol_avg, 2)
    if vol_ratio > 1.5:
        vol_signal = "HIGH"
    elif vol_ratio < 0.5:
        vol_signal = "LOW"
    else:
        vol_signal = "NORMAL"
    return {
        "price": round(price, 6),
        "rsi": round(rsi, 1),
        "stoch_k": round(stoch_k * 100, 1),
        "stoch_d": round(stoch_d * 100, 1),
        "macd": "BULLISH" if macd_bullish else "BEARISH",
        "macd_hist": round(macd_hist, 6),
        "trend": trend,
        "above_ema200": price > ema200,
        "ema9": round(ema9, 6),
        "ema21": round(ema21, 6),
        "ema50": round(ema50, 6),
        "ema200": round(ema200, 6),
        "bb_position": bb_position,
        "bb_width": bb_width,
        "bb_upper": round(bb_upper, 6),
        "bb_lower": round(bb_lower, 6),
        "atr_pct": atr_pct,
        "williams_r": round(williams_r, 1),
        "cci": round(cci, 1),
        "volume": vol_signal,
        "vol_ratio": vol_ratio,
        "resistance": round(float(df["high"].tail(20).max()), 6),
        "support": round(float(df["low"].tail(20).min()), 6),
    }



def detect_rsi_divergence(df, periods=14, lookback=20):
    """
    Определяет дивергенцию RSI:
    - Bearish: цена делает новый максимум, RSI нет → сигнал разворота вниз
    - Bullish: цена делает новый минимум, RSI нет → сигнал разворота вверх
    Возвращает dict с типом дивергенции и силой.
    """
    try:
        if len(df) < lookback + periods:
            return {"type": "NONE", "strength": 0}

        closes = df["close"].values[-lookback:]
        # RSI через pandas
        delta = df["close"].diff()
        gain = delta.clip(lower=0).rolling(periods).mean()
        loss = (-delta.clip(upper=0)).rolling(periods).mean()
        rs = gain / loss.replace(0, 1e-10)
        rsi_series = (100 - 100 / (1 + rs)).values[-lookback:]

        # Найдём последние 2 локальных максимума цены
        price_highs = []
        rsi_highs = []
        price_lows = []
        rsi_lows = []

        for i in range(2, len(closes) - 1):
            if closes[i] > closes[i-1] and closes[i] > closes[i+1]:
                price_highs.append((i, closes[i]))
                rsi_highs.append((i, rsi_series[i]))
            if closes[i] < closes[i-1] and closes[i] < closes[i+1]:
                price_lows.append((i, closes[i]))
                rsi_lows.append((i, rsi_series[i]))

        result = {"type": "NONE", "strength": 0, "description": ""}

        # Bearish divergence: цена растёт, RSI падает
        if len(price_highs) >= 2 and len(rsi_highs) >= 2:
            ph1, ph2 = price_highs[-2], price_highs[-1]
            rh1, rh2 = rsi_highs[-2], rsi_highs[-1]
            if ph2[1] > ph1[1] and rh2[1] < rh1[1]:
                strength = round((ph2[1] - ph1[1]) / ph1[1] * 100, 2)
                rsi_drop = round(rh1[1] - rh2[1], 1)
                result = {
                    "type": "BEARISH",
                    "strength": min(strength, 5.0),
                    "description": "⚠️ Медвежья дивергенция RSI: цена ↑" + str(strength) + "% но RSI ↓" + str(rsi_drop) + "п — истощение роста"
                }

        # Bullish divergence: цена падает, RSI растёт
        if len(price_lows) >= 2 and len(rsi_lows) >= 2:
            pl1, pl2 = price_lows[-2], price_lows[-1]
            rl1, rl2 = rsi_lows[-2], rsi_lows[-1]
            if pl2[1] < pl1[1] and rl2[1] > rl1[1]:
                strength = round((pl1[1] - pl2[1]) / pl1[1] * 100, 2)
                rsi_rise = round(rl2[1] - rl1[1], 1)
                result = {
                    "type": "BULLISH",
                    "strength": min(strength, 5.0),
                    "description": "✅ Бычья дивергенция RSI: цена ↓" + str(strength) + "% но RSI ↑" + str(rsi_rise) + "п — скрытая сила"
                }

        return result
    except Exception as e:
        return {"type": "NONE", "strength": 0, "description": ""}


def find_volume_levels(df, n_levels=3, min_vol_multiplier=1.5):
    """
    Находит уровни поддержки/сопротивления по объёму.
    Реальные S/R — там где исторически был высокий объём.
    Возвращает список уровней с объёмом и типом.
    """
    try:
        if len(df) < 20:
            return []

        avg_vol = df["vol"].mean()
        if avg_vol == 0:
            return []

        # Фильтруем свечи с высоким объёмом
        high_vol = df[df["vol"] > avg_vol * min_vol_multiplier].copy()
        if len(high_vol) < 3:
            return []

        current_price = df["close"].iloc[-1]
        levels = []

        for _, row in high_vol.iterrows():
            # Средняя цена свечи с высоким объёмом = значимый уровень
            level_price = (row["high"] + row["low"]) / 2
            vol_ratio = round(row["vol"] / avg_vol, 1)

            level_type = "RESISTANCE" if level_price > current_price else "SUPPORT"
            levels.append({
                "price": round(level_price, 6),
                "vol_ratio": vol_ratio,
                "type": level_type
            })

        # Кластеризуем близкие уровни (в пределах 0.5%)
        clustered = []
        used = set()
        levels_sorted = sorted(levels, key=lambda x: x["price"])

        for i, lvl in enumerate(levels_sorted):
            if i in used:
                continue
            cluster = [lvl]
            for j, other in enumerate(levels_sorted):
                if j != i and j not in used:
                    if abs(other["price"] - lvl["price"]) / lvl["price"] < 0.005:
                        cluster.append(other)
                        used.add(j)
            used.add(i)
            # Берём уровень с максимальным объёмом в кластере
            best = max(cluster, key=lambda x: x["vol_ratio"])
            clustered.append(best)

        # Сортируем по объёму и берём топ N
        clustered.sort(key=lambda x: x["vol_ratio"], reverse=True)
        top = clustered[:n_levels * 2]

        # Разделяем на support и resistance
        supports = sorted([l for l in top if l["type"] == "SUPPORT"],
                         key=lambda x: x["price"], reverse=True)[:n_levels]
        resistances = sorted([l for l in top if l["type"] == "RESISTANCE"],
                            key=lambda x: x["price"])[:n_levels]

        return supports + resistances

    except Exception as e:
        return []

def get_market_data(symbol):
    result = {"symbol": symbol}
    ohlcv_1h = fetch_ohlcv_with_fallback(symbol, "1h", limit=200)
    df_1h = pd.DataFrame(ohlcv_1h, columns=["ts", "open", "high", "low", "close", "vol"])
    result["tf_1h"] = analyze_timeframe(df_1h)
    result["price"] = result["tf_1h"]["price"]

    # RSI divergence on 1H
    result["divergence_1h"] = detect_rsi_divergence(df_1h)

    # Volume-based S/R on 1H
    result["vol_levels_1h"] = find_volume_levels(df_1h, n_levels=3)

    try:
        ohlcv_4h = fetch_ohlcv_with_fallback(symbol, "4h", limit=200)
        df_4h = pd.DataFrame(ohlcv_4h, columns=["ts", "open", "high", "low", "close", "vol"])
        result["tf_4h"] = analyze_timeframe(df_4h)
        result["divergence_4h"] = detect_rsi_divergence(df_4h)
        result["vol_levels_4h"] = find_volume_levels(df_4h, n_levels=2)
    except Exception as e:
        print("4h error: " + str(e))
        result["tf_4h"] = None
        result["divergence_4h"] = {"type": "NONE"}
        result["vol_levels_4h"] = []
    try:
        ohlcv_1d = fetch_ohlcv_with_fallback(symbol, "1d", limit=200)
        df_1d = pd.DataFrame(ohlcv_1d, columns=["ts", "open", "high", "low", "close", "vol"])
        result["tf_1d"] = analyze_timeframe(df_1d)
        result["divergence_1d"] = detect_rsi_divergence(df_1d)
    except Exception as e:
        print("1d error: " + str(e))
        result["tf_1d"] = None
        result["divergence_1d"] = {"type": "NONE"}
    return result



# Coin-specific thresholds
COIN_PROFILES = {
    "BTC": {
        "rsi_buy_max": 65,
        "rsi_sell_min": 65,
        "stoch_overbought": 82,
        "vol_warn": 0.4,
        "min_signals": 3,
        "description": "Blue chip — чёткие пороги RSI"
    },
    "ETH": {
        "rsi_buy_max": 65,
        "rsi_sell_min": 65,
        "stoch_overbought": 82,
        "vol_warn": 0.4,
        "min_signals": 3,
        "description": "Blue chip — чёткие пороги RSI"
    },
    "SOL": {
        "rsi_buy_max": 66,
        "rsi_sell_min": 64,
        "stoch_overbought": 80,
        "vol_warn": 0.5,
        "min_signals": 3,
        "description": "Высокая бета — умеренные пороги"
    },
    "AVAX": {
        "rsi_buy_max": 67,
        "rsi_sell_min": 63,
        "stoch_overbought": 78,
        "vol_warn": 0.5,
        "min_signals": 3,
        "description": "Высокая бета — умеренные пороги"
    },
    "LINK": {
        "rsi_buy_max": 67,
        "rsi_sell_min": 63,
        "stoch_overbought": 78,
        "vol_warn": 0.5,
        "min_signals": 3,
        "description": "Высокая бета — умеренные пороги"
    },
    "DOGE": {
        "rsi_buy_max": 70,    # Meme coin — очень волатилен, шире пороги
        "rsi_sell_min": 60,
        "stoch_overbought": 75,
        "vol_warn": 0.6,      # Для DOGE нужен объём
        "min_signals": 3,
        "description": "Meme coin — широкие пороги, объём важен"
    },
    "XRP": {
        "rsi_buy_max": 68,
        "rsi_sell_min": 62,
        "stoch_overbought": 78,
        "vol_warn": 0.5,
        "min_signals": 3,
        "description": "Новостной актив — умеренные пороги"
    },
}

def get_coin_profile(symbol):
    coin = symbol.split("/")[0].upper()
    return COIN_PROFILES.get(coin, {
        "rsi_buy_max": 65, "rsi_sell_min": 65,
        "stoch_overbought": 80, "vol_warn": 0.5,
        "min_signals": 3, "description": "Default"
    })

def volume_confidence_penalty(tf_1h, tf_4h):
    """Снижает confidence если объём низкий.
    4H порог ниже чем 1H — 4H свеча естественно имеет меньший vol_ratio.
    Штраф только если ОБА таймфрейма сигнализируют об аномально низком объёме.
    """
    vol_1h = tf_1h.get("vol_ratio", 1.0)
    vol_4h = tf_4h.get("vol_ratio", 1.0)
    if vol_1h < 0.15 and vol_4h < 0.15:
        return -0.08  # Экстремально низкий объём на обоих
    if vol_1h < 0.3 and vol_4h < 0.3:
        return -0.05  # Умеренный штраф
    if vol_1h < 0.3:
        return -0.03  # Лёгкий штраф — только 1H слабый
    return 0.0        # Объём нормальный

def tf_summary(tf_data, name):
    if not tf_data:
        return name + ": unavailable"
    lines = [
        name + " (price: $" + str(tf_data["price"]) + "):",
        "  RSI=" + str(tf_data["rsi"]) + " | StochRSI K/D=" + str(tf_data["stoch_k"]) + "/" + str(tf_data["stoch_d"]),
        "  MACD=" + tf_data["macd"] + " (hist=" + str(tf_data["macd_hist"]) + ")",
        "  Trend=" + tf_data["trend"] + " | Above EMA200=" + str(tf_data["above_ema200"]),
        "  BB=" + tf_data["bb_position"] + " (width=" + str(tf_data["bb_width"]) + "%)",
        "  ATR%=" + str(tf_data["atr_pct"]) + " | Williams%R=" + str(tf_data["williams_r"]) + " | CCI=" + str(tf_data["cci"]),
        "  Volume=" + tf_data["volume"] + " (" + str(tf_data["vol_ratio"]) + "x avg)",
        "  Support=$" + str(tf_data["support"]) + " | Resistance=$" + str(tf_data["resistance"]),
    ]
    return "\n".join(lines)



PAPER_TRADE_SIZE = 100  # $100 на каждую сделку
PAPER_INITIAL_BALANCE = 1000  # Стартовый баланс $1000

def paper_check_open_trades(conn, current_prices):
    """Проверяет открытые сделки — закрывает по SL/TP или обновляет P&L."""
    try:
        cur = conn.cursor()
        cur.execute("SELECT id, symbol, action, entry_price, stop_loss, take_profit, size_usd FROM paper_trades WHERE status='OPEN'")
        trades = cur.fetchall()

        for trade in trades:
            tid, symbol, action, entry, sl, tp, size = trade
            coin = symbol.split("/")[0]
            price = current_prices.get(coin)
            if not price:
                continue

            pnl_pct = 0
            exit_reason = None

            if action == "BUY":
                pnl_pct = (price - entry) / entry * 100
                if sl and price <= sl:
                    exit_reason = "STOP_LOSS"
                elif tp and price >= tp:
                    exit_reason = "TAKE_PROFIT"
            elif action == "SELL":
                pnl_pct = (entry - price) / entry * 100
                if sl and price >= sl:
                    exit_reason = "STOP_LOSS"
                elif tp and price <= tp:
                    exit_reason = "TAKE_PROFIT"

            pnl_usd = round(size * pnl_pct / 100, 2)

            # Auto-close trades older than 24 hours with no significant movement
            if not exit_reason:
                import datetime as _dt
                cur.execute("SELECT opened_at FROM paper_trades WHERE id=%s", (tid,))
                opened_row = cur.fetchone()
                if opened_row:
                    age_hours = (_dt.datetime.now(_dt.timezone.utc) - opened_row[0].replace(tzinfo=_dt.timezone.utc)).total_seconds() / 3600
                    if age_hours >= 24:
                        exit_reason = "TIMEOUT_24H"
                        print("Paper trade TIMEOUT 24H: " + symbol + " P&L=" + str(round(pnl_pct,2)) + "%")

            if exit_reason:
                cur.execute("""
                    UPDATE paper_trades
                    SET status='CLOSED', exit_price=%s, pnl_usd=%s, pnl_pct=%s,
                        exit_reason=%s, closed_at=NOW()
                    WHERE id=%s
                """, (price, pnl_usd, round(pnl_pct, 2), exit_reason, tid))
                # Update portfolio balance
                cur.execute("UPDATE paper_portfolio SET balance = balance + %s, updated_at=NOW()", (pnl_usd,))
                conn.commit()
                print("Paper trade CLOSED: " + symbol + " " + action + " " + exit_reason + " P&L: $" + str(pnl_usd) + " (" + str(round(pnl_pct,2)) + "%)")
            else:
                # Just update unrealized P&L
                cur.execute("""
                    UPDATE paper_trades SET pnl_usd=%s, pnl_pct=%s WHERE id=%s
                """, (pnl_usd, round(pnl_pct, 2), tid))
                conn.commit()

        cur.close()
    except Exception as e:
        print("Paper check error: " + str(e))


def paper_open_trade(conn, symbol, action, price, stop_loss, take_profit, confidence):
    """Открывает новую бумажную сделку если нет уже открытой по этой монете."""
    try:
        cur = conn.cursor()

        # Проверяем нет ли уже открытой сделки по этой монете
        cur.execute("SELECT id FROM paper_trades WHERE symbol=%s AND status='OPEN'", (symbol,))
        if cur.fetchone():
            print("Paper trade: уже есть открытая сделка по " + symbol + " — пропускаем")
            cur.close()
            return

        # Проверяем баланс
        cur.execute("SELECT balance FROM paper_portfolio ORDER BY id DESC LIMIT 1")
        row = cur.fetchone()
        balance = row[0] if row else PAPER_INITIAL_BALANCE
        if balance < PAPER_TRADE_SIZE:
            print("Paper trade: недостаточно баланса ($" + str(round(balance,2)) + ")")
            cur.close()
            return

        # Открываем сделку
        cur.execute("""
            INSERT INTO paper_trades (symbol, action, entry_price, stop_loss, take_profit, confidence, size_usd)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (symbol, action, price, stop_loss, take_profit, confidence, PAPER_TRADE_SIZE))
        conn.commit()
        cur.close()
        print("Paper trade OPENED: " + symbol + " " + action + " @ $" + str(price) +
              " SL=$" + str(stop_loss) + " TP=$" + str(take_profit))
    except Exception as e:
        print("Paper open error: " + str(e))

def run_cycle(symbol):
    try:
        market = get_market_data(symbol)
    except Exception as e:
        return {"symbol": symbol, "action": "HOLD", "confidence": 0, "reason": "Error: " + str(e)}

    news = []
    try:
        news = fetch_news(symbol)
        print("News: " + str(len(news)) + " headlines")
    except Exception as e:
        print("News error: " + str(e))

    fear_greed = None
    try:
        fear_greed = fetch_fear_greed()
    except Exception as e:
        print("FG error: " + str(e))

    liqs = {}
    try:
        liqs = fetch_liquidations(symbol)
    except Exception as e:
        print("Liqs error: " + str(e))

    # Define coin_name once for all subsequent calls
    coin_name = symbol.split("/")[0].lower()

    # CryptoCompare social sentiment
    sentiment = None
    try:
        sentiment = fetch_cryptocompare_sentiment(coin_name)
    except Exception as e:
        print("Sentiment error: " + str(e))

    # Alpha Vantage market context (S&P500)
    market_ctx = None
    try:
        market_ctx = fetch_market_context()
    except Exception as e:
        print("Market context error: " + str(e))

    # Messari on-chain metrics
    messari = None
    try:
        messari = fetch_onchain_metrics(coin_name)
    except Exception as e:
        print("Messari error: " + str(e))

    whales = []  # removed — was too noisy

    news_block = ""
    if news:
        news_block = "\nRECENT NEWS:\n" + "\n".join("- " + h for h in news) + "\n"

    fg_block = ""
    if fear_greed:
        fg_block = ("\nMARKET SENTIMENT (Fear & Greed Index):\n"
            + "  Value: " + str(fear_greed["value"]) + "/100 — " + fear_greed["label"]
            + " (change: " + fear_greed["direction"] + str(abs(fear_greed["change"])) + " vs yesterday)\n"
            + "  Interpretation: <25=Extreme Fear, 25-45=Fear, 45-55=Neutral, 55-75=Greed, >75=Extreme Greed\n")

    liqs_block = ""
    if liqs:
        parts = []
        if "funding_rate" in liqs:
            parts.append("  Funding rate: " + str(liqs["funding_rate"]) + "% — " + liqs.get("funding_signal", ""))
        if "funding_24h_avg" in liqs:
            parts.append("  Funding 24h avg: " + str(liqs["funding_24h_avg"]) + "% (trend: " + liqs.get("funding_trend", "?") + ")")
        if "open_interest_usd" in liqs:
            parts.append("  Open Interest: $" + str(liqs["open_interest_usd"]) + "B (Hyperliquid DEX)")
        if "long_liqs_24h" in liqs:
            parts.append("  Long liquidations 24h: $" + str(liqs["long_liqs_24h"]) + "M")
            parts.append("  Short liquidations 24h: $" + str(liqs["short_liqs_24h"]) + "M")
            ratio = liqs.get("liq_ratio", 0)
            if ratio > 1.5:
                parts.append("  → More LONGS liquidated = bearish pressure")
            elif ratio < 0.67:
                parts.append("  → More SHORTS liquidated = bullish pressure")
        if parts:
            liqs_block = "\nLIQUIDATIONS & OPEN INTEREST (Hyperliquid):\n" + "\n".join(parts) + "\n"

    whale_block = ""

    # Messari on-chain block
    messari_block = ""
    messari_data = messari  # use directly from fetch
    if messari_data:
        parts = []
        if messari_data.get("change_24h") is not None:
            parts.append("  Price 24h: " + ("+".join(["", str(messari_data["change_24h"])]) if messari_data["change_24h"] > 0 else str(messari_data["change_24h"])) + "%")
        if messari_data.get("change_7d") is not None:
            parts.append("  Price 7d: " + ("+" if messari_data["change_7d"] > 0 else "") + str(messari_data["change_7d"]) + "%")
        if messari_data.get("change_30d") is not None:
            parts.append("  Price 30d: " + ("+" if messari_data["change_30d"] > 0 else "") + str(messari_data["change_30d"]) + "%")
        if messari_data.get("vol_mcap_ratio"):
            parts.append("  Vol/MCap: " + str(messari_data["vol_mcap_ratio"]) + "%")
        if messari_data.get("dominance"):
            parts.append("  Dominance: " + str(messari_data["dominance"]) + "%")
        if messari_data.get("vol_signal"):
            parts.append("  " + messari_data["vol_signal"])
        if messari_data.get("trend_24h"):
            parts.append("  " + messari_data["trend_24h"])
        if messari_data.get("trend_7d"):
            parts.append("  " + messari_data["trend_7d"])
        if messari_data.get("supply_signal"):
            parts.append("  " + messari_data["supply_signal"])
        if parts:
            messari_block = "\nMARKET METRICS (CoinMarketCap):\n" + "\n".join(parts) + "\n"

    # CryptoCompare sentiment block
    sentiment_block = ""
    if sentiment:
        parts = []
        if sentiment.get("reddit_posts_24h"):
            parts.append("Reddit posts/day: " + str(sentiment["reddit_posts_24h"]))
        if sentiment.get("twitter_statuses_24h"):
            parts.append("Twitter activity: " + str(sentiment["twitter_statuses_24h"]))
        if parts:
            sentiment_block = "\nSOCIAL SENTIMENT (CryptoCompare):\n  " + " | ".join(parts) + "\n"

    # Alpha Vantage market context block
    market_ctx_block = ""
    if market_ctx and market_ctx.get("signal"):
        market_ctx_block = "\nMARKET CONTEXT (S&P500):\n  " + market_ctx["signal"] + "\n"

    # RSI Divergence block
    div_block = ""
    divs = []
    for tf_name, div_key in [("1H", "divergence_1h"), ("4H", "divergence_4h"), ("1D", "divergence_1d")]:
        div = market.get(div_key, {})
        if div and div.get("type") != "NONE" and div.get("description"):
            divs.append("  [" + tf_name + "] " + div["description"])
    if divs:
        div_block = "\nRSI DIVERGENCE (важный сигнал разворота):\n" + "\n".join(divs) + "\n"
        print(symbol.split("/")[0] + " divergence: " + " | ".join([d.strip() for d in divs]))

    # Volume S/R levels block
    vol_sr_block = ""
    all_levels = market.get("vol_levels_1h", []) + market.get("vol_levels_4h", [])
    if all_levels:
        current_price = market["price"]
        supports = sorted([l for l in all_levels if l["type"] == "SUPPORT"],
                         key=lambda x: x["price"], reverse=True)[:2]
        resistances = sorted([l for l in all_levels if l["type"] == "RESISTANCE"],
                            key=lambda x: x["price"])[:2]
        parts = []
        for r in resistances:
            dist = round((r["price"] - current_price) / current_price * 100, 1)
            parts.append("  RESISTANCE $" + str(r["price"]) + " (vol=" + str(r["vol_ratio"]) + "x, +" + str(dist) + "%)")
        for s in supports:
            dist = round((current_price - s["price"]) / current_price * 100, 1)
            parts.append("  SUPPORT $" + str(s["price"]) + " (vol=" + str(s["vol_ratio"]) + "x, -" + str(dist) + "%)")
        if parts:
            vol_sr_block = "\nVOLUME-BASED S/R LEVELS (реальные уровни по объёму):\n" + "\n".join(parts) + "\n"

    # Coin-specific profile and volume penalty
    coin = symbol.split("/")[0].upper()
    profile = get_coin_profile(symbol)
    vol_penalty = volume_confidence_penalty(market["tf_1h"], market["tf_4h"])
    if vol_penalty < 0:
        print(coin + " volume penalty: " + str(vol_penalty) + " (1H=" + str(market["tf_1h"].get("vol_ratio","?")) + "x 4H=" + str(market["tf_4h"].get("vol_ratio","?")) + "x)")

    lines = [
        "You are an aggressive professional crypto trader. Your goal is to find ACTIONABLE signals.",
        "COIN PROFILE for " + coin + ": " + profile["description"],
        "IMPORTANT RULES:",
        "1. Use 1H and 4H as PRIMARY signals. 1D is context only — do NOT let 1D alone block BUY/SELL.",
        "2. BUY signal rules (need " + str(profile["min_signals"]) + "+ of these):",
        "   - 1H trend UP or STRONG_UP",
        "   - 4H trend UP or STRONG_UP",
        "   - MACD bullish on 1H or 4H",
        "   - RSI 1H between 40-" + str(profile["rsi_buy_max"]) + " (room to grow, coin-specific)",
        "   - Price above EMA200 on 1H",
        "   - Funding rate negative or neutral (shorts paying = bullish)",
        "   - Fear & Greed < 30 (extreme fear = contrarian buy)",
        "   - StochRSI 1H not overbought (< " + str(profile["stoch_overbought"]) + ", coin-specific)",
        "3. SELL signal rules (need " + str(profile["min_signals"]) + "+ of these):",
        "   - 1H trend DOWN or STRONG_DOWN",
        "   - 4H trend DOWN or STRONG_DOWN",
        "   - MACD bearish on 1H or 4H",
        "   - RSI 1H > " + str(profile["rsi_sell_min"]) + " (coin-specific)",
        "   - Price below EMA200 on 1H",
        "   - Funding rate very positive (>0.05%, longs paying = bearish)",
        "   - StochRSI 1H overbought (> " + str(profile["stoch_overbought"]) + ", coin-specific)",
        "4. HOLD only when signals are truly mixed with NO clear edge.",
        "5. Confidence base: 0.65-0.75. Apply volume penalty: " + str(vol_penalty) + " (already calculated).",
        "   Final confidence must be: base + " + str(vol_penalty) + ". If vol_ratio 1H=" + str(round(market["tf_1h"].get("vol_ratio",1),2)) + " and 4H=" + str(round(market["tf_4h"].get("vol_ratio",1),2)) + ".",
        "6. If RSI DIVERGENCE detected — it OVERRIDES trend signals. Bearish divergence → prefer SELL/HOLD even in uptrend.",
        "7. Use VOLUME S/R levels for stop_loss and take_profit — they are stronger than simple High/Low.",
        "",
        "SYMBOL: " + market["symbol"],
        "PRICE: $" + str(market["price"]),
        "",
        tf_summary(market["tf_1h"], "1H"),
        "",
        tf_summary(market["tf_4h"], "4H"),
        "",
        tf_summary(market["tf_1d"], "1D"),
        fg_block,
        liqs_block,
        div_block,
        vol_sr_block,
        messari_block,
        sentiment_block,
        market_ctx_block,
        news_block,
        "Count the BUY/SELL rules above carefully before deciding.",
        "Reply ONLY with a raw JSON object. NO markdown, NO code fences. Keep reason under 100 words. Just the JSON:",
        '{"action":"HOLD","confidence":0.7,"stop_loss":0,"take_profit":0,"reason":"reason in Russian"}',
        "action: BUY, SELL or HOLD | confidence: 0.0-1.0 | stop_loss/take_profit: price levels",
    ]
    prompt = "\n".join(lines)

    # Retry on overload (529)
    for attempt in range(3):
        try:
            response = llm.invoke([{"role": "user", "content": prompt}])
            break
        except Exception as e:
            if "529" in str(e) or "overloaded" in str(e).lower():
                wait = 30 * (attempt + 1)
                print("Anthropic overloaded, retry in " + str(wait) + "s...")
                time.sleep(wait)
                if attempt == 2:
                    raise
            else:
                raise
    try:
        # Get raw text from response - handle both string and AIMessage
        raw = response.content if isinstance(response.content, str) else str(response.content)
        raw = raw.strip()
        print("RAW RESPONSE: " + raw[:300])
        # Save raw to file for debugging
        with open("last_raw_response.txt", "w", encoding="utf-8") as _f:
            _f.write(raw)
        # Strip markdown code fences
        import re
        raw = re.sub(r"```(?:json)?\s*", "", raw).strip()
        raw = re.sub(r"```\s*$", "", raw).strip()
        # Find JSON object
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start >= 0 and end > start:
            raw = raw[start:end]
        decision = json.loads(raw)
        print("Parse OK: action=" + str(decision.get("action")) + " conf=" + str(decision.get("confidence")))
    except Exception as e:
        print("PARSE ERROR: " + str(e))
        print("RAW WAS: " + repr(raw[:500] if "raw" in dir() else "N/A"))
        decision = {"action": "HOLD", "confidence": 0.0, "stop_loss": 0, "take_profit": 0, "reason": "Parse error: " + str(e)}

    result = {
        "symbol": symbol,
        "price": market["price"],
        "tf_1h": market["tf_1h"],
        "tf_4h": market["tf_4h"],
        "tf_1d": market["tf_1d"],
        "news": news,
        "fear_greed": fear_greed,
        "liquidations": liqs,
        "sentiment": sentiment,
        "market_context": market_ctx,
        "messari": messari,
        "whale_alerts": [],
    }
    result.update(decision)
    result["timestamp"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    return result


def save_to_db(symbol, signal):
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        return None
    conn = psycopg2.connect(db_url)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO signals (symbol, data) VALUES (%s, %s) RETURNING id",
        [symbol, json.dumps(signal)],
    )
    signal_id = cur.fetchone()[0]
    conn.commit()
    cur.close()
    conn.close()
    return signal_id


def save_signal(symbol, signal):
    key = symbol.replace("/", "_")
    with open("signal_" + key + ".json", "w", encoding="utf-8") as f:
        json.dump(signal, f, ensure_ascii=False, indent=2)
    if symbol == "BTC/USDT":
        with open("last_signal.json", "w", encoding="utf-8") as f:
            json.dump(signal, f, ensure_ascii=False, indent=2)
    print("Saved: signal_" + key + ".json")
    try:
        save_to_db(symbol, signal)
        print("Saved to DB: " + symbol)
    except Exception as e:
        print("DB error: " + str(e))


def wait_until_next_hour():
    now = datetime.datetime.now()
    next_hour = now.replace(minute=0, second=0, microsecond=0) + datetime.timedelta(hours=1)
    wait = (next_hour - now).total_seconds()
    print("Next cycle at " + next_hour.strftime("%H:00") + " (wait " + str(int(wait // 60)) + " min)")
    time.sleep(wait)



# Price monitor state
_price_history = {}   # {coin: [(timestamp, price), ...]}
_last_emergency = {}  # {coin: timestamp} — throttle emergency signals
_emergency_lock = threading.Lock()

# Hyperliquid coin → symbol map
HL_COINS = {
    "BTC": "BTC", "ETH": "ETH", "SOL": "SOL",
    "AVAX": "AVAX", "LINK": "LINK", "DOGE": "DOGE", "XRP": "XRP"
}


def get_price_change_pct(coin, minutes=15):
    """Check % price change over last N minutes from history."""
    history = _price_history.get(coin, [])
    if len(history) < 2:
        return 0
    now = time.time()
    cutoff = now - (minutes * 60)
    old_prices = [p for t, p in history if t <= cutoff]
    if not old_prices:
        return 0
    old_price = old_prices[-1]
    current_price = history[-1][1]
    if old_price <= 0:
        return 0
    return (current_price - old_price) / old_price * 100


# Live price cache from WebSocket
_live_prices = {}  # {coin: price} — updated in real-time

def on_hl_message(ws, message):
    """Handle incoming Hyperliquid WebSocket message."""
    try:
        data = _json_ws.loads(message)
        channel = data.get("channel", "")

        if channel == "trades":
            trades = data.get("data", [])
            for trade in trades:
                coin = trade.get("coin", "")
                if coin not in HL_COINS:
                    continue
                price = float(trade.get("px", 0))
                if not price:
                    continue

                # Update live price cache
                _live_prices[coin] = price
                # Write to shared file for server to read
                try:
                    import json as _jw
                    with open("/tmp/hl_live_prices.json", "w") as _f:
                        _jw.dump(_live_prices, _f)
                except:
                    pass

                now = time.time()
                if coin not in _price_history:
                    _price_history[coin] = []
                _price_history[coin].append((now, price))
                _price_history[coin] = [(t, p) for t, p in _price_history[coin] if t > now - 1800]

                # Check emergency trigger
                change_15m = get_price_change_pct(coin, 15)
                change_5m  = get_price_change_pct(coin, 5)
                trigger = abs(change_15m) > 3.0 or abs(change_5m) > 2.0

                if trigger:
                    last_em = _last_emergency.get(coin, 0)
                    if now - last_em > 1800:
                        direction = "↑" if change_15m > 0 else "↓"
                        print("⚡ EMERGENCY: " + coin + " " + direction +
                              str(round(change_15m, 1)) + "% in 15min")
                        _last_emergency[coin] = now
                        sym = coin + "/USDT"
                        with _emergency_lock:
                            try:
                                signal = run_cycle(sym)
                                vol_pen = volume_confidence_penalty(
                                    signal.get("tf_1h") or {}, signal.get("tf_4h") or {}
                                )
                                if vol_pen < 0 and signal.get("action") != "HOLD":
                                    signal["confidence"] = round(
                                        max(0.50, signal.get("confidence", 0.7) + vol_pen), 2
                                    )
                                signal["emergency"] = True
                                signal["trigger"] = direction + str(round(change_15m, 1)) + "% in 15min"
                                save_signal(sym, signal)
                                print("⚡ Emergency signal: " + sym + " " +
                                      signal.get("action") + " " +
                                      str(round(signal.get("confidence", 0) * 100)) + "%")
                            except Exception as se:
                                print("Emergency signal error: " + str(se))

        elif channel == "candle":
            # Real-time candle update — update live price
            candle_data = data.get("data", {})
            coin = candle_data.get("s", "").replace("-PERP", "")
            close_px = candle_data.get("c")
            if coin in HL_COINS and close_px:
                _live_prices[coin] = float(close_px)

    except Exception as e:
        print("WS message error: " + str(e))


def on_hl_open(ws):
    """Subscribe to trades and 1m candles for all our coins."""
    print("Hyperliquid WebSocket connected")
    for coin in HL_COINS:
        # Subscribe to real-time trades for price monitoring
        ws.send(_json_ws.dumps({
            "method": "subscribe",
            "subscription": {"type": "trades", "coin": coin}
        }))
        # Subscribe to 1m candles for technical updates
        ws.send(_json_ws.dumps({
            "method": "subscribe",
            "subscription": {"type": "candle", "coin": coin, "interval": "1m"}
        }))
    print("Subscribed trades+candles: " + ", ".join(HL_COINS.keys()))


def on_hl_error(ws, error):
    print("Hyperliquid WS error: " + str(error))


def on_hl_close(ws, close_status_code, close_msg):
    print("Hyperliquid WS closed — will reconnect in 30s")


def run_price_monitor():
    """
    Background thread — connects to Hyperliquid WebSocket.
    Receives real-time trades, triggers emergency signals on >3% moves.
    Auto-reconnects on disconnect.
    """
    print("Price monitor thread started (Hyperliquid WebSocket)")
    time.sleep(15)  # Wait for exchanges to init

    while True:
        try:
            ws = websocket.WebSocketApp(
                "wss://api.hyperliquid.xyz/ws",
                on_open=on_hl_open,
                on_message=on_hl_message,
                on_error=on_hl_error,
                on_close=on_hl_close,
            )
            ws.run_forever(ping_interval=30, ping_timeout=10)
        except Exception as e:
            print("Price monitor WS error: " + str(e))
        print("Reconnecting Hyperliquid WS in 30s...")
        time.sleep(30)


def run_paper_checker():
    """Background thread — checks paper trades every 15 minutes."""
    print("Paper checker thread started (every 15 min)")
    while True:
        try:
            time.sleep(900)  # 15 minutes
            conn = get_db()
            if not conn:
                continue
            current_prices = {}
            for sym in SYMBOLS:
                coin = sym.split("/")[0]
                try:
                    # Use live WebSocket price first
                    if coin in _live_prices:
                        current_prices[coin] = _live_prices[coin]
                        continue
                    # Fallback: CEX ticker
                    for ex in EXCHANGES:
                        try:
                            ticker = ex.fetch_ticker(sym)
                            if ticker and ticker.get("last"):
                                current_prices[coin] = float(ticker["last"])
                                break
                        except:
                            continue
                except:
                    pass
            if current_prices:
                paper_check_open_trades(conn, current_prices)
            conn.close()
        except Exception as e:
            print("Paper checker error: " + str(e))


if __name__ == "__main__":
    print("=" * 50)
    print("Agent v3 — Multi-TF + News + Accuracy Tracking")
    print("Pairs: " + ", ".join(SYMBOLS))
    print("Cycle: every hour at :00")
    print("=" * 50)

    init_db()

    # Start background paper trade checker (every 15 min)
    checker_thread = threading.Thread(target=run_paper_checker, daemon=True)
    checker_thread.start()

    # Start price monitor (every 60s, triggers emergency signals on >3% moves)
    monitor_thread = threading.Thread(target=run_price_monitor, daemon=True)
    monitor_thread.start()

    cycle = 0
    while True:
        try:
            cycle += 1
            print("\n=== Cycle #" + str(cycle) + " ===")

            # Check results of old signals
            print("\n--- Checking signal results ---")
            try:
                update_signal_results()
            except Exception as e:
                print("Results check error: " + str(e))

            # Check open paper trades — use live WebSocket prices first
            try:
                conn = get_db()
                current_prices = {}
                for sym in SYMBOLS:
                    coin = sym.split("/")[0]
                    try:
                        # 1. Use live WebSocket price (most accurate)
                        if coin in _live_prices:
                            current_prices[coin] = _live_prices[coin]
                            continue
                        # 2. Fallback: CEX ticker
                        for ex in EXCHANGES:
                            try:
                                ticker = ex.fetch_ticker(sym)
                                if ticker and ticker.get("last"):
                                    current_prices[coin] = float(ticker["last"])
                                    break
                            except:
                                continue
                    except Exception as pe:
                        print("Price fetch error " + sym + ": " + str(pe))
                print("Paper prices: " + str({k: round(v,4) for k,v in current_prices.items()}))
                if current_prices:
                    paper_check_open_trades(conn, current_prices)
                conn.close()
            except Exception as e:
                print("Paper check error: " + str(e))

            # Run new signals
            for symbol in SYMBOLS:
                print("\n--- " + symbol + " ---")
                signal = run_cycle(symbol)
                tf1 = signal.get("tf_1h") or {}
                tf4 = signal.get("tf_4h") or {}
                tf1d = signal.get("tf_1d") or {}
                print("Price: $" + str(signal.get("price", 0)))
                print("1H: RSI=" + str(tf1.get("rsi")) + " MACD=" + str(tf1.get("macd")) + " Trend=" + str(tf1.get("trend")))
                print("4H: RSI=" + str(tf4.get("rsi")) + " MACD=" + str(tf4.get("macd")) + " Trend=" + str(tf4.get("trend")))
                print("1D: RSI=" + str(tf1d.get("rsi")) + " MACD=" + str(tf1d.get("macd")) + " Trend=" + str(tf1d.get("trend")))

                # Apply volume confidence penalty
                vol_penalty = volume_confidence_penalty(
                    signal.get("tf_1h") or {}, signal.get("tf_4h") or {}
                )
                if vol_penalty < 0 and signal.get("action") != "HOLD":
                    original_conf = signal.get("confidence", 0.7)
                    signal["confidence"] = round(max(0.50, original_conf + vol_penalty), 2)
                    print("Volume penalty " + str(vol_penalty) + ": " + str(original_conf) + " → " + str(signal["confidence"]))

                print("Signal: " + str(signal.get("action")) + " | Confidence: " + str(int(signal.get("confidence", 0) * 100)) + "%")
                print(str(signal.get("reason", "")))
                save_signal(symbol, signal)

                # Paper trading — открываем сделку при BUY/SELL
                if signal.get("action") in ("BUY", "SELL"):
                    sl = signal.get("stop_loss", 0)
                    tp = signal.get("take_profit", 0)
                    price = signal.get("price", 0)
                    print("Paper debug: action=" + str(signal.get("action")) +
                          " sl=" + str(sl) + " tp=" + str(tp) + " price=" + str(price))
                    if not sl or not tp or sl <= 0 or tp <= 0:
                        tf1h = signal.get("tf_1h") or {}
                        sl = sl or tf1h.get("support", 0)
                        tp = tp or tf1h.get("resistance", 0)
                        print("Paper debug: using S/R fallback sl=" + str(sl) + " tp=" + str(tp))
                    if sl and tp and sl > 0 and tp > 0 and price > 0:
                        try:
                            pconn = get_db()
                            paper_open_trade(pconn, symbol, signal["action"],
                                             price, sl, tp,
                                             signal.get("confidence", 0.7))
                            pconn.close()
                        except Exception as pe:
                            print("Paper open error: " + str(pe))
                    else:
                        print("Paper trade SKIPPED: invalid sl/tp/price")

            wait_until_next_hour()

        except Exception as loop_err:
            print("CYCLE ERROR: " + str(loop_err))
            import traceback
            traceback.print_exc()
            print("Waiting 60s before retry...")
            time.sleep(60)
