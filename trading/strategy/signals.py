"""
신호 조합 엔진.

신호 구성 (합계 최대 ±1.0):
  정치인 거래  ±0.40  (의회 순매수/순매도 비율)
  뉴스 감성    ±0.30  (헤드라인 키워드 점수)
  기술적 지표  ±0.30  (RSI + MACD + MA + 볼린저)

BUY_THRESHOLD  이상 → BUY
SELL_THRESHOLD 이하 → SELL
그 외          → HOLD
"""

import logging

from trading import config
from trading.data.news import get_news_signal
from trading.data.politician import get_dart_insider_signal, get_politician_signal
from trading.data.prices import get_price_history
from trading.strategy.technical import get_technical_signal

logger = logging.getLogger(__name__)


def generate_signal(ticker: str, market: str = "US") -> dict:
    """단일 종목 종합 신호 생성"""
    df = get_price_history(ticker, market)

    if market == "US":
        politician = get_politician_signal(ticker)
    else:
        politician = get_dart_insider_signal(ticker, config.DART_API_KEY)

    news = get_news_signal(ticker, market)
    tech = get_technical_signal(df)

    score = round(politician + news + tech, 3)

    if score >= config.BUY_THRESHOLD:
        action = "BUY"
    elif score <= config.SELL_THRESHOLD:
        action = "SELL"
    else:
        action = "HOLD"

    return {
        "ticker": ticker,
        "market": market,
        "action": action,
        "score": score,
        "breakdown": {
            "politician": politician,
            "news": news,
            "technical": tech,
        },
    }


def scan_all() -> list[dict]:
    """전체 감시 종목 스캔 후 신호 목록 반환"""
    results = []
    for ticker in config.WATCHLIST_US:
        try:
            results.append(generate_signal(ticker.strip(), "US"))
        except Exception as e:
            logger.error(f"US {ticker}: {e}")
    for ticker in config.WATCHLIST_KR:
        try:
            results.append(generate_signal(ticker.strip(), "KR"))
        except Exception as e:
            logger.error(f"KR {ticker}: {e}")
    results.sort(key=lambda x: abs(x["score"]), reverse=True)
    return results
