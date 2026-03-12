import os
import json
import urllib.request
import threading
import subprocess
import sys
import psycopg2
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


def get_db():
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        return None
    return psycopg2.connect(db_url)


def get_accuracy_stats():
    try:
        conn = get_db()
        if not conn:
            return {}
        cur = conn.cursor()

        # Overall accuracy per timeframe
        stats = {}
        for period in ["1h", "4h", "24h", "7d", "30d"]:
            col = "result_" + period
            cur.execute("""
                SELECT
                    COUNT(*) FILTER (WHERE """ + col + """ = 'WIN') as wins,
                    COUNT(*) FILTER (WHERE """ + col + """ = 'LOSS') as losses,
                    COUNT(*) FILTER (WHERE """ + col + """ = 'NEUTRAL') as neutral,
                    COUNT(*) FILTER (WHERE """ + col + """ IS NOT NULL) as total
                FROM signal_results
            """)
            row = cur.fetchone()
            wins, losses, neutral, total = row
            if total and total > 0:
                accuracy = round(wins / total * 100, 1)
            else:
                accuracy = None
            stats[period] = {
                "wins": wins or 0,
                "losses": losses or 0,
                "neutral": neutral or 0,
                "total": total or 0,
                "accuracy": accuracy
            }

        # Per-coin accuracy (24h)
        cur.execute("""
            SELECT symbol,
                COUNT(*) FILTER (WHERE result_24h = 'WIN') as wins,
                COUNT(*) FILTER (WHERE result_24h = 'LOSS') as losses,
                COUNT(*) FILTER (WHERE result_24h IS NOT NULL) as total
            FROM signal_results
            GROUP BY symbol
            ORDER BY symbol
        """)
        coins = {}
        for row in cur.fetchall():
            sym, wins, losses, total = row
            coin = sym.replace("/USDT", "")
            if total and total > 0:
                acc = round((wins or 0) / total * 100, 1)
            else:
                acc = None
            coins[coin] = {"wins": wins or 0, "losses": losses or 0, "total": total or 0, "accuracy": acc}
        stats["by_coin"] = coins

        # Per-action accuracy (24h)
        cur.execute("""
            SELECT action,
                COUNT(*) FILTER (WHERE result_24h = 'WIN') as wins,
                COUNT(*) FILTER (WHERE result_24h = 'LOSS') as losses,
                COUNT(*) FILTER (WHERE result_24h IS NOT NULL) as total
            FROM signal_results
            GROUP BY action
        """)
        actions = {}
        for row in cur.fetchall():
            act, wins, losses, total = row
            if total and total > 0:
                acc = round((wins or 0) / total * 100, 1)
            else:
                acc = None
            actions[act] = {"wins": wins or 0, "losses": losses or 0, "total": total or 0, "accuracy": acc}
        stats["by_action"] = actions

        # Recent results history (last 50)
        cur.execute("""
            SELECT r.symbol, r.action, r.price_at_signal,
                   r.result_1h, r.result_4h, r.result_24h,
                   r.price_1h, r.price_24h,
                   r.created_at
            FROM signal_results r
            WHERE r.result_1h IS NOT NULL OR r.result_24h IS NOT NULL
            ORDER BY r.created_at DESC
            LIMIT 50
        """)
        history = []
        for row in cur.fetchall():
            history.append({
                "symbol": row[0],
                "action": row[1],
                "price_at_signal": row[2],
                "result_1h": row[3],
                "result_4h": row[4],
                "result_24h": row[5],
                "price_1h": row[6],
                "price_24h": row[7],
                "time": row[8].isoformat() if row[8] else None
            })
        stats["history"] = history

        cur.close()
        conn.close()
        return stats
    except Exception as e:
        print("get_accuracy_stats error: " + str(e))
        return {}


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
  .card .value.purple { color: #cc88ff; }
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
  .badge.WIN { background: #003322; color: #00cc88; }
  .badge.LOSS { background: #330011; color: #ff4466; }
  .badge.NEUTRAL { background: #1a2033; color: #8899aa; }
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
  .accuracy-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 12px; margin-bottom: 20px; }
  .acc-card { background: #0a0e1a; border: 1px solid #1e3a5f; border-radius: 10px; padding: 14px; text-align: center; }
  .acc-card .period { font-size: 11px; color: #8899aa; text-transform: uppercase; letter-spacing: 1px; }
  .acc-card .acc-val { font-size: 26px; font-weight: bold; margin: 6px 0; }
  .acc-card .acc-sub { font-size: 11px; color: #556677; }
  .acc-bar-wrap { background: #1e3a5f; border-radius: 6px; height: 8px; margin: 6px 0; }
  .acc-bar { height: 8px; border-radius: 6px; }
  .coin-acc-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 10px; }
  .coin-acc { background: #0a0e1a; border: 1px solid #1e3a5f; border-radius: 8px; padding: 12px; text-align: center; }
  .coin-acc .cname { font-size: 14px; font-weight: bold; color: #fff; }
  .coin-acc .cacc { font-size: 20px; font-weight: bold; margin: 4px 0; }
  .coin-acc .csub { font-size: 11px; color: #556677; }
  .no-data { color: #445566; font-size: 13px; font-style: italic; text-align: center; padding: 20px; }
  .tabs { display: flex; gap: 8px; margin-bottom: 16px; }
  .tab { padding: 6px 16px; border-radius: 20px; border: 1px solid #1e3a5f; background: #0a0e1a;
    color: #8899aa; cursor: pointer; font-size: 13px; transition: all 0.2s; }
  .tab.active { background: #1e3a5f; color: #4da6ff; border-color: #4da6ff; }
</style>
</head>
<body>
<div class="header">
  <h1>🤖 AI Trading Signal Bot</h1>
  <p>Multi-timeframe analysis: 1h + 4h + 1d · News sentiment · Claude AI · x402 payments on Base</p>
</div>
<div class="container">

  <!-- Summary cards -->
  <div class="cards">
    <div class="card"><div class="label">Total Pairs</div><div class="value blue">7</div></div>
    <div class="card"><div class="label">BUY Signals</div><div class="value green" id="buy-count">—</div></div>
    <div class="card"><div class="label">SELL Signals</div><div class="value red" id="sell-count">—</div></div>
    <div class="card"><div class="label">HOLD Signals</div><div class="value yellow" id="hold-count">—</div></div>
    <div class="card"><div class="label">Price per Signal</div><div class="value blue">$0.10 USDC</div></div>
    <div class="card"><div class="label">Accuracy 24h</div><div class="value purple" id="acc-24h">—</div></div>
  </div>

  <!-- ACCURACY SECTION -->
  <div class="section">
    <h2>🎯 Forecast Accuracy</h2>
    <div id="accuracy-content">
      <div class="no-data">⏳ Accumulating data... Results appear after signals age 1h, 4h, 24h, 7d, 30d</div>
    </div>
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
    <div class="tabs">
      <div class="tab active" onclick="switchTab('signals')">All Signals</div>
      <div class="tab" onclick="switchTab('results')">Forecast Results</div>
    </div>
    <div id="tab-signals">
      <table>
        <thead><tr><th>Pair</th><th>Action</th><th>Price</th><th>Confidence</th><th>1H Trend</th><th>4H Trend</th><th>1D Trend</th><th>Time</th></tr></thead>
        <tbody id="history-table"><tr><td colspan="8" style="color:#8899aa">Loading...</td></tr></tbody>
      </table>
    </div>
    <div id="tab-results" style="display:none">
      <table>
        <thead><tr><th>Pair</th><th>Action</th><th>Entry Price</th><th>Result 1h</th><th>Result 4h</th><th>Result 24h</th><th>Time</th></tr></thead>
        <tbody id="results-table"><tr><td colspan="7" style="color:#8899aa">Loading...</td></tr></tbody>
      </table>
    </div>
  </div>

  <!-- API info -->
  <div class="section">
    <h2>🔗 API Endpoints</h2>
    <p style="color:#8899aa;font-size:13px;margin-bottom:12px">Free status endpoints — no payment required:</p>
    """ + "".join(['<div class="api-url">GET ' + PUBLIC_URL + '/status/' + c + '</div>' for c in ["BTC","ETH","SOL","AVAX","LINK","DOGE","XRP"]]) + """
    <p style="color:#8899aa;font-size:13px;margin:12px 0">Paid signal endpoints — $0.10 USDC via x402:</p>
    """ + "".join(['<div class="api-url">GET ' + PUBLIC_URL + '/signal/' + c + '</div>' for c in ["BTC","ETH","SOL","AVAX","LINK","DOGE","XRP"]]) + """
    <p style="color:#8899aa;font-size:13px;margin:12px 0">Accuracy stats — free:</p>
    <div class="api-url">GET """ + PUBLIC_URL + """/accuracy</div>
  </div>

</div>

<script>
const API = window.location.origin;
const COINS = ["BTC","ETH","SOL","AVAX","LINK","DOGE","XRP"];
let allSignals = [];
let chart = null;
let accuracyData = null;

function switchTab(tab) {
  document.getElementById("tab-signals").style.display = tab === "signals" ? "block" : "none";
  document.getElementById("tab-results").style.display = tab === "results" ? "block" : "none";
  document.querySelectorAll(".tab").forEach((t, i) => {
    t.classList.toggle("active", (i === 0 && tab === "signals") || (i === 1 && tab === "results"));
  });
}

async function loadAccuracy() {
  try {
    const res = await fetch(API + "/accuracy");
    if (!res.ok) return;
    accuracyData = await res.json();
    renderAccuracy();
    renderResultsTable();
  } catch(e) { console.error("Accuracy load error:", e); }
}

function colorForAcc(acc) {
  if (acc === null || acc === undefined) return "#556677";
  if (acc >= 65) return "#00cc88";
  if (acc >= 50) return "#ffcc00";
  return "#ff4466";
}

function renderAccuracy() {
  const el = document.getElementById("accuracy-content");
  if (!accuracyData) return;

  const periods = ["1h", "4h", "24h", "7d", "30d"];
  const labels = {"1h": "1 Hour", "4h": "4 Hours", "24h": "24 Hours", "7d": "7 Days", "30d": "30 Days"};

  let hasAnyData = false;
  for (const p of periods) {
    const d = accuracyData[p];
    if (d && d.total > 0) { hasAnyData = true; break; }
  }

  if (!hasAnyData) {
    el.innerHTML = '<div class="no-data">⏳ Accumulating data... Results appear after signals age 1h, 4h, 24h, 7d, 30d</div>';
    return;
  }

  // Update 24h summary card
  const d24 = accuracyData["24h"];
  if (d24 && d24.accuracy !== null) {
    document.getElementById("acc-24h").textContent = d24.accuracy + "%";
    document.getElementById("acc-24h").style.color = colorForAcc(d24.accuracy);
  }

  // Accuracy per period
  let html = '<div class="accuracy-grid">';
  for (const p of periods) {
    const d = accuracyData[p];
    const acc = d && d.total > 0 ? d.accuracy : null;
    const col = colorForAcc(acc);
    const barW = acc !== null ? acc : 0;
    html += '<div class="acc-card">' +
      '<div class="period">' + labels[p] + '</div>' +
      '<div class="acc-val" style="color:' + col + '">' + (acc !== null ? acc + "%" : "—") + '</div>' +
      '<div class="acc-bar-wrap"><div class="acc-bar" style="width:' + barW + '%;background:' + col + '"></div></div>' +
      '<div class="acc-sub">' + (d ? d.wins + "W / " + d.losses + "L / " + d.neutral + "N (" + d.total + " signals)" : "No data") + '</div>' +
    '</div>';
  }
  html += '</div>';

  // By coin
  const bc = accuracyData.by_coin;
  if (bc && Object.keys(bc).length > 0) {
    html += '<h3 style="color:#8899aa;font-size:13px;margin:16px 0 10px;text-transform:uppercase;letter-spacing:1px">Accuracy by Coin (24h)</h3>';
    html += '<div class="coin-acc-grid">';
    for (const [coin, d] of Object.entries(bc)) {
      const col = colorForAcc(d.accuracy);
      html += '<div class="coin-acc">' +
        '<div class="cname">' + coin + '</div>' +
        '<div class="cacc" style="color:' + col + '">' + (d.accuracy !== null ? d.accuracy + "%" : "—") + '</div>' +
        '<div class="csub">' + d.wins + "W / " + d.losses + "L (" + d.total + ")</div>" +
      '</div>';
    }
    html += '</div>';
  }

  // By action
  const ba = accuracyData.by_action;
  if (ba && Object.keys(ba).length > 0) {
    html += '<h3 style="color:#8899aa;font-size:13px;margin:16px 0 10px;text-transform:uppercase;letter-spacing:1px">Accuracy by Signal Type (24h)</h3>';
    html += '<div class="accuracy-grid">';
    for (const [action, d] of Object.entries(ba)) {
      const col = colorForAcc(d.accuracy);
      html += '<div class="acc-card">' +
        '<span class="badge ' + action + '">' + action + '</span>' +
        '<div class="acc-val" style="color:' + col + '">' + (d.accuracy !== null ? d.accuracy + "%" : "—") + '</div>' +
        '<div class="acc-sub">' + d.wins + "W / " + d.losses + "L (" + d.total + ")</div>" +
      '</div>';
    }
    html += '</div>';
  }

  el.innerHTML = html;
}

function renderResultsTable() {
  const tbody = document.getElementById("results-table");
  if (!accuracyData || !accuracyData.history || !accuracyData.history.length) {
    tbody.innerHTML = '<tr><td colspan="7" class="no-data">No results yet — data appears after signals age 1h+</td></tr>';
    return;
  }
  tbody.innerHTML = accuracyData.history.map(r => {
    const ts = r.time ? r.time.substring(0, 16).replace("T", " ") : "—";
    const price = r.price_at_signal ? "$" + Number(r.price_at_signal).toLocaleString() : "—";
    const r1 = r.result_1h ? '<span class="badge ' + r.result_1h + '">' + r.result_1h + '</span>' : '<span style="color:#445566">—</span>';
    const r4 = r.result_4h ? '<span class="badge ' + r.result_4h + '">' + r.result_4h + '</span>' : '<span style="color:#445566">—</span>';
    const r24 = r.result_24h ? '<span class="badge ' + r.result_24h + '">' + r.result_24h + '</span>' : '<span style="color:#445566">—</span>';
    return '<tr>' +
      '<td>' + r.symbol + '</td>' +
      '<td><span class="badge ' + r.action + '">' + r.action + '</span></td>' +
      '<td>' + price + '</td>' +
      '<td>' + r1 + '</td>' +
      '<td>' + r4 + '</td>' +
      '<td>' + r24 + '</td>' +
      '<td>' + ts + '</td>' +
    '</tr>';
  }).join("");
}

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
      '<div class="price">$' + Number(s.price || 0).toLocaleString() + '</div>' +
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
  const counts = {BUY: 0, SELL: 0, HOLD: 0};
  allSignals.forEach(s => { if (counts[s.action] !== undefined) counts[s.action]++; });
  const ctx = document.getElementById("signalChart").getContext("2d");
  if (chart) chart.destroy();
  chart = new Chart(ctx, {
    type: "bar",
    data: {
      labels: COINS,
      datasets: [{
        label: "Signal",
        data: COINS.map(c => {
          const s = allSignals.find(x => (x.symbol||"").startsWith(c));
          if (!s) return 0;
          return s.action === "BUY" ? 1 : s.action === "SELL" ? -1 : 0;
        }),
        backgroundColor: COINS.map(c => {
          const s = allSignals.find(x => (x.symbol||"").startsWith(c));
          if (!s) return "#1e3a5f";
          return s.action === "BUY" ? "#00cc88" : s.action === "SELL" ? "#ff4466" : "#ffcc00";
        }),
        borderRadius: 6,
      }]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        y: { ticks: { color: "#8899aa", callback: v => v===1?"BUY":v===-1?"SELL":"HOLD" },
          grid: { color: "#1e3a5f" }, min: -1.5, max: 1.5 },
        x: { ticks: { color: "#8899aa" }, grid: { display: false } }
      }
    }
  });
}

function renderHistory() {
  const tbody = document.getElementById("history-table");
  if (!allSignals.length) { tbody.innerHTML = '<tr><td colspan="8" style="color:#8899aa">No signals</td></tr>'; return; }
  tbody.innerHTML = allSignals.map(s => {
    const conf = Math.round((s.confidence || 0) * 100);
    const tf1 = s.tf_1h || {};
    const tf4 = s.tf_4h || {};
    const tf1d = s.tf_1d || {};
    const ts = s.updated || s.timestamp || "";
    return '<tr>' +
      '<td>' + (s.symbol || "?") + '</td>' +
      '<td><span class="badge ' + s.action + '">' + s.action + '</span></td>' +
      '<td>$' + Number(s.price || 0).toLocaleString() + '</td>' +
      '<td>' + conf + '%</td>' +
      '<td><span class="badge ' + (tf1.trend||"") + '">' + (tf1.trend || "—") + '</span></td>' +
      '<td><span class="badge ' + (tf4.trend||"") + '">' + (tf4.trend || "—") + '</span></td>' +
      '<td><span class="badge ' + (tf1d.trend||"") + '">' + (tf1d.trend || "—") + '</span></td>' +
      '<td>' + ts.substring(0, 16).replace("T", " ") + '</td>' +
    '</tr>';
  }).join("");
}

loadSignals();
loadAccuracy();
setInterval(loadSignals, 60000);
setInterval(loadAccuracy, 300000);
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
        "features": ["multi-timeframe 1h/4h/1d", "news analysis", "12+ indicators", "accuracy tracking"],
        "stats": PUBLIC_URL + "/stats",
        "agent_card": PUBLIC_URL + "/.well-known/agent.json",
        "endpoints": {
            "free": ["GET /status/" + c for c in COINS],
            "paid": ["GET /signal/" + c for c in COINS],
            "accuracy": "GET /accuracy"
        }
    })


@app.route("/stats")
def stats():
    return render_template_string(STATS_HTML)


@app.route("/accuracy")
def accuracy():
    return jsonify(get_accuracy_stats())


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
    print("Accuracy: " + PUBLIC_URL + "/accuracy")
    print("Price: $" + PRICE + " USDC")
    print("Wallet: " + PAY_TO)
    print("Pairs: " + ", ".join(COINS))
    print("=" * 50)
    app.run(host="0.0.0.0", port=PORT)
