import os
from dotenv import load_dotenv

load_dotenv()

# ── 자금 설정 ────────────────────────────────────────────────
INITIAL_CAPITAL    = float(os.getenv("INITIAL_CAPITAL", "100"))
MAX_POSITION_SIZE  = float(os.getenv("MAX_POSITION_SIZE", "0.25"))   # 종목당 최대 25%
STOP_LOSS_PCT      = float(os.getenv("STOP_LOSS_PCT", "0.12"))       # 손절: -12% (여유 확대)
TAKE_PROFIT_PCT    = float(os.getenv("TAKE_PROFIT_PCT", "0.30"))     # 익절: +30% (모멘텀 유지)

# ── 신호 임계값 ───────────────────────────────────────────────
# 기술 신호 범위가 ±0.50으로 확대됨 → 임계값도 함께 조정
BUY_THRESHOLD      = float(os.getenv("BUY_THRESHOLD", "0.15"))       # 기존 0.35 → 0.15
SELL_THRESHOLD     = float(os.getenv("SELL_THRESHOLD", "-0.20"))     # 기존 -0.35 → -0.20

# ── 감시 종목 ─────────────────────────────────────────────────
WATCHLIST_US = os.getenv(
    "WATCHLIST_US",
    "AAPL,MSFT,NVDA,TSLA,AMZN,META,GOOGL,JPM,NFLX,AMD"
).split(",")

WATCHLIST_KR = os.getenv(
    "WATCHLIST_KR",
    "005930,000660,035420,005380,051910,035720,000270,068270"
).split(",")
# 삼성전자, SK하이닉스, 네이버, 현대차, LG화학, 카카오, 기아, 셀트리온

# ── API 키 (없어도 작동, 있으면 더 정확해짐) ──────────────────
DART_API_KEY = os.getenv("DART_API_KEY", "")
NEWS_API_KEY = os.getenv("NEWS_API_KEY", "")

# ── 저장소 ───────────────────────────────────────────────────
DB_PATH = os.getenv("TRADING_DB_PATH", "trading.db")
