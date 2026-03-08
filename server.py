import os
import json
import urllib.request
import urllib.parse
from flask import Flask, request, jsonify
from dotenv import load_dotenv

load_dotenv(override=False)

app = Flask(__name__)

PORT = int(os.getenv("PORT", 4021))
PAY_TO = os.getenv("RECEIVING_WALLET", "")
PRICE = os.getenv("SIGNAL_PRICE", "0.50")
NETWORK = os.getenv("NETWORK_ID", "base-mainnet")
PUBLIC_URL = os.getenv("PUBLIC_URL", "http://localhost:" + str(PORT))
ASSET = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"

if not PAY_TO:
    print("ОШИБКА: RECEIVING_WALLET не задан")
    exit(1)

def verify_payment(payment_header):
    try:
        body = json.dumps({
            "payment": payment_header,
            "paymentRequirements": {
                "scheme": "exact",
                "network": NETWORK,
                "maxAmountRequired": str(int(float(PRICE) * 1000000)),
                "resource": PUBLIC_URL + "/signal",
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

@app.route("/")
def index():
    return jsonify({
        "name": "AI Trading Signal Service",
        "protocol": "x402",
        "price_per_signal": "$" + PRICE + " USDC",
        "network": NETWORK,
        "wallet": PAY_TO,
        "endpoints": {"paid": "GET /signal", "free": "GET /status"}
    })

@app.route("/status")
def status():
    try:
        with open("last_signal.json", "r", encoding="utf-8") as f:
            data = json.load(f)
        return jsonify({
            "status": "running",
            "symbol": data.get("symbol"),
            "price": data.get("price"),
            "action": data.get("action"),
            "updated": data.get("timestamp")
        })
    except Exception:
        return jsonify({"status": "pending", "message": "Агент ещё не запустился"})

@app.route("/signal")
def signal():
    payment_header = request.headers.get("X-Payment") or request.headers.get("Payment")

    if not payment_header:
        return jsonify({
            "x402Version": 1,
            "error": "Payment required",
            "accepts": [{
                "scheme": "exact",
                "network": NETWORK,
                "maxAmountRequired": str(int(float(PRICE) * 1000000)),
                "resource": PUBLIC_URL + "/signal",
                "description": "AI Trading Signal - RSI + MACD + Claude Analysis",
                "mimeType": "application/json",
                "payTo": PAY_TO,
                "maxTimeoutSeconds": 300,
                "asset": ASSET,
                "extra": {"name": "USDC", "version": "2"}
            }]
        }), 402

    if not verify_payment(payment_header):
        return jsonify({"error": "Payment invalid"}), 402

    try:
        with open("last_signal.json", "r", encoding="utf-8") as f:
            signal_data = json.load(f)
        return jsonify({"status": "success", "paid": "$" + PRICE + " USDC", "signal": signal_data})
    except Exception:
        return jsonify({"error": "Signal not ready"}), 503

if __name__ == "__main__":
    print("=" * 50)
    print("x402 Сервер запущен!")
    print("URL: " + PUBLIC_URL)
    print("Цена: $" + PRICE + " USDC")
    print("Кошелёк: " + PAY_TO)
    print("=" * 50)
    app.run(host="0.0.0.0", port=PORT)
