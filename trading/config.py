import os
from dotenv import load_dotenv

load_dotenv()

# ── 공통 자금 ────────────────────────────────────────────────
INITIAL_CAPITAL   = float(os.getenv("INITIAL_CAPITAL", "1000000"))

# ── 장기 포트폴리오 설정 (60% 자본 배분) ─────────────────────
LONG_CAPITAL_RATIO    = float(os.getenv("LONG_CAPITAL_RATIO", "0.60"))
LONG_MAX_POSITION     = float(os.getenv("LONG_MAX_POSITION", "0.30"))   # 종목당 30%
LONG_STOP_LOSS        = float(os.getenv("LONG_STOP_LOSS", "0.15"))      # 손절 -15%
LONG_TAKE_PROFIT      = float(os.getenv("LONG_TAKE_PROFIT", "0.0"))     # 0 = 익절 없음
LONG_BUY_THRESHOLD    = float(os.getenv("LONG_BUY_THRESHOLD", "0.20"))
LONG_SELL_THRESHOLD   = float(os.getenv("LONG_SELL_THRESHOLD", "-0.15"))

# ── 단타 포트폴리오 설정 (40% 자본 배분) ─────────────────────
SHORT_CAPITAL_RATIO   = float(os.getenv("SHORT_CAPITAL_RATIO", "0.40"))
SHORT_MAX_POSITION    = float(os.getenv("SHORT_MAX_POSITION", "0.20"))  # 종목당 20%
SHORT_STOP_LOSS       = float(os.getenv("SHORT_STOP_LOSS", "0.08"))     # 손절 -8%
SHORT_TAKE_PROFIT     = float(os.getenv("SHORT_TAKE_PROFIT", "0.15"))   # 익절 +15%
SHORT_BUY_THRESHOLD   = float(os.getenv("SHORT_BUY_THRESHOLD", "0.15"))
SHORT_SELL_THRESHOLD  = float(os.getenv("SHORT_SELL_THRESHOLD", "-0.20"))

# ── 정치인 카피트레이딩 설정 (20% 자본 배분) ─────────────────
POL_CAPITAL_RATIO     = float(os.getenv("POL_CAPITAL_RATIO", "0.20"))
POL_MAX_POSITION      = float(os.getenv("POL_MAX_POSITION", "0.25"))    # 종목당 25%
POL_STOP_LOSS         = float(os.getenv("POL_STOP_LOSS", "0.12"))       # 손절 -12%
POL_HOLD_DAYS         = int(os.getenv("POL_HOLD_DAYS", "90"))           # 최대 보유일
POL_SCAN_DAYS         = int(os.getenv("POL_SCAN_DAYS", "30"))           # 최근 N일 공시 스캔

# 자본금 재배분 (LONG 50% / SHORT 30% / POL 20%)
LONG_CAPITAL_RATIO    = float(os.getenv("LONG_CAPITAL_RATIO", "0.50"))
SHORT_CAPITAL_RATIO   = float(os.getenv("SHORT_CAPITAL_RATIO", "0.30"))

# ── 하위 호환 (단타 기본값으로 alias) ─────────────────────────
MAX_POSITION_SIZE = SHORT_MAX_POSITION
STOP_LOSS_PCT     = SHORT_STOP_LOSS
TAKE_PROFIT_PCT   = SHORT_TAKE_PROFIT
BUY_THRESHOLD     = SHORT_BUY_THRESHOLD
SELL_THRESHOLD    = SHORT_SELL_THRESHOLD

# ── 감시 종목 ─────────────────────────────────────────────────
WATCHLIST_US = os.getenv(
    "WATCHLIST_US",
    "AAPL,MSFT,NVDA,TSLA,AMZN,META,GOOGL,JPM,NFLX,AMD"
).split(",")

WATCHLIST_KR = os.getenv(
    "WATCHLIST_KR",
    "005930,000660,035420,005380,051910,035720,000270,068270"
).split(",")

# ── API 키 ───────────────────────────────────────────────────
DART_API_KEY = os.getenv("DART_API_KEY", "")
NEWS_API_KEY = os.getenv("NEWS_API_KEY", "")

# ── 저장소 ───────────────────────────────────────────────────
DB_PATH = os.getenv("TRADING_DB_PATH", "trading.db")
