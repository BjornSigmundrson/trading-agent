import os
import json
import urllib.request
import threading
import subprocess
import sys
from flask import Flask, request, jsonify
from dotenv import load_dotenv

load_dotenv(override=False)

import threading
import subprocess
import sys

def run_agent():
    subprocess.run([sys.executable, "agent.py"])

threading.Thread(target=run_agent, daemon=True).start()

app = Flask(__name__)

PORT = int(os.getenv("PORT", 4021))
PAY_TO = os.getenv("RECEIVING_WALLET", "")
PRICE = os.getenv("SIGNAL_PRICE", "0.50")
NETWORK = os.getenv("NETWORK_ID", "base-mainnet")
PUBLIC_URL = os.getenv("PUBLIC_URL", "http://localhost:" + str(PORT))
ASSET = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"

SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT"]

if not PAY_TO:
    print("ОШИБКА: RECEIVING_WALLET не задан")
    exit(1)

def verify_payment(payment_header, resource):
    try:
        body = json.dumps({
            "payment": payment_header,
            "paymentRequirements": {
                "scheme": "exact",
                "network": NETWORK,
                "maxAmountRequired": str(int(float(PRICE) * 1000000)),
                "resource": resource,
                "description": "AI Trading Signal",
                "mimeType": "application/json",
                "payTo": PAY_TO,
                "maxTimeoutSeconds": 300,
                "asset": ASSET,
                "outputSchema": None,
                "extra": {"name": "USDC", "version": "2"}
            }
        }).encode("utf-8")
        req = urllib.request.Request(
            "https://x402.org/facilitator/verify",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read().decode())
            return result.get("isValid") == True
    except Exception as e:
        print("Ошибка верификации:", e)
        return False

def payment_required_response(resource, symbol):
    return jsonify({
        "x402Version": 1,
        "error": "Payment required",
        "accepts": [{
            "scheme": "exact",
            "network": NETWORK,
            "maxAmountRequired": str(int(float(PRICE) * 1000000)),
            "resource": resource,
            "description": "AI Trading Signal - " + symbol + " RSI + MACD + Claude Analysis",
            "mimeType": "application/json",
            "payTo": PAY_TO,
            "maxTimeoutSeconds": 300,
            "asset": ASSET,
            "extra": {"name": "USDC", "version": "2"}
        }]
    }), 402

def read_signal(symbol):
    key = symbol.replace("/", "_")
    try:
        import psycopg2
        db_url = os.getenv("DATABASE_URL")
        if db_url:
            conn = psycopg2.connect(db_url)
            cur = conn.cursor()
            cur.execute("SELECT data FROM signals WHERE symbol=%s ORDER BY created_at DESC LIMIT 1", [symbol])
            row = cur.fetchone()
            cur.close()
            conn.close()
            if row:
                return row[0]
    except Exception as e:
        print("БД ошибка:", e)
    try:
        with open("signal_" + key + ".json", "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        pass
    if symbol == "BTC/USDT":
        try:
            with open("last_signal.json", "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return None

@app.route("/")
def index():
    return jsonify({
        "name": "AI Trading Signal Service",
        "protocol": "x402",
        "price_per_signal": "$" + PRICE + " USDC",
        "network": NETWORK,
        "wallet": PAY_TO,
        "pairs": SYMBOLS,
        "endpoints": {
            "free": ["GET /status", "GET /status/BTC", "GET /status/ETH", "GET /status/SOL"],
            "paid": ["GET /signal", "GET /signal/BTC", "GET /signal/ETH", "GET /signal/SOL"]
        }
    })

@app.route("/status")
@app.route("/status/<coin>")
def status(coin="BTC"):
    symbol = coin.upper() + "/USDT"
    if symbol not in SYMBOLS:
        return jsonify({"error": "Unknown symbol. Use BTC, ETH or SOL"}), 400
    data = read_signal(symbol)
    if data:
        return jsonify({
            "status": "running",
            "symbol": data.get("symbol"),
            "price": data.get("price"),
            "action": data.get("action"),
            "updated": data.get("timestamp")
        })
    return jsonify({"status": "pending", "message": "Агент ещё не запустился"})

@app.route("/signal")
@app.route("/signal/<coin>")
def signal(coin="BTC"):
    symbol = coin.upper() + "/USDT"
    if symbol not in SYMBOLS:
        return jsonify({"error": "Unknown symbol. Use BTC, ETH or SOL"}), 400
    resource = PUBLIC_URL + "/signal/" + coin.upper()
    payment_header = request.headers.get("X-Payment") or request.headers.get("Payment")
    if not payment_header:
        return payment_required_response(resource, symbol)
    if not verify_payment(payment_header, resource):
        return jsonify({"error": "Payment invalid"}), 402
    data = read_signal(symbol)
    if data:
        return jsonify({"status": "success", "paid": "$" + PRICE + " USDC", "signal": data})
    return jsonify({"error": "Signal not ready"}), 503

if __name__ == "__main__":
    print("=" * 50)
    print("x402 Сервер запущен!")
    print("URL: " + PUBLIC_URL)
    print("Цена: $" + PRICE + " USDC")
    print("Кошелёк: " + PAY_TO)
    print("Пары: " + ", ".join(SYMBOLS))
    print("=" * 50)
    app.run(host="0.0.0.0", port=PORT)
