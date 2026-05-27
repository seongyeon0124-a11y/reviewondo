"""
자동매매 트레이딩 대시보드 (페이퍼 트레이딩).
실행: python trading_app.py  (포트 5001)
"""

import os
from flask import Flask, jsonify, redirect, render_template_string, request, url_for
from dotenv import load_dotenv

load_dotenv()

from trading.backtest import run_backtest
from trading.broker.paper import (
    execute_sell, get_cash, get_portfolio_value, get_positions_with_pnl,
    get_trade_history, init_db, reset_portfolio,
)
from trading.config import INITIAL_CAPITAL, WATCHLIST_KR, WATCHLIST_US
from trading.data.politician import get_all_recent_trades
from trading.data.prices import get_data_source_status
from trading.scheduler import run_cycle, run_pol_cycle
from trading.strategy.pol_strategy import get_pol_buy_candidates
from trading.strategy.signals import generate_signal, scan_all

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "trading-dev-key")

init_db()

# ── 자동 스케줄러 ─────────────────────────────────────────────
try:
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger

    _scheduler = BackgroundScheduler(timezone="Asia/Seoul", daemon=True)

    # 단타: 매주 금요일 오후 3시 (미국 장 마감 전)
    _scheduler.add_job(
        lambda: run_cycle("SHORT"),
        CronTrigger(day_of_week="fri", hour=15, minute=0),
        id="short_cycle", replace_existing=True,
    )
    # 장기: 매월 첫 번째 월요일 오전 9시
    _scheduler.add_job(
        lambda: run_cycle("LONG"),
        CronTrigger(day_of_week="mon", hour=9, minute=0, week="1"),
        id="long_cycle", replace_existing=True,
    )
    # 정치인 카피: 매일 오전 8시 (공시 수시 확인)
    _scheduler.add_job(
        run_pol_cycle,
        CronTrigger(hour=8, minute=0),
        id="pol_cycle", replace_existing=True,
    )

    _scheduler.start()
except ImportError:
    _scheduler = None

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
    --bg:#0d1117; --surface:#161b22; --border:#21262d;
    --text:#e6edf3; --muted:#8b949e;
    --green:#3fb950; --red:#f85149; --blue:#58a6ff; --yellow:#d29922;
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

  /* 탭 */
  .tabs { display: flex; gap: 2px; margin-bottom: 20px; }
  .tab  { padding: 9px 22px; border-radius: 8px 8px 0 0; font-size: 13px; font-weight: 700;
          cursor: pointer; border: 1px solid var(--border); border-bottom: none;
          background: var(--bg); color: var(--muted); user-select: none; }
  .tab.active { background: var(--surface); color: var(--text); border-color: var(--border); }
  .tab-long.active  { color: var(--blue); }
  .tab-short.active { color: var(--yellow); }
  .tab-panel { display: none; }
  .tab-panel.active { display: block; }

  .breakdown { font-size: 10px; color: var(--muted); }
  .mode-badge { padding: 2px 8px; border-radius: 4px; font-size: 10px; font-weight: 700; }
  .mode-long  { background: rgba(88,166,255,.15); color: var(--blue); }
  .mode-short { background: rgba(210,153,34,.15);  color: var(--yellow); }
  @media (max-width: 700px) { .kpi-row { grid-template-columns: repeat(2, 1fr); } }
</style>
</head>
<body>
<div class="topbar">
  <h1>AutoTrader</h1>
  <span class="badge badge-paper">PAPER</span>
  <a href="/">리뷰온도</a>
  <a href="/trading/backtest" style="color:var(--yellow)">📊 백테스트</a>
  <span style="margin-left:auto;font-size:11px">
    {% for src, status in data_sources.items() %}
      <span title="{{ src }}" style="margin-left:8px">{{ status[:2] }}</span>
    {% endfor %}
    <span style="color:var(--muted);margin-left:8px">{{ now }}</span>
  </span>
</div>

<div class="main">

  <!-- 전체 요약 KPI -->
  <div class="kpi-row" style="grid-template-columns:repeat(4,1fr);margin-bottom:12px">
    <div class="kpi">
      <div class="label">전체 포트폴리오</div>
      <div class="value neu">{{ "%.0f"|format(total_value) }}</div>
      <div class="sub">초기 {{ "%.0f"|format(initial_capital) }}</div>
    </div>
    <div class="kpi">
      <div class="label">전체 손익</div>
      <div class="value {% if total_pnl >= 0 %}pos{% else %}neg{% endif %}">
        {% if total_pnl >= 0 %}+{% endif %}{{ "%.0f"|format(total_pnl) }}
      </div>
      <div class="sub {% if total_pnl_pct >= 0 %}pos{% else %}neg{% endif %}">
        {% if total_pnl_pct >= 0 %}+{% endif %}{{ "%.1f"|format(total_pnl_pct) }}%
      </div>
    </div>
    <div class="kpi">
      <div class="label">장기 가치 <span class="mode-badge mode-long">LONG</span></div>
      <div class="value neu">{{ "%.0f"|format(long.value) }}</div>
      <div class="sub">현금 {{ "%.0f"|format(long.cash) }}</div>
    </div>
    <div class="kpi">
      <div class="label">단타 가치 <span class="mode-badge mode-short">SHORT</span></div>
      <div class="value neu">{{ "%.0f"|format(short.value) }}</div>
      <div class="sub">현금 {{ "%.0f"|format(short.cash) }}</div>
    </div>
    <div class="kpi" style="border-color:rgba(63,185,80,.3)">
      <div class="label">정치인 카피 <span class="mode-badge" style="background:rgba(63,185,80,.15);color:#3fb950">POL</span></div>
      <div class="value neu">{{ "%.0f"|format(pol.value) }}</div>
      <div class="sub">현금 {{ "%.0f"|format(pol.cash) }}</div>
    </div>
  </div>

  <!-- 탭 -->
  <div class="tabs">
    <div class="tab tab-long active"  onclick="switchTab('long')">📈 장기 보유</div>
    <div class="tab tab-short"        onclick="switchTab('short')">⚡ 단타</div>
    <div class="tab tab-pol"          onclick="switchTab('pol')" style="color:#3fb950">🏛️ 정치인 따라하기</div>
  </div>

  <!-- ── 장기 탭 ── -->
  <div class="tab-panel active" id="panel-long">
    <div class="action-bar">
      <button class="btn btn-primary" onclick="runCycle('LONG')">
        <span class="spinner" id="spin-long"></span> 🔍 장기 스캔 + 매매
      </button>
      <button class="btn btn-ghost" onclick="runScan('LONG')">📡 신호만 스캔</button>
      <button class="btn btn-danger btn-sm" onclick="confirmReset('LONG')" style="margin-left:auto">초기화</button>
    </div>
    <div class="section" id="sig-long" style="display:none">
      <div class="section-header"><span class="section-title">📡 장기 신호</span></div>
      <table><thead><tr><th>종목</th><th>시장</th><th>액션</th><th>점수</th><th>정치인</th><th>뉴스</th><th>기술</th></tr></thead>
      <tbody id="sig-long-body"></tbody></table>
    </div>
    <div class="section">
      <div class="section-header">
        <span class="section-title">💼 장기 포지션</span>
        <span style="font-size:11px;color:var(--muted)">손절 -15% / 익절 없음 / 월 1회 체크</span>
      </div>
      {% if long.positions %}
      <table><thead><tr><th>종목</th><th>시장</th><th>수량</th><th>평균단가</th><th>현재가</th><th>평가손익</th><th>수익률</th><th></th></tr></thead>
      <tbody>{% for p in long.positions %}
        <tr>
          <td><strong>{{ p.ticker }}</strong></td><td>{{ p.market }}</td>
          <td>{{ "%.4f"|format(p.shares) }}</td><td>{{ "%.4f"|format(p.avg_cost) }}</td>
          <td>{{ "%.4f"|format(p.current_price) }}</td>
          <td class="{% if p.pnl>=0 %}pos{% else %}neg{% endif %}">{% if p.pnl>=0 %}+{% endif %}{{ "%.2f"|format(p.pnl) }}</td>
          <td class="{% if p.pnl_pct>=0 %}pos{% else %}neg{% endif %}">{% if p.pnl_pct>=0 %}+{% endif %}{{ p.pnl_pct }}%</td>
          <td><form method="post" action="/trading/sell"><input type="hidden" name="ticker" value="{{ p.ticker }}"><input type="hidden" name="market" value="{{ p.market }}"><input type="hidden" name="mode" value="LONG"><button type="submit" class="btn btn-danger btn-sm">매도</button></form></td>
        </tr>{% endfor %}
      </tbody></table>
      {% else %}<div class="empty">장기 포지션 없음</div>{% endif %}
    </div>
    <div class="section">
      <div class="section-header"><span class="section-title">📋 장기 거래 내역</span></div>
      {% if long.trades %}<table><thead><tr><th>시각</th><th>종목</th><th>액션</th><th>가격</th><th>손익</th><th>사유</th></tr></thead>
      <tbody>{% for t in long.trades %}
        <tr>
          <td style="color:var(--muted)">{{ t.timestamp[:16] }}</td><td><strong>{{ t.ticker }}</strong></td>
          <td><span class="{% if t.action=='BUY' %}act-buy{% else %}act-sell{% endif %}">{{ t.action }}</span></td>
          <td>{{ "%.2f"|format(t.price) }}</td>
          <td class="{% if t.pnl>0 %}pos{% elif t.pnl<0 %}neg{% endif %}">{% if t.pnl!=0 %}{% if t.pnl>0 %}+{% endif %}{{ "%.2f"|format(t.pnl) }}{% endif %}</td>
          <td style="color:var(--muted);font-size:11px">{{ t.reason }}</td>
        </tr>{% endfor %}
      </tbody></table>
      {% else %}<div class="empty">거래 없음</div>{% endif %}
    </div>
  </div>

  <!-- ── 단타 탭 ── -->
  <div class="tab-panel" id="panel-short">
    <div class="action-bar">
      <button class="btn btn-primary" style="background:var(--yellow)" onclick="runCycle('SHORT')">
        <span class="spinner" id="spin-short"></span> ⚡ 단타 스캔 + 매매
      </button>
      <button class="btn btn-ghost" onclick="runScan('SHORT')">📡 신호만 스캔</button>
      <button class="btn btn-danger btn-sm" onclick="confirmReset('SHORT')" style="margin-left:auto">초기화</button>
    </div>
    <div class="section" id="sig-short" style="display:none">
      <div class="section-header"><span class="section-title">📡 단타 신호</span></div>
      <table><thead><tr><th>종목</th><th>시장</th><th>액션</th><th>점수</th><th>정치인</th><th>뉴스</th><th>기술</th></tr></thead>
      <tbody id="sig-short-body"></tbody></table>
    </div>
    <div class="section">
      <div class="section-header">
        <span class="section-title">⚡ 단타 포지션</span>
        <span style="font-size:11px;color:var(--muted)">손절 -8% / 익절 +15% / 주 1회 체크</span>
      </div>
      {% if short.positions %}
      <table><thead><tr><th>종목</th><th>시장</th><th>수량</th><th>평균단가</th><th>현재가</th><th>평가손익</th><th>수익률</th><th></th></tr></thead>
      <tbody>{% for p in short.positions %}
        <tr>
          <td><strong>{{ p.ticker }}</strong></td><td>{{ p.market }}</td>
          <td>{{ "%.4f"|format(p.shares) }}</td><td>{{ "%.4f"|format(p.avg_cost) }}</td>
          <td>{{ "%.4f"|format(p.current_price) }}</td>
          <td class="{% if p.pnl>=0 %}pos{% else %}neg{% endif %}">{% if p.pnl>=0 %}+{% endif %}{{ "%.2f"|format(p.pnl) }}</td>
          <td class="{% if p.pnl_pct>=0 %}pos{% else %}neg{% endif %}">{% if p.pnl_pct>=0 %}+{% endif %}{{ p.pnl_pct }}%</td>
          <td><form method="post" action="/trading/sell"><input type="hidden" name="ticker" value="{{ p.ticker }}"><input type="hidden" name="market" value="{{ p.market }}"><input type="hidden" name="mode" value="SHORT"><button type="submit" class="btn btn-danger btn-sm">매도</button></form></td>
        </tr>{% endfor %}
      </tbody></table>
      {% else %}<div class="empty">단타 포지션 없음</div>{% endif %}
    </div>
    <div class="section">
      <div class="section-header"><span class="section-title">📋 단타 거래 내역</span></div>
      {% if short.trades %}<table><thead><tr><th>시각</th><th>종목</th><th>액션</th><th>가격</th><th>손익</th><th>사유</th></tr></thead>
      <tbody>{% for t in short.trades %}
        <tr>
          <td style="color:var(--muted)">{{ t.timestamp[:16] }}</td><td><strong>{{ t.ticker }}</strong></td>
          <td><span class="{% if t.action=='BUY' %}act-buy{% else %}act-sell{% endif %}">{{ t.action }}</span></td>
          <td>{{ "%.2f"|format(t.price) }}</td>
          <td class="{% if t.pnl>0 %}pos{% elif t.pnl<0 %}neg{% endif %}">{% if t.pnl!=0 %}{% if t.pnl>0 %}+{% endif %}{{ "%.2f"|format(t.pnl) }}{% endif %}</td>
          <td style="color:var(--muted);font-size:11px">{{ t.reason }}</td>
        </tr>{% endfor %}
      </tbody></table>
      {% else %}<div class="empty">거래 없음</div>{% endif %}
    </div>
  </div><!-- /panel-short -->

  <!-- ── 정치인 탭 ── -->
  <div class="tab-panel" id="panel-pol">
    <div class="action-bar">
      <button class="btn btn-primary" style="background:#3fb950;color:#000" onclick="runPol()">
        <span class="spinner" id="spin-pol"></span> 🏛️ 정치인 공시 스캔 + 매매
      </button>
      <button class="btn btn-danger btn-sm" onclick="confirmReset('POL')" style="margin-left:auto">초기화</button>
    </div>

    <div class="section">
      <div class="section-header">
        <span class="section-title">🏛️ 최신 의회 매매 공시 (최근 30일)</span>
        <span style="font-size:11px;color:var(--muted)">STOCK Act — 최대 45일 지연 공시</span>
      </div>
      {% if pol_feed %}
      <table><thead><tr><th>날짜</th><th>의원</th><th>원</th><th>종목</th><th>유형</th><th>금액</th></tr></thead>
      <tbody>{% for t in pol_feed[:30] %}
        <tr>
          <td style="color:var(--muted)">{{ t.date }}</td>
          <td><strong>{{ t.name }}</strong></td>
          <td style="color:var(--muted);font-size:11px">{{ t.chamber }}</td>
          <td><strong style="color:var(--blue)">{{ t.ticker }}</strong></td>
          <td><span class="{% if t.is_buy %}act-buy{% else %}act-sell{% endif %}">{% if t.is_buy %}매수{% else %}매도{% endif %}</span></td>
          <td style="font-size:11px;color:var(--muted)">{{ t.amount }}</td>
        </tr>{% endfor %}
      </tbody></table>
      {% else %}<div class="empty">정치인 공시 없음 (네트워크 연결 필요)</div>{% endif %}
    </div>

    {% if pol_candidates %}
    <div class="section">
      <div class="section-header">
        <span class="section-title">⭐ 카피트레이딩 후보</span>
        <span style="font-size:11px;color:var(--muted)">복수 의원 매수 = 신뢰도↑</span>
      </div>
      <table><thead><tr><th>종목</th><th>의원 수</th><th>최근 날짜</th><th>신뢰도</th><th>매수 의원</th></tr></thead>
      <tbody>{% for c in pol_candidates %}
        <tr>
          <td><strong style="color:var(--blue)">{{ c.ticker }}</strong></td>
          <td>{{ c.count }}명</td><td>{{ c.latest_date }}</td>
          <td><span style="color:#3fb950;font-weight:700">{{ "%.0f"|format(c.confidence*100) }}%</span></td>
          <td style="font-size:11px;color:var(--muted)">{{ c.politicians[:2]|map(attribute='name')|join(', ') }}</td>
        </tr>
      {% endfor %}</tbody></table>
    </div>
    {% endif %}

    <div class="section">
      <div class="section-header">
        <span class="section-title">💼 보유 포지션</span>
        <span style="font-size:11px;color:var(--muted)">손절 -12% / 90일 자동 청산</span>
      </div>
      {% if pol.positions %}
      <table><thead><tr><th>종목</th><th>진입일</th><th>평균단가</th><th>현재가</th><th>손익</th><th>수익률</th><th></th></tr></thead>
      <tbody>{% for p in pol.positions %}
        <tr>
          <td><strong>{{ p.ticker }}</strong></td>
          <td style="color:var(--muted)">{{ p.entry_date[:10] }}</td>
          <td>{{ "%.2f"|format(p.avg_cost) }}</td><td>{{ "%.2f"|format(p.current_price) }}</td>
          <td class="{% if p.pnl>=0 %}pos{% else %}neg{% endif %}">{% if p.pnl>=0 %}+{% endif %}{{ "%.2f"|format(p.pnl) }}</td>
          <td class="{% if p.pnl_pct>=0 %}pos{% else %}neg{% endif %}">{% if p.pnl_pct>=0 %}+{% endif %}{{ p.pnl_pct }}%</td>
          <td><form method="post" action="/trading/sell"><input type="hidden" name="ticker" value="{{ p.ticker }}"><input type="hidden" name="market" value="US"><input type="hidden" name="mode" value="POL"><button type="submit" class="btn btn-danger btn-sm">매도</button></form></td>
        </tr>{% endfor %}
      </tbody></table>
      {% else %}<div class="empty">포지션 없음 — 스캔 시 정치인 매수 감지되면 자동 진입</div>{% endif %}
    </div>

    <div class="section">
      <div class="section-header"><span class="section-title">📋 거래 내역</span></div>
      {% if pol.trades %}<table><thead><tr><th>시각</th><th>종목</th><th>액션</th><th>가격</th><th>손익</th><th>사유</th></tr></thead>
      <tbody>{% for t in pol.trades %}
        <tr>
          <td style="color:var(--muted)">{{ t.timestamp[:16] }}</td><td><strong>{{ t.ticker }}</strong></td>
          <td><span class="{% if t.action=='BUY' %}act-buy{% else %}act-sell{% endif %}">{{ t.action }}</span></td>
          <td>{{ "%.2f"|format(t.price) }}</td>
          <td class="{% if t.pnl>0 %}pos{% elif t.pnl<0 %}neg{% endif %}">{% if t.pnl!=0 %}{% if t.pnl>0 %}+{% endif %}{{ "%.2f"|format(t.pnl) }}{% endif %}</td>
          <td style="color:var(--muted);font-size:11px">{{ t.reason }}</td>
        </tr>{% endfor %}
      </tbody></table>
      {% else %}<div class="empty">거래 없음</div>{% endif %}
    </div>
  </div><!-- /panel-pol -->

</div><!-- /main -->
<div id="toast"></div>

<script>
function switchTab(name) {
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
  document.querySelector('.tab-' + name).classList.add('active');
  document.getElementById('panel-' + name).classList.add('active');
}

function showToast(msg, ok=true) {
  const t = document.getElementById('toast');
  t.textContent = msg; t.style.display = 'block';
  t.style.borderColor = ok ? '#3fb950' : '#f85149';
  setTimeout(() => t.style.display = 'none', 4000);
}

async function runCycle(mode) {
  const spin = document.getElementById('spin-' + mode.toLowerCase());
  spin.style.display = 'inline-block';
  try {
    const r    = await fetch('/trading/run?mode=' + mode, {method:'POST'});
    const data = await r.json();
    showToast(`[${mode}] 완료! 실행 ${data.executed?.length||0}건`);
    setTimeout(() => location.reload(), 1500);
  } catch(e) { showToast('오류: ' + e, false); }
  finally { spin.style.display = 'none'; }
}

async function runScan(mode) {
  showToast('스캔 중...', true);
  try {
    const r       = await fetch('/trading/scan?mode=' + mode);
    const signals = await r.json();
    const bodyId  = mode === 'LONG' ? 'sig-long-body' : 'sig-short-body';
    const secId   = mode === 'LONG' ? 'sig-long'      : 'sig-short';
    const tbody   = document.getElementById(bodyId);
    tbody.innerHTML = '';
    signals.forEach(s => {
      const col = s.score >= 0.15 ? '#3fb950' : s.score <= -0.15 ? '#f85149' : '#8b949e';
      const cls = s.action === 'BUY' ? 'act-buy' : s.action === 'SELL' ? 'act-sell' : 'act-hold';
      tbody.innerHTML += `<tr>
        <td><strong>${s.ticker}</strong></td><td>${s.market}</td>
        <td><span class="${cls}">${s.action}</span></td>
        <td style="color:${col};font-weight:700">${s.score >= 0 ? '+' : ''}${s.score.toFixed(3)}</td>
        <td class="breakdown">${s.breakdown.politician >= 0 ? '+' : ''}${s.breakdown.politician.toFixed(3)}</td>
        <td class="breakdown">${s.breakdown.news >= 0 ? '+' : ''}${s.breakdown.news.toFixed(3)}</td>
        <td class="breakdown">${s.breakdown.technical >= 0 ? '+' : ''}${s.breakdown.technical.toFixed(3)}</td>
      </tr>`;
    });
    document.getElementById(secId).style.display = 'block';
  } catch(e) { showToast('오류: ' + e, false); }
}

async function runPol() {
  const spin = document.getElementById('spin-pol');
  spin.style.display = 'inline-block';
  try {
    const r    = await fetch('/trading/run/pol', {method:'POST'});
    const data = await r.json();
    showToast(`[POL] 매수 ${data.executed?.length||0}건, 매도 ${data.sold?.length||0}건`);
    setTimeout(() => location.reload(), 1500);
  } catch(e) { showToast('오류: ' + e, false); }
  finally { spin.style.display = 'none'; }
}

function confirmReset(mode) {
  if (confirm(`[${mode}] 포트폴리오를 초기화하시겠습니까?`)) {
    fetch('/trading/reset?mode=' + mode, {method:'POST'}).then(() => location.reload());
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

    def _pdata(mode):
        v = get_portfolio_value(mode)
        return {
            "value":     v,
            "cash":      get_cash(mode),
            "positions": get_positions_with_pnl(mode),
            "trades":    get_trade_history(30, mode),
            "pnl":       v - INITIAL_CAPITAL * (0.60 if mode == "LONG" else 0.40),
        }

    long_d  = _pdata("LONG")
    short_d = _pdata("SHORT")
    pol_d   = _pdata("POL")
    total_v = long_d["value"] + short_d["value"] + pol_d["value"]
    total_pnl = total_v - INITIAL_CAPITAL
    total_pnl_pct = total_pnl / INITIAL_CAPITAL * 100 if INITIAL_CAPITAL else 0

    try:
        pol_feed       = get_all_recent_trades(days=30)
        pol_candidates = get_pol_buy_candidates(days=30)
    except Exception:
        pol_feed, pol_candidates = [], []

    return render_template_string(
        DASHBOARD_HTML,
        long=long_d, short=short_d, pol=pol_d,
        pol_feed=pol_feed,
        pol_candidates=pol_candidates,
        total_value=total_v,
        total_pnl=total_pnl,
        total_pnl_pct=round(total_pnl_pct, 2),
        initial_capital=INITIAL_CAPITAL,
        data_sources=get_data_source_status(),
        now=datetime.now().strftime("%Y-%m-%d %H:%M"),
    )


@app.route("/trading/run", methods=["POST"])
def api_run():
    mode = request.args.get("mode", "SHORT").upper()
    result = run_cycle(mode)
    return jsonify(result)


@app.route("/trading/scan")
def api_scan():
    mode = request.args.get("mode", "SHORT").upper()
    signals = scan_all(mode)
    return jsonify(signals)


@app.route("/trading/signal/<market>/<ticker>")
def api_signal(market, ticker):
    mode = request.args.get("mode", "SHORT").upper()
    sig = generate_signal(ticker.upper(), market.upper(), mode)
    return jsonify(sig)


@app.route("/trading/sell", methods=["POST"])
def manual_sell():
    ticker = request.form.get("ticker", "").strip().upper()
    market = request.form.get("market", "US").strip().upper()
    mode   = request.form.get("mode", "SHORT").strip().upper()
    execute_sell(ticker, market, reason="수동 매도", mode=mode)
    return redirect(url_for("dashboard"))


@app.route("/trading/monitor")
def monitor_page():
    from datetime import datetime
    jobs = []
    if _scheduler:
        for job in _scheduler.get_jobs():
            nxt = job.next_run_time
            jobs.append({
                "id":   job.id,
                "next": nxt.strftime("%Y-%m-%d %H:%M %Z") if nxt else "미정",
            })

    all_trades = get_trade_history(200)
    data_src   = get_data_source_status()

    html = """<!DOCTYPE html>
<html lang='ko'><head><meta charset='UTF-8'>
<title>모니터링 — AutoTrader</title>
<style>
  :root{--bg:#0d1117;--surface:#161b22;--border:#21262d;--text:#e6edf3;
        --muted:#8b949e;--green:#3fb950;--red:#f85149;--blue:#58a6ff;--yellow:#d29922}
  *{box-sizing:border-box;margin:0;padding:0}
  body{background:var(--bg);color:var(--text);font-family:'SF Mono',monospace;font-size:13px}
  .topbar{background:var(--surface);border-bottom:1px solid var(--border);
          padding:12px 20px;display:flex;align-items:center;gap:16px}
  .topbar h1{font-size:15px;font-weight:700;color:var(--blue)}
  .topbar a{color:var(--muted);text-decoration:none;font-size:12px}
  .main{max-width:1000px;margin:0 auto;padding:20px}
  .section{background:var(--surface);border:1px solid var(--border);
           border-radius:10px;margin-bottom:20px}
  .section-header{padding:12px 16px;border-bottom:1px solid var(--border);
                  font-size:13px;font-weight:700}
  table{width:100%;border-collapse:collapse}
  th{padding:8px 12px;text-align:left;font-size:11px;color:var(--muted);
     border-bottom:1px solid var(--border);font-weight:600;text-transform:uppercase}
  td{padding:9px 12px;border-bottom:1px solid var(--border);font-size:12px}
  tr:last-child td{border-bottom:none}
  .pos{color:var(--green)}.neg{color:var(--red)}.neu{color:var(--blue)}
  .act-buy{background:rgba(63,185,80,.15);color:var(--green);padding:2px 8px;border-radius:4px}
  .act-sell{background:rgba(248,81,73,.15);color:var(--red);padding:2px 8px;border-radius:4px}
  .ok{color:var(--green)}.warn{color:var(--yellow)}.err{color:var(--red)}
</style></head><body>
<div class='topbar'>
  <h1>AutoTrader</h1>
  <a href='/trading'>대시보드</a>
  <a href='/trading/backtest'>백테스트</a>
  <span style='margin-left:auto;color:var(--muted);font-size:11px'>""" + datetime.now().strftime("%Y-%m-%d %H:%M") + """</span>
</div>
<div class='main'>

<div class='section'>
  <div class='section-header'>⏰ 자동 스케줄 현황</div>
  <table><thead><tr><th>작업</th><th>다음 실행</th><th>주기</th></tr></thead><tbody>"""

    schedule_info = {
        "short_cycle": ("⚡ 단타 사이클",    "매주 금요일 15:00"),
        "long_cycle":  ("📈 장기 사이클",    "매월 첫 월요일 09:00"),
        "pol_cycle":   ("🏛️ 정치인 스캔",  "매일 08:00"),
    }
    if jobs:
        for j in jobs:
            label, freq = schedule_info.get(j["id"], (j["id"], ""))
            html += f"<tr><td>{label}</td><td class='neu'>{j['next']}</td><td style='color:var(--muted)'>{freq}</td></tr>"
    else:
        html += "<tr><td colspan='3' style='text-align:center;padding:20px;color:var(--muted)'>APScheduler 미설치 — pip install APScheduler</td></tr>"

    html += """</tbody></table></div>

<div class='section'>
  <div class='section-header'>🔌 데이터 소스 상태</div>
  <table><thead><tr><th>소스</th><th>상태</th><th>발급처</th></tr></thead><tbody>"""

    links = {
        "polygon":       "https://polygon.io/dashboard",
        "twelve_data":   "https://twelvedata.com",
        "alpha_vantage": "https://alphavantage.co",
        "yfinance":      "",
    }
    for src, status in data_src.items():
        cls = "ok" if "✅" in status else "warn" if "⚠️" in status else "err"
        link = links.get(src, "")
        link_html = f"<a href='{link}' target='_blank' style='color:var(--blue)'>{link}</a>" if link else "—"
        html += f"<tr><td>{src}</td><td class='{cls}'>{status}</td><td>{link_html}</td></tr>"

    html += """</tbody></table></div>

<div class='section'>
  <div class='section-header'>📋 전체 거래 일지 (최근 200건)</div>
  <table><thead><tr><th>시각</th><th>모드</th><th>종목</th><th>액션</th><th>가격</th><th>손익</th><th>사유</th></tr></thead><tbody>"""

    mode_colors = {"LONG": "#58a6ff", "SHORT": "#d29922", "POL": "#3fb950"}
    for t in all_trades:
        mode  = t.get("mode", "SHORT")
        col   = mode_colors.get(mode, "#8b949e")
        act   = t.get("action", "")
        cls   = "act-buy" if act == "BUY" else "act-sell"
        pnl   = t.get("pnl", 0) or 0
        pnl_s = f"+{pnl:,.0f}" if pnl > 0 else f"{pnl:,.0f}" if pnl < 0 else "—"
        pnl_c = "pos" if pnl > 0 else "neg" if pnl < 0 else ""
        html += (
            f"<tr>"
            f"<td style='color:var(--muted)'>{str(t.get('timestamp',''))[:16]}</td>"
            f"<td><span style='color:{col};font-weight:700'>{mode}</span></td>"
            f"<td><strong>{t.get('ticker','')}</strong></td>"
            f"<td><span class='{cls}'>{act}</span></td>"
            f"<td>{t.get('price',0):.2f}</td>"
            f"<td class='{pnl_c}'>{pnl_s}</td>"
            f"<td style='color:var(--muted);font-size:11px'>{str(t.get('reason',''))[:40]}</td>"
            f"</tr>"
        )

    html += "</tbody></table></div></div></body></html>"
    return html


@app.route("/trading/datasources")
def api_datasources():
    return jsonify(get_data_source_status())


@app.route("/trading/run/pol", methods=["POST"])
def api_run_pol():
    result = run_pol_cycle()
    return jsonify(result)


@app.route("/trading/reset", methods=["POST"])
def api_reset():
    mode = request.args.get("mode")
    reset_portfolio(mode.upper() if mode else None)
    return jsonify({"ok": True})


BACKTEST_HTML = r"""
<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>백테스트 — AutoTrader</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>
<style>
  :root {
    --bg:#0d1117;--surface:#161b22;--border:#21262d;
    --text:#e6edf3;--muted:#8b949e;
    --green:#3fb950;--red:#f85149;--blue:#58a6ff;--yellow:#d29922;
  }
  *{box-sizing:border-box;margin:0;padding:0}
  body{background:var(--bg);color:var(--text);font-family:'SF Mono','Fira Code',ui-monospace,monospace;font-size:13px}
  .topbar{background:var(--surface);border-bottom:1px solid var(--border);padding:12px 20px;display:flex;align-items:center;gap:16px}
  .topbar h1{font-size:15px;font-weight:700;color:var(--blue)}
  .topbar a{color:var(--muted);text-decoration:none;font-size:12px}
  .topbar a:hover{color:var(--text)}
  .badge{padding:3px 10px;border-radius:20px;font-size:11px;font-weight:700}
  .badge-bt{background:#1e2a1a;color:var(--yellow)}
  .main{max-width:1100px;margin:0 auto;padding:20px}

  /* config card */
  .config-card{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:20px;margin-bottom:20px}
  .config-card h2{font-size:13px;font-weight:700;margin-bottom:14px;color:var(--yellow)}
  .form-row{display:flex;gap:16px;flex-wrap:wrap;align-items:flex-end}
  .form-group{display:flex;flex-direction:column;gap:6px}
  .form-group label{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.4px}
  select,input[type=number]{background:#0d1117;border:1px solid var(--border);color:var(--text);
    padding:7px 10px;border-radius:6px;font-size:12px;font-family:inherit}
  select:focus,input:focus{outline:none;border-color:var(--blue)}
  .btn{display:inline-flex;align-items:center;gap:6px;padding:8px 18px;border-radius:6px;
    font-size:12px;font-weight:600;border:none;cursor:pointer;text-decoration:none}
  .btn-run{background:var(--yellow);color:#000}
  .btn-run:hover{opacity:.85}
  .btn-ghost{background:var(--surface);color:var(--text);border:1px solid var(--border)}

  /* KPI */
  .kpi-row{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:20px}
  @media(max-width:700px){.kpi-row{grid-template-columns:repeat(2,1fr)}}
  .kpi{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:16px}
  .kpi .label{font-size:11px;color:var(--muted);margin-bottom:6px;text-transform:uppercase;letter-spacing:.5px}
  .kpi .value{font-size:24px;font-weight:800}
  .kpi .sub{font-size:11px;color:var(--muted);margin-top:4px}
  .pos{color:var(--green)}.neg{color:var(--red)}.neu{color:var(--blue)}.warn{color:var(--yellow)}

  /* section */
  .section{background:var(--surface);border:1px solid var(--border);border-radius:10px;margin-bottom:20px}
  .section-header{padding:12px 16px;border-bottom:1px solid var(--border);display:flex;justify-content:space-between;align-items:center}
  .section-title{font-size:13px;font-weight:700}
  .chart-wrap{padding:16px;position:relative;height:280px}

  /* table */
  table{width:100%;border-collapse:collapse}
  th{padding:8px 12px;text-align:left;font-size:11px;color:var(--muted);border-bottom:1px solid var(--border);
    font-weight:600;text-transform:uppercase;letter-spacing:.4px}
  td{padding:9px 12px;border-bottom:1px solid var(--border);font-size:12px}
  tr:last-child td{border-bottom:none}
  tr:hover td{background:rgba(255,255,255,.03)}
  .empty{text-align:center;padding:30px;color:var(--muted)}

  .act-buy{background:rgba(63,185,80,.15);color:var(--green);padding:2px 8px;border-radius:4px}
  .act-sell{background:rgba(248,81,73,.15);color:var(--red);padding:2px 8px;border-radius:4px}

  /* spinner */
  #overlay{display:none;position:fixed;inset:0;background:rgba(13,17,23,.8);z-index:50;
    justify-content:center;align-items:center;flex-direction:column;gap:14px}
  #overlay.show{display:flex}
  .loader{width:36px;height:36px;border:3px solid var(--border);border-top-color:var(--yellow);
    border-radius:50%;animation:spin .8s linear infinite}
  @keyframes spin{to{transform:rotate(360deg)}}
  #overlay p{color:var(--muted);font-size:12px}

  /* results hidden by default */
  #results{display:none}
  #error-box{display:none;background:rgba(248,81,73,.1);border:1px solid var(--red);
    border-radius:8px;padding:14px;margin-bottom:16px;color:var(--red);font-size:12px}
</style>
</head>
<body>

<div class="topbar">
  <h1>AutoTrader</h1>
  <span class="badge badge-bt">BACKTEST</span>
  <a href="/trading">대시보드</a>
  <a href="/">리뷰온도</a>
</div>

<div class="main">

  <!-- 설정 카드 -->
  <div class="config-card">
    <h2>📊 백테스트 설정</h2>
    <div class="form-row">
      <div class="form-group">
        <label>기간</label>
        <select id="period">
          <option value="180">6개월</option>
          <option value="365" selected>1년</option>
          <option value="730">2년</option>
        </select>
      </div>
      <div class="form-group">
        <label>시장</label>
        <select id="market">
          <option value="US">미국 (US)</option>
          <option value="KR">한국 (KR)</option>
          <option value="ALL">전체</option>
        </select>
      </div>
      <div class="form-group">
        <label>신호 체크 주기</label>
        <select id="freq">
          <option value="W-FRI" selected>매주 금요일</option>
          <option value="ME">매월 말</option>
        </select>
      </div>
      <div class="form-group">
        <label>초기 자본금</label>
        <input type="number" id="capital" value="{{ initial_capital }}" min="1" step="1" style="width:110px">
      </div>
      <div class="form-group">
        <label>정치인 신호</label>
        <select id="use_pol">
          <option value="1" selected>사용</option>
          <option value="0">미사용</option>
        </select>
      </div>
      <button class="btn btn-run" onclick="runBacktest()">▶ 실행</button>
    </div>
  </div>

  <div id="error-box"></div>

  <!-- 결과 -->
  <div id="results">

    <!-- KPI -->
    <div class="kpi-row" id="kpi-row"></div>

    <!-- 수익 곡선 -->
    <div class="section">
      <div class="section-header">
        <span class="section-title">📈 포트폴리오 수익 곡선</span>
        <span id="bt-period" style="font-size:11px;color:var(--muted)"></span>
      </div>
      <div class="chart-wrap">
        <canvas id="equityChart"></canvas>
      </div>
    </div>

    <!-- 거래 내역 -->
    <div class="section">
      <div class="section-header">
        <span class="section-title">📋 시뮬레이션 거래 내역</span>
        <span id="trade-summary" style="font-size:11px;color:var(--muted)"></span>
      </div>
      <table>
        <thead>
          <tr><th>날짜</th><th>종목</th><th>시장</th><th>액션</th><th>체결가</th><th>손익</th><th>사유</th></tr>
        </thead>
        <tbody id="trade-tbody"></tbody>
      </table>
    </div>

  </div><!-- /results -->
</div><!-- /main -->

<!-- 로딩 오버레이 -->
<div id="overlay">
  <div class="loader"></div>
  <p id="overlay-msg">데이터 다운로드 중... (첫 실행 시 1~2분 소요)</p>
</div>

<script>
let equityChart = null;

async function runBacktest() {
  const overlay = document.getElementById('overlay');
  const errBox  = document.getElementById('error-box');
  errBox.style.display = 'none';
  overlay.classList.add('show');

  const msgs = [
    '데이터 다운로드 중...',
    '신호 계산 중...',
    '거래 시뮬레이션 중...',
    '성과 지표 산출 중...',
  ];
  let mi = 0;
  const mt = setInterval(() => {
    document.getElementById('overlay-msg').textContent = msgs[mi++ % msgs.length];
  }, 2500);

  try {
    const resp = await fetch('/trading/backtest/run', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({
        period:    parseInt(document.getElementById('period').value),
        market:    document.getElementById('market').value,
        freq:      document.getElementById('freq').value,
        capital:   parseFloat(document.getElementById('capital').value),
        use_pol:   document.getElementById('use_pol').value === '1',
      })
    });
    const data = await resp.json();
    clearInterval(mt);
    overlay.classList.remove('show');

    if (data.error) {
      errBox.textContent = '오류: ' + data.error;
      errBox.style.display = 'block';
      return;
    }
    renderResults(data);
  } catch(e) {
    clearInterval(mt);
    overlay.classList.remove('show');
    errBox.textContent = '오류: ' + e;
    errBox.style.display = 'block';
  }
}

function renderResults(d) {
  document.getElementById('results').style.display = 'block';

  // KPI
  const ret   = d.total_return;
  const dd    = d.max_drawdown;
  const kpis = [
    { label:'총 수익률', value:(ret>=0?'+':'')+ret+'%', sub:`최종 ${d.final_value.toFixed(2)} / 초기 ${d.initial_capital}`, cls: ret>=0?'pos':'neg' },
    { label:'최대 낙폭 (MDD)', value:dd.toFixed(1)+'%', sub:'고점 대비 최대 하락', cls: dd > -15 ? 'warn' : 'neg' },
    { label:'샤프 비율', value:d.sharpe_ratio.toFixed(2), sub:'주간 수익률 기준 (>1.0 양호)', cls: d.sharpe_ratio>=1?'pos':d.sharpe_ratio>=0?'warn':'neg' },
    { label:'승률', value:d.win_rate.toFixed(1)+'%', sub:`${d.sell_count}번 매도 중 승리`, cls: d.win_rate>=55?'pos':d.win_rate>=45?'warn':'neg' },
    { label:'연간화 수익률', value:(d.annualized_return>=0?'+':'')+d.annualized_return.toFixed(1)+'%', sub:`${d.period_days}일 백테스트 기준`, cls: d.annualized_return>=0?'pos':'neg' },
    { label:'프로핏 팩터', value:d.profit_factor, sub:'총수익/총손실 (>1.5 양호)', cls: parseFloat(d.profit_factor)>=1.5?'pos':parseFloat(d.profit_factor)>=1?'warn':'neg' },
    { label:'총 거래 수', value:d.trade_count+'건', sub:`매도 ${d.sell_count}건`, cls:'neu' },
    { label:'평균 손익', value:`W:+${d.avg_win.toFixed(3)} / L:${d.avg_loss.toFixed(3)}`, sub:'건당 평균 이익 / 손실', cls:'neu' },
  ];
  document.getElementById('kpi-row').style.gridTemplateColumns = 'repeat(4,1fr)';
  document.getElementById('kpi-row').innerHTML = kpis.map(k=>`
    <div class="kpi">
      <div class="label">${k.label}</div>
      <div class="value ${k.cls}">${k.value}</div>
      <div class="sub">${k.sub}</div>
    </div>`).join('');

  document.getElementById('bt-period').textContent = `${d.period_days}일 백테스트`;

  // 수익 곡선 차트
  const labels = d.equity_curve.map(e => e.date);
  const values = d.equity_curve.map(e => e.value);
  if (equityChart) equityChart.destroy();
  const ctx = document.getElementById('equityChart').getContext('2d');
  equityChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels,
      datasets: [{
        label: '포트폴리오 가치',
        data: values,
        borderColor: '#58a6ff',
        backgroundColor: 'rgba(88,166,255,.08)',
        borderWidth: 2,
        fill: true,
        tension: 0.3,
        pointRadius: 0,
      }, {
        label: '초기 자본금',
        data: Array(labels.length).fill(d.initial_capital),
        borderColor: '#21262d',
        borderDash: [4,4],
        borderWidth: 1,
        pointRadius: 0,
        fill: false,
      }]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend:{ labels:{ color:'#8b949e', font:{size:11} } } },
      scales: {
        x: { ticks:{ color:'#8b949e', maxTicksLimit:10, font:{size:10} }, grid:{ color:'#21262d' } },
        y: { ticks:{ color:'#8b949e', font:{size:10} }, grid:{ color:'#21262d' } }
      }
    }
  });

  // 거래 내역
  document.getElementById('trade-summary').textContent = `총 ${d.trades.length}건 (최근 100건 표시)`;
  const tbody = document.getElementById('trade-tbody');
  if (!d.trades.length) {
    tbody.innerHTML = '<tr><td colspan="7" class="empty">거래 없음</td></tr>';
    return;
  }
  tbody.innerHTML = d.trades.map(t => {
    const isBuy = t.action === 'BUY';
    const pnlHtml = t.pnl ? `<span class="${t.pnl>0?'pos':'neg'}">${t.pnl>0?'+':''}${t.pnl.toFixed(4)}</span>` : '-';
    return `<tr>
      <td style="color:var(--muted)">${t.date}</td>
      <td><strong>${t.ticker}</strong></td>
      <td>${t.market}</td>
      <td><span class="${isBuy?'act-buy':'act-sell'}">${t.action}</span></td>
      <td>${t.price.toFixed(4)}</td>
      <td>${pnlHtml}</td>
      <td style="color:var(--muted);font-size:11px">${t.reason}</td>
    </tr>`;
  }).join('');
}
</script>
</body>
</html>
"""


@app.route("/trading/backtest")
def backtest_page():
    return render_template_string(BACKTEST_HTML, initial_capital=INITIAL_CAPITAL)


@app.route("/trading/backtest/run", methods=["POST"])
def api_backtest_run():
    body = request.get_json(silent=True) or {}
    period = int(body.get("period", 365))
    market = body.get("market", "US")
    freq = body.get("freq", "W-FRI")
    capital = float(body.get("capital", INITIAL_CAPITAL))
    use_pol = bool(body.get("use_pol", True))

    if market == "US":
        tickers = [(t.strip(), "US") for t in WATCHLIST_US]
    elif market == "KR":
        tickers = [(t.strip(), "KR") for t in WATCHLIST_KR]
    else:
        tickers = [(t.strip(), "US") for t in WATCHLIST_US] + \
                  [(t.strip(), "KR") for t in WATCHLIST_KR]

    result = run_backtest(
        tickers_markets=tickers,
        period_days=period,
        initial_capital=capital,
        freq=freq,
        use_politician=use_pol,
    )
    return jsonify(result)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    app.run(debug=False, host="0.0.0.0", port=port)
