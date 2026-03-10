import os
import json
import urllib.request
import threading
import subprocess
import sys
from flask import Flask, request, jsonify, render_template_string
from dotenv import load_dotenv

load_dotenv(override=False)

def run_agent():
    subprocess.run([sys.executable, "agent.py"])

threading.Thread(target=run_agent, daemon=True).start()

app = Flask(__name__)

PORT = int(os.getenv("PORT", 4021))
PAY_TO = os.getenv("RECEIVING_WALLET", "")
PRICE = os.getenv("SIGNAL_PRICE", "0.10")
NETWORK = os.getenv("NETWORK_ID", "base-mainnet")
PUBLIC_URL = os.getenv("PUBLIC_URL", "http://localhost:" + str(PORT))
ASSET = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"

SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "AVAX/USDT", "LINK/USDT", "DOGE/USDT", "XRP/USDT"]
COINS = ["BTC", "ETH", "SOL", "AVAX", "LINK", "DOGE", "XRP"]

if not PAY_TO:
    print("ERROR: RECEIVING_WALLET not set")
    exit(1)


STATS_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AI Trading Signal Bot — Stats</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.0/chart.umd.min.js"></script>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: #0a0e1a; color: #e0e6f0; font-family: 'Segoe UI', sans-serif; }
  .header { background: linear-gradient(135deg, #0f1629 0%, #1a2744 100%);
    padding: 24px 32px; border-bottom: 1px solid #1e3a5f; }
  .header h1 { font-size: 24px; color: #4da6ff; }
  .header p { color: #8899aa; margin-top: 4px; font-size: 14px; }
  .container { max-width: 1200px; margin: 0 auto; padding: 24px 16px; }
  .cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-bottom: 28px; }
  .card { background: #0f1629; border: 1px solid #1e3a5f; border-radius: 12px; padding: 20px; }
  .card .label { font-size: 12px; color: #8899aa; text-transform: uppercase; letter-spacing: 1px; }
  .card .value { font-size: 28px; font-weight: bold; margin-top: 6px; }
  .card .value.green { color: #00cc88; }
  .card .value.red { color: #ff4466; }
  .card .value.blue { color: #4da6ff; }
  .card .value.yellow { color: #ffcc00; }
  .section { background: #0f1629; border: 1px solid #1e3a5f; border-radius: 12px; padding: 20px; margin-bottom: 24px; }
  .section h2 { font-size: 16px; color: #4da6ff; margin-bottom: 16px; border-bottom: 1px solid #1e3a5f; padding-bottom: 10px; }
  .signals-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 16px; }
  .signal-card { background: #0a0e1a; border: 1px solid #1e3a5f; border-radius: 10px; padding: 16px; }
  .signal-card .coin { font-size: 18px; font-weight: bold; color: #fff; }
  .signal-card .price { font-size: 22px; color: #4da6ff; margin: 6px 0; }
  .signal-card .action { display: inline-block; padding: 4px 14px; border-radius: 20px; font-weight: bold; font-size: 13px; }
  .action.BUY { background: #003322; color: #00cc88; border: 1px solid #00cc88; }
  .action.SELL { background: #330011; color: #ff4466; border: 1px solid #ff4466; }
  .action.HOLD { background: #1a2033; color: #ffcc00; border: 1px solid #ffcc00; }
  .signal-card .meta { font-size: 12px; color: #8899aa; margin-top: 8px; }
  .signal-card .reason { font-size: 12px; color: #aabbcc; margin-top: 8px; line-height: 1.5; }
  .signal-card .conf { font-size: 13px; color: #ccc; margin-top: 6px; }
  .conf-bar { background: #1e3a5f; border-radius: 4px; height: 6px; margin-top: 4px; }
  .conf-fill { height: 6px; border-radius: 4px; background: linear-gradient(90deg, #4da6ff, #00cc88); }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th { background: #0a0e1a; color: #8899aa; padding: 10px 12px; text-align: left;
    border-bottom: 1px solid #1e3a5f; font-weight: 500; }
  td { padding: 10px 12px; border-bottom: 1px solid #0f1a2e; color: #ccc; }
  tr:hover td { background: #0f1629; }
  .badge { display: inline-block; padding: 2px 10px; border-radius: 12px; font-size: 12px; font-weight: bold; }
  .badge.BUY { background: #003322; color: #00cc88; }
  .badge.SELL { background: #330011; color: #ff4466; }
  .badge.HOLD { background: #1a2033; color: #ffcc00; }
  .chart-wrap { position: relative; height: 260px; }
  .tf-row { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 8px; }
  .tf-badge { font-size: 11px; padding: 2px 8px; border-radius: 8px; background: #1e3a5f; color: #8899aa; }
  .tf-badge.UP, .tf-badge.STRONG_UP { background: #003322; color: #00cc88; }
  .tf-badge.DOWN, .tf-badge.STRONG_DOWN { background: #330011; color: #ff4466; }
  .news-item { padding: 8px 0; border-bottom: 1px solid #0f1a2e; font-size: 13px; color: #aabbcc; }
  .news-item:last-child { border-bottom: none; }
  .updated { font-size: 11px; color: #556677; margin-top: 4px; }
  .api-url { background: #0a0e1a; border: 1px solid #1e3a5f; border-radius: 8px; padding: 10px 14px;
    font-family: monospace; font-size: 13px; color: #4da6ff; margin: 6px 0; word-break: break-all; }
</style>
</head>
<body>
<div class="header">
  <h1>🤖 AI Trading Signal Bot</h1>
  <p>Multi-timeframe analysis: 1h + 4h + 1d · News sentiment · Claude AI · x402 payments on Base</p>
</div>
<div class="container">

  <!-- Summary cards -->
  <div class="cards" id="summary-cards">
    <div class="card"><div class="label">Total Pairs</div><div class="value blue" id="total-pairs">7</div></div>
    <div class="card"><div class="label">BUY Signals</div><div class="value green" id="buy-count">—</div></div>
    <div class="card"><div class="label">SELL Signals</div><div class="value red" id="sell-count">—</div></div>
    <div class="card"><div class="label">HOLD Signals</div><div class="value yellow" id="hold-count">—</div></div>
    <div class="card"><div class="label">Price per Signal</div><div class="value blue">$0.10 USDC</div></div>
  </div>

  <!-- Latest signals grid -->
  <div class="section">
    <h2>📊 Latest Signals</h2>
    <div class="signals-grid" id="signals-grid">
      <div style="color:#8899aa">Loading...</div>
    </div>
  </div>

  <!-- Chart -->
  <div class="section">
    <h2>📈 Signal Distribution</h2>
    <div class="chart-wrap">
      <canvas id="signalChart"></canvas>
    </div>
  </div>

  <!-- History table -->
  <div class="section">
    <h2>🕐 Signal History</h2>
    <table>
      <thead><tr><th>Pair</th><th>Action</th><th>Price</th><th>Confidence</th><th>1H Trend</th><th>4H Trend</th><th>1D Trend</th><th>Time</th></tr></thead>
      <tbody id="history-table"><tr><td colspan="8" style="color:#8899aa">Loading...</td></tr></tbody>
    </table>
  </div>

  <!-- API info -->
  <div class="section">
    <h2>🔗 API Endpoints</h2>
    <p style="color:#8899aa;font-size:13px;margin-bottom:12px">Free status endpoints — no payment required:</p>
    """ + "".join(['<div class="api-url">GET ' + PUBLIC_URL + '/status/' + c + '</div>' for c in ["BTC","ETH","SOL","AVAX","LINK","DOGE","XRP"]]) + """
    <p style="color:#8899aa;font-size:13px;margin:12px 0">Paid signal endpoints — $0.10 USDC via x402:</p>
    """ + "".join(['<div class="api-url">GET ' + PUBLIC_URL + '/signal/' + c + '</div>' for c in ["BTC","ETH","SOL","AVAX","LINK","DOGE","XRP"]]) + """
  </div>

</div>

<script>
const API = window.location.origin;
const COINS = ["BTC","ETH","SOL","AVAX","LINK","DOGE","XRP"];
let allSignals = [];
let chart = null;

async function loadSignals() {
  const results = await Promise.all(
    COINS.map(c => fetch(API + "/status/" + c).then(r => r.json()).catch(() => null))
  );
  allSignals = results.filter(Boolean);
  renderCards();
  renderSummary();
  renderChart();
  renderHistory();
}

function renderSummary() {
  document.getElementById("buy-count").textContent = allSignals.filter(s => s.action === "BUY").length;
  document.getElementById("sell-count").textContent = allSignals.filter(s => s.action === "SELL").length;
  document.getElementById("hold-count").textContent = allSignals.filter(s => s.action === "HOLD").length;
}

function renderCards() {
  const grid = document.getElementById("signals-grid");
  if (!allSignals.length) { grid.innerHTML = '<div style="color:#8899aa">No signals yet</div>'; return; }
  grid.innerHTML = allSignals.map(s => {
    const conf = Math.round((s.confidence || 0) * 100);
    const tf1 = s.tf_1h || {};
    const tf4 = s.tf_4h || {};
    const tf1d = s.tf_1d || {};
    const news = (s.news || []).slice(0, 2);
    return '<div class="signal-card">' +
      '<div class="coin">' + (s.symbol || s.coin || "?") + '</div>' +
      '<div class="price">$' + (s.price || 0).toLocaleString() + '</div>' +
      '<span class="action ' + s.action + '">' + s.action + '</span>' +
      '<div class="conf">Confidence: ' + conf + '%' +
        '<div class="conf-bar"><div class="conf-fill" style="width:' + conf + '%"></div></div>' +
      '</div>' +
      '<div class="tf-row">' +
        (tf1.trend ? '<span class="tf-badge ' + tf1.trend + '">1H: ' + tf1.trend + '</span>' : '') +
        (tf4.trend ? '<span class="tf-badge ' + tf4.trend + '">4H: ' + tf4.trend + '</span>' : '') +
        (tf1d.trend ? '<span class="tf-badge ' + tf1d.trend + '">1D: ' + tf1d.trend + '</span>' : '') +
      '</div>' +
      (news.length ? '<div class="news-item" style="margin-top:8px">📰 ' + news[0] + '</div>' : '') +
      '<div class="reason">' + (s.reason || "") + '</div>' +
      '<div class="updated">Updated: ' + (s.updated || s.timestamp || "—") + '</div>' +
    '</div>';
  }).join("");
}

function renderChart() {
  const buy = allSignals.filter(s => s.action === "BUY").length;
  const sell = allSignals.filter(s => s.action === "SELL").length;
  const hold = allSignals.filter(s => s.action === "HOLD").length;
  const ctx = document.getElementById("signalChart").getContext("2d");
  if (chart) chart.destroy();
  chart = new Chart(ctx, {
    type: "doughnut",
    data: {
      labels: ["BUY", "SELL", "HOLD"],
      datasets: [{
        data: [buy, sell, hold],
        backgroundColor: ["#00cc88", "#ff4466", "#ffcc00"],
        borderColor: "#0a0e1a", borderWidth: 3
      }]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: { position: "right", labels: { color: "#e0e6f0", font: { size: 14 } } }
      }
    }
  });
}

function renderHistory() {
  const tbody = document.getElementById("history-table");
  if (!allSignals.length) { tbody.innerHTML = '<tr><td colspan="8" style="color:#8899aa">No data yet</td></tr>'; return; }
  tbody.innerHTML = allSignals.map(s => {
    const tf1 = s.tf_1h || {};
    const tf4 = s.tf_4h || {};
    const tf1d = s.tf_1d || {};
    const conf = Math.round((s.confidence || 0) * 100);
    const ts = s.updated || s.timestamp || "—";
    return '<tr>' +
      '<td><b>' + (s.symbol || "?") + '</b></td>' +
      '<td><span class="badge ' + s.action + '">' + s.action + '</span></td>' +
      '<td>$' + (s.price || 0).toLocaleString() + '</td>' +
      '<td>' + conf + '%</td>' +
      '<td><span class="badge ' + (tf1.trend||"") + '">' + (tf1.trend || "—") + '</span></td>' +
      '<td><span class="badge ' + (tf4.trend||"") + '">' + (tf4.trend || "—") + '</span></td>' +
      '<td><span class="badge ' + (tf1d.trend||"") + '">' + (tf1d.trend || "—") + '</span></td>' +
      '<td>' + ts.substring(0, 16).replace("T", " ") + '</td>' +
    '</tr>';
  }).join("");
}

loadSignals();
setInterval(loadSignals, 60000);
</script>
</body>
</html>"""


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
        print("Verify error:", e)
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
            "description": "AI Trading Signal - " + symbol,
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
        print("DB error:", e)
    try:
        with open("signal_" + key + ".json", "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        pass
    return None


@app.route("/.well-known/agent.json")
def agent_card():
    endpoints = []
    for coin in COINS:
        endpoints.append({"path": "/signal/" + coin, "method": "GET",
            "description": coin + "/USDT trading signal", "price_usd": float(PRICE),
            "currency": "USDC", "network": "base-mainnet"})
    for coin in COINS:
        endpoints.append({"path": "/status/" + coin, "method": "GET",
            "description": "Free " + coin + " status", "price_usd": 0})
    return jsonify({
        "name": "AI Trading Signal Bot",
        "description": "BTC, ETH, SOL, AVAX, LINK, DOGE, XRP signals. Multi-timeframe 1h+4h+1d + news. Claude AI. Updated every hour.",
        "url": PUBLIC_URL,
        "version": "2.0.0",
        "capabilities": {"payments": ["x402"], "networks": ["base-mainnet"], "assets": ["USDC"]},
        "endpoints": endpoints,
        "contact": "darex20003@gmail.com",
        "x402_facilitator": "https://x402.org/facilitator"
    })


@app.route("/")
def index():
    return jsonify({
        "name": "AI Trading Signal Service",
        "version": "2.0.0",
        "protocol": "x402",
        "price_per_signal": "$" + PRICE + " USDC",
        "network": NETWORK,
        "wallet": PAY_TO,
        "pairs": SYMBOLS,
        "features": ["multi-timeframe 1h/4h/1d", "news analysis", "12+ indicators"],
        "stats": PUBLIC_URL + "/stats",
        "agent_card": PUBLIC_URL + "/.well-known/agent.json",
        "endpoints": {
            "free": ["GET /status/" + c for c in COINS],
            "paid": ["GET /signal/" + c for c in COINS]
        }
    })


@app.route("/stats")
def stats():
    return render_template_string(STATS_HTML)


@app.route("/status")
@app.route("/status/<coin>")
def status(coin="BTC"):
    symbol = coin.upper() + "/USDT"
    if symbol not in SYMBOLS:
        return jsonify({"error": "Unknown symbol. Use: " + ", ".join(COINS)}), 400
    data = read_signal(symbol)
    if data:
        return jsonify({
            "status": "running",
            "symbol": data.get("symbol"),
            "price": data.get("price"),
            "action": data.get("action"),
            "confidence": data.get("confidence"),
            "reason": data.get("reason"),
            "tf_1h": data.get("tf_1h"),
            "tf_4h": data.get("tf_4h"),
            "tf_1d": data.get("tf_1d"),
            "news": data.get("news", []),
            "updated": data.get("timestamp")
        })
    return jsonify({"status": "pending", "message": "Signal not ready yet"})


@app.route("/signal")
@app.route("/signal/<coin>")
def signal(coin="BTC"):
    symbol = coin.upper() + "/USDT"
    if symbol not in SYMBOLS:
        return jsonify({"error": "Unknown symbol. Use: " + ", ".join(COINS)}), 400
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
    print("x402 Server v2.0 started!")
    print("URL: " + PUBLIC_URL)
    print("Stats: " + PUBLIC_URL + "/stats")
    print("Price: $" + PRICE + " USDC")
    print("Wallet: " + PAY_TO)
    print("Pairs: " + ", ".join(COINS))
    print("=" * 50)
    app.run(host="0.0.0.0", port=PORT)
