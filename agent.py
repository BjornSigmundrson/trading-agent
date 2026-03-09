import os, json, time
import pandas as pd
import ta
import ccxt
from dotenv import load_dotenv
from langchain_anthropic import ChatAnthropic

load_dotenv(override=False)

CYCLE_SEC = 3600

api_key = os.getenv("ANTHROPIC_API_KEY")
if not api_key:
    print("ANTHROPIC_API_KEY не найден в .env")
    exit(1)
print("Anthropic API ключ найден")

SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT"]

def make_exchange():
    for ex in [ccxt.coinbase(), ccxt.kraken(), ccxt.binance()]:
        try:
            ex.fetch_ticker("BTC/USDT")
            print("Биржа: " + ex.id)
            return ex
        except Exception:
            continue
    raise Exception("Все биржи недоступны")

exchange = make_exchange()
llm = ChatAnthropic(model="claude-sonnet-4-6", temperature=0)

def get_market_data(symbol):
    ohlcv = exchange.fetch_ohlcv(symbol, "1h", limit=100)
    df = pd.DataFrame(ohlcv, columns=["ts","open","high","low","close","vol"])
    rsi = float(ta.momentum.RSIIndicator(df["close"], window=14).rsi().iloc[-1])
    macd_obj = ta.trend.MACD(df["close"])
    macd_bullish = macd_obj.macd().iloc[-1] > macd_obj.macd_signal().iloc[-1]
    ema20 = df["close"].ewm(span=20).mean().iloc[-1]
    ema50 = df["close"].ewm(span=50).mean().iloc[-1]
    if ema20 > ema50 * 1.003:
        trend = "UP"
    elif ema20 < ema50 * 0.997:
        trend = "DOWN"
    else:
        trend = "FLAT"
    return {
        "symbol": symbol,
        "price": round(df["close"].iloc[-1], 2),
        "rsi": round(rsi, 1),
        "macd": "BULLISH" if macd_bullish else "BEARISH",
        "trend": trend,
    }

def run_cycle(symbol):
    try:
        market = get_market_data(symbol)
    except Exception as e:
        return {"symbol": symbol, "action": "HOLD", "confidence": 0, "reason": "Ошибка: " + str(e)}

    prompt = (
        "Ты профессиональный крипто-трейдер. Проанализируй данные и дай сигнал.\n\n"
        "ДАННЫЕ (" + market["symbol"] + ", таймфрейм 1h):\n"
        "Цена: $" + str(market["price"]) + "\n"
        "RSI(14): " + str(market["rsi"]) + "\n"
        "MACD: " + market["macd"] + "\n"
        "Тренд EMA20/50: " + market["trend"] + "\n\n"
        "Ответь ТОЛЬКО валидным JSON без markdown:\n"
        '{"action":"HOLD","confidence":0.6,"stop_loss":0,"take_profit":0,"reason":"объяснение на русском"}\n\n'
        "action: только BUY, SELL или HOLD\n"
        "confidence: от 0.0 до 1.0\n"
    )

    response = llm.invoke([{"role": "user", "content": prompt}])
    try:
        decision = json.loads(response.content.strip())
    except Exception:
        decision = {"action": "HOLD", "confidence": 0.0,
                    "stop_loss": 0, "take_profit": 0, "reason": "Ошибка парсинга"}

    result = {}
    result.update(market)
    result.update(decision)
    import datetime
    result["timestamp"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    return result

def save_signal(symbol, signal):
    key = symbol.replace("/", "_")
    with open("signal_" + key + ".json", "w", encoding="utf-8") as f:
        json.dump(signal, f, ensure_ascii=False, indent=2)
    # также сохраняем BTC как last_signal.json для совместимости
    if symbol == "BTC/USDT":
        with open("last_signal.json", "w", encoding="utf-8") as f:
            json.dump(signal, f, ensure_ascii=False, indent=2)
    print("Сохранено в файл: signal_" + key + ".json")
    try:
        import psycopg2
        db_url = os.getenv("DATABASE_URL")
        if db_url:
            conn = psycopg2.connect(db_url)
            cur = conn.cursor()
            cur.execute("""
    CREATE TABLE IF NOT EXISTS signals (
        id SERIAL PRIMARY KEY,
        data JSONB,
        created_at TIMESTAMP DEFAULT NOW()
    )
""")
cur.execute("""
    ALTER TABLE signals ADD COLUMN IF NOT EXISTS symbol VARCHAR(20)
""")
            cur.execute("INSERT INTO signals (symbol, data) VALUES (%s, %s)",
                       [symbol, json.dumps(signal)])
            conn.commit()
            cur.close()
            conn.close()
            print("Сохранено в БД: " + symbol)
    except Exception as e:
        print("БД ошибка:", e)

if __name__ == "__main__":
    print("=" * 50)
    print("Агент запущен")
    print("Пары: " + ", ".join(SYMBOLS))
    print("Цикл: каждые " + str(CYCLE_SEC // 60) + " минут")
    print("=" * 50)

    cycle = 0
    while True:
        cycle += 1
        print("\n=== Цикл #" + str(cycle) + " ===")
        for symbol in SYMBOLS:
            print("\n--- " + symbol + " ---")
            signal = run_cycle(symbol)
            print("Цена: $" + str(signal.get("price", 0)))
            print("RSI=" + str(signal.get("rsi")) + " | MACD=" + str(signal.get("macd")) + " | Тренд=" + str(signal.get("trend")))
            print("Сигнал: " + str(signal.get("action")) + " | Уверенность: " + str(int(signal.get("confidence", 0) * 100)) + "%")
            print(str(signal.get("reason", "")))
            save_signal(symbol, signal)
        print("\nСледующий цикл через " + str(CYCLE_SEC // 60) + " минут...")
        time.sleep(CYCLE_SEC)
