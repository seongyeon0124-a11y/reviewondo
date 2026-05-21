"""
자동매매 트레이딩 대시보드 (페이퍼 트레이딩).
실행: python trading_app.py  (포트 5001)
"""

import os
from flask import Flask, jsonify, redirect, render_template_string, request, url_for
from dotenv import load_dotenv

load_dotenv()

from trading.broker.paper import (
    get_cash, get_portfolio_value, get_positions_with_pnl,
    get_trade_history, init_db, reset_portfolio, execute_sell,
)
from trading.config import INITIAL_CAPITAL
from trading.scheduler import run_cycle
from trading.strategy.signals import generate_signal, scan_all

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "trading-dev-key")

init_db()

# ─────────────────────────────── HTML ────────────────────────────────

DASHBOARD_HTML = r"""
<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AutoTrader — 페이퍼 트레이딩</title>
<style>
  :root {
    --bg: #0d1117; --surface: #161b22; --border: #21262d;
    --text: #e6edf3; --muted: #8b949e;
    --green: #3fb950; --red: #f85149; --blue: #58a6ff;
    --yellow: #d29922;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: var(--bg); color: var(--text); font-family: 'SF Mono', 'Fira Code', ui-monospace, monospace; font-size: 13px; }

  .topbar { background: var(--surface); border-bottom: 1px solid var(--border); padding: 12px 20px; display: flex; align-items: center; gap: 16px; }
  .topbar h1 { font-size: 15px; font-weight: 700; color: var(--blue); }
  .topbar a { color: var(--muted); text-decoration: none; font-size: 12px; }
  .topbar a:hover { color: var(--text); }
  .badge { padding: 3px 10px; border-radius: 20px; font-size: 11px; font-weight: 700; }
  .badge-paper { background: #1c2a38; color: var(--blue); }

  .main { max-width: 1200px; margin: 0 auto; padding: 20px; }

  /* 상단 지표 카드 */
  .kpi-row { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 20px; }
  .kpi { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 16px; }
  .kpi .label { font-size: 11px; color: var(--muted); margin-bottom: 6px; text-transform: uppercase; letter-spacing: .5px; }
  .kpi .value { font-size: 26px; font-weight: 800; }
  .kpi .sub { font-size: 11px; color: var(--muted); margin-top: 4px; }
  .pos { color: var(--green); } .neg { color: var(--red); } .neu { color: var(--blue); }

  /* 버튼 */
  .btn { display: inline-flex; align-items: center; gap: 6px; padding: 8px 16px; border-radius: 6px; font-size: 12px; font-weight: 600; border: none; cursor: pointer; text-decoration: none; }
  .btn-primary { background: var(--blue); color: #000; }
  .btn-primary:hover { opacity: .85; }
  .btn-danger { background: var(--red); color: #fff; }
  .btn-danger:hover { opacity: .85; }
  .btn-ghost { background: var(--surface); color: var(--text); border: 1px solid var(--border); }
  .btn-ghost:hover { border-color: var(--blue); }
  .btn-sm { padding: 4px 10px; font-size: 11px; }

  .action-bar { display: flex; gap: 10px; margin-bottom: 20px; align-items: center; }

  /* 섹션 */
  .section { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; margin-bottom: 20px; }
  .section-header { padding: 12px 16px; border-bottom: 1px solid var(--border); display: flex; justify-content: space-between; align-items: center; }
  .section-title { font-size: 13px; font-weight: 700; }

  /* 테이블 */
  table { width: 100%; border-collapse: collapse; }
  th { padding: 8px 12px; text-align: left; font-size: 11px; color: var(--muted); border-bottom: 1px solid var(--border); font-weight: 600; text-transform: uppercase; letter-spacing: .4px; }
  td { padding: 9px 12px; border-bottom: 1px solid var(--border); font-size: 12px; }
  tr:last-child td { border-bottom: none; }
  tr:hover td { background: rgba(255,255,255,.03); }
  .empty { text-align: center; padding: 30px; color: var(--muted); }

  /* 신호 게이지 */
  .score-bar { display: flex; align-items: center; gap: 8px; }
  .score-track { flex: 1; height: 4px; background: var(--border); border-radius: 2px; position: relative; max-width: 120px; }
  .score-fill { height: 100%; border-radius: 2px; }
  .score-num { font-size: 12px; font-weight: 700; min-width: 44px; text-align: right; }

  /* 액션 배지 */
  .act-buy  { background: rgba(63,185,80,.15); color: var(--green); padding: 2px 8px; border-radius: 4px; }
  .act-sell { background: rgba(248,81,73,.15); color: var(--red); padding: 2px 8px; border-radius: 4px; }
  .act-hold { background: rgba(139,148,158,.12); color: var(--muted); padding: 2px 8px; border-radius: 4px; }

  /* 스피너 */
  .spinner { display: none; width: 14px; height: 14px; border: 2px solid transparent; border-top-color: currentColor; border-radius: 50%; animation: spin .6s linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }

  /* 알림 */
  #toast { position: fixed; bottom: 20px; right: 20px; background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 12px 18px; font-size: 12px; display: none; z-index: 99; max-width: 320px; }

  .breakdown { font-size: 10px; color: var(--muted); }
  @media (max-width: 700px) { .kpi-row { grid-template-columns: repeat(2, 1fr); } }
</style>
</head>
<body>
<div class="topbar">
  <h1>AutoTrader</h1>
  <span class="badge badge-paper">PAPER</span>
  <a href="/">리뷰온도</a>
  <span style="margin-left:auto;color:var(--muted);font-size:11px">마지막 갱신: {{ now }}</span>
</div>

<div class="main">

  <!-- KPI 카드 -->
  <div class="kpi-row">
    <div class="kpi">
      <div class="label">포트폴리오 가치</div>
      <div class="value neu">{{ "%.2f"|format(portfolio_value) }}</div>
      <div class="sub">초기자본 {{ "%.2f"|format(initial_capital) }}</div>
    </div>
    <div class="kpi">
      <div class="label">총 손익 (PnL)</div>
      <div class="value {% if pnl >= 0 %}pos{% else %}neg{% endif %}">
        {% if pnl >= 0 %}+{% endif %}{{ "%.2f"|format(pnl) }}
      </div>
      <div class="sub {% if pnl_pct >= 0 %}pos{% else %}neg{% endif %}">
        {% if pnl_pct >= 0 %}+{% endif %}{{ "%.1f"|format(pnl_pct) }}%
      </div>
    </div>
    <div class="kpi">
      <div class="label">가용 현금</div>
      <div class="value">{{ "%.2f"|format(cash) }}</div>
      <div class="sub">{{ "%.0f"|format(cash / portfolio_value * 100) if portfolio_value > 0 else 0 }}% 현금 비중</div>
    </div>
    <div class="kpi">
      <div class="label">보유 종목 수</div>
      <div class="value">{{ positions|length }}</div>
      <div class="sub">총 거래 {{ trade_count }}건</div>
    </div>
  </div>

  <!-- 액션 버튼 -->
  <div class="action-bar">
    <button class="btn btn-primary" onclick="runCycle()">
      <span class="spinner" id="cycle-spin"></span>
      🔍 신호 스캔 + 자동 매매
    </button>
    <button class="btn btn-ghost" onclick="runScan()">
      📡 신호만 스캔
    </button>
    <button class="btn btn-danger btn-sm" onclick="confirmReset()" style="margin-left:auto">
      초기화
    </button>
  </div>

  <!-- 신호 스캐너 -->
  <div class="section" id="signal-section" style="display:none">
    <div class="section-header">
      <span class="section-title">📡 신호 스캐너</span>
    </div>
    <table>
      <thead>
        <tr><th>종목</th><th>시장</th><th>액션</th><th>점수</th><th>정치인</th><th>뉴스</th><th>기술적</th></tr>
      </thead>
      <tbody id="signal-tbody"></tbody>
    </table>
  </div>

  <!-- 보유 포지션 -->
  <div class="section">
    <div class="section-header">
      <span class="section-title">💼 보유 포지션</span>
    </div>
    {% if positions %}
    <table>
      <thead>
        <tr><th>종목</th><th>시장</th><th>수량</th><th>평균단가</th><th>현재가</th><th>평가손익</th><th>수익률</th><th></th></tr>
      </thead>
      <tbody>
        {% for p in positions %}
        <tr>
          <td><strong>{{ p.ticker }}</strong></td>
          <td>{{ p.market }}</td>
          <td>{{ "%.4f"|format(p.shares) }}</td>
          <td>{{ "%.4f"|format(p.avg_cost) }}</td>
          <td>{{ "%.4f"|format(p.current_price) }}</td>
          <td class="{% if p.pnl >= 0 %}pos{% else %}neg{% endif %}">
            {% if p.pnl >= 0 %}+{% endif %}{{ "%.4f"|format(p.pnl) }}
          </td>
          <td class="{% if p.pnl_pct >= 0 %}pos{% else %}neg{% endif %}">
            {% if p.pnl_pct >= 0 %}+{% endif %}{{ p.pnl_pct }}%
          </td>
          <td>
            <form method="post" action="/trading/sell" style="display:inline">
              <input type="hidden" name="ticker" value="{{ p.ticker }}">
              <input type="hidden" name="market" value="{{ p.market }}">
              <button type="submit" class="btn btn-danger btn-sm">수동 매도</button>
            </form>
          </td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
    {% else %}
    <div class="empty">보유 포지션 없음 — "신호 스캔 + 자동 매매"를 실행하세요</div>
    {% endif %}
  </div>

  <!-- 거래 내역 -->
  <div class="section">
    <div class="section-header">
      <span class="section-title">📋 거래 내역 (최근 50건)</span>
    </div>
    {% if trades %}
    <table>
      <thead>
        <tr><th>시각</th><th>종목</th><th>시장</th><th>액션</th><th>수량</th><th>가격</th><th>손익</th><th>사유</th></tr>
      </thead>
      <tbody>
        {% for t in trades %}
        <tr>
          <td style="color:var(--muted)">{{ t.timestamp[:16] }}</td>
          <td><strong>{{ t.ticker }}</strong></td>
          <td>{{ t.market }}</td>
          <td>
            <span class="{% if t.action == 'BUY' %}act-buy{% elif t.action == 'SELL' %}act-sell{% endif %}">
              {{ t.action }}
            </span>
          </td>
          <td>{{ "%.4f"|format(t.shares) }}</td>
          <td>{{ "%.4f"|format(t.price) }}</td>
          <td class="{% if t.pnl > 0 %}pos{% elif t.pnl < 0 %}neg{% endif %}">
            {% if t.pnl != 0 %}{% if t.pnl > 0 %}+{% endif %}{{ "%.4f"|format(t.pnl) }}{% endif %}
          </td>
          <td style="color:var(--muted);font-size:11px">{{ t.reason }}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
    {% else %}
    <div class="empty">거래 내역 없음</div>
    {% endif %}
  </div>

</div><!-- /main -->

<div id="toast"></div>

<script>
function showToast(msg, ok=true) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.style.display = 'block';
  t.style.borderColor = ok ? '#3fb950' : '#f85149';
  setTimeout(() => { t.style.display = 'none'; }, 4000);
}

async function runCycle() {
  const spin = document.getElementById('cycle-spin');
  spin.style.display = 'inline-block';
  try {
    const r = await fetch('/trading/run', {method:'POST'});
    const data = await r.json();
    const n = data.executed?.length || 0;
    showToast(`완료! 실행 ${n}건 (SL/TP ${data.sl_tp?.length||0}건)`);
    setTimeout(() => location.reload(), 1500);
  } catch(e) { showToast('오류: ' + e, false); }
  finally { spin.style.display = 'none'; }
}

async function runScan() {
  showToast('스캔 중...', true);
  try {
    const r = await fetch('/trading/scan');
    const signals = await r.json();
    renderSignals(signals);
    document.getElementById('signal-section').style.display = 'block';
  } catch(e) { showToast('오류: ' + e, false); }
}

function renderSignals(signals) {
  const tbody = document.getElementById('signal-tbody');
  tbody.innerHTML = '';
  signals.forEach(s => {
    const score = s.score;
    const pct = Math.abs(score) / 1.0 * 100;
    const color = score >= 0.35 ? '#3fb950' : score <= -0.35 ? '#f85149' : '#8b949e';
    const actCls = s.action === 'BUY' ? 'act-buy' : s.action === 'SELL' ? 'act-sell' : 'act-hold';
    tbody.innerHTML += `<tr>
      <td><strong>${s.ticker}</strong></td>
      <td>${s.market}</td>
      <td><span class="${actCls}">${s.action}</span></td>
      <td>
        <div class="score-bar">
          <div class="score-track">
            <div class="score-fill" style="width:${pct}%;background:${color}"></div>
          </div>
          <span class="score-num" style="color:${color}">${score >= 0 ? '+' : ''}${score.toFixed(3)}</span>
        </div>
      </td>
      <td class="breakdown">${s.breakdown.politician >= 0 ? '+' : ''}${s.breakdown.politician.toFixed(3)}</td>
      <td class="breakdown">${s.breakdown.news >= 0 ? '+' : ''}${s.breakdown.news.toFixed(3)}</td>
      <td class="breakdown">${s.breakdown.technical >= 0 ? '+' : ''}${s.breakdown.technical.toFixed(3)}</td>
    </tr>`;
  });
}

function confirmReset() {
  if (confirm('포트폴리오를 초기화하시겠습니까? 모든 거래 내역이 삭제됩니다.')) {
    fetch('/trading/reset', {method:'POST'}).then(() => location.reload());
  }
}
</script>
</body>
</html>
"""


# ─────────────────────────────── Routes ──────────────────────────────

@app.route("/trading")
def dashboard():
    from datetime import datetime
    portfolio_value = get_portfolio_value()
    cash = get_cash()
    positions = get_positions_with_pnl()
    trades = get_trade_history(50)
    pnl = portfolio_value - INITIAL_CAPITAL
    pnl_pct = (pnl / INITIAL_CAPITAL * 100) if INITIAL_CAPITAL > 0 else 0
    trade_count = len(get_trade_history(9999))

    return render_template_string(
        DASHBOARD_HTML,
        portfolio_value=portfolio_value,
        initial_capital=INITIAL_CAPITAL,
        cash=cash,
        positions=positions,
        trades=trades,
        pnl=pnl,
        pnl_pct=round(pnl_pct, 2),
        trade_count=trade_count,
        now=datetime.now().strftime("%Y-%m-%d %H:%M"),
    )


@app.route("/trading/run", methods=["POST"])
def api_run():
    result = run_cycle()
    return jsonify(result)


@app.route("/trading/scan")
def api_scan():
    signals = scan_all()
    return jsonify(signals)


@app.route("/trading/signal/<market>/<ticker>")
def api_signal(market, ticker):
    sig = generate_signal(ticker.upper(), market.upper())
    return jsonify(sig)


@app.route("/trading/sell", methods=["POST"])
def manual_sell():
    ticker = request.form.get("ticker", "").strip().upper()
    market = request.form.get("market", "US").strip().upper()
    execute_sell(ticker, market, reason="수동 매도")
    return redirect(url_for("dashboard"))


@app.route("/trading/reset", methods=["POST"])
def api_reset():
    reset_portfolio()
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(debug=True, port=5001)
