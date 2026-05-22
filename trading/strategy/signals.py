"""
신호 조합 엔진.

LONG (장기):  12M모멘텀 + 200MA추세 + 정치인(180일)
SHORT (단타): 3M모멘텀 + MACD + RSI + 거래량
"""

import logging

from trading import config
from trading.data.news import get_news_signal
from trading.data.politician import get_dart_insider_signal, get_politician_signal
from trading.data.prices import get_price_history
from trading.strategy.longterm import get_longterm_signal
from trading.strategy.technical import get_technical_signal

logger = logging.getLogger(__name__)


def generate_signal(ticker: str, market: str = "US", mode: str = "SHORT") -> dict:
    df = get_price_history(ticker, market, days=270 if mode == "SHORT" else 400)

    if market == "US":
        pol_days = 90 if mode == "SHORT" else 180
        politician = get_politician_signal(ticker, days=pol_days)
    else:
        politician = get_dart_insider_signal(ticker, config.DART_API_KEY)

    news = get_news_signal(ticker, market)

    if mode == "LONG":
        tech  = get_longterm_signal(df)
        buy_t = config.LONG_BUY_THRESHOLD
        sel_t = config.LONG_SELL_THRESHOLD
    else:
        tech  = get_technical_signal(df)
        buy_t = config.SHORT_BUY_THRESHOLD
        sel_t = config.SHORT_SELL_THRESHOLD

    score = round(politician + news + tech, 3)

    if score >= buy_t:
        action = "BUY"
    elif score <= sel_t:
        action = "SELL"
    else:
        action = "HOLD"

    return {
        "ticker": ticker, "market": market, "mode": mode,
        "action": action, "score": score,
        "breakdown": {"politician": politician, "news": news, "technical": tech},
    }


def scan_all(mode: str = "SHORT") -> list[dict]:
    results = []
    for ticker in config.WATCHLIST_US:
        try:
            results.append(generate_signal(ticker.strip(), "US", mode))
        except Exception as e:
            logger.error(f"US {ticker}: {e}")
    for ticker in config.WATCHLIST_KR:
        try:
            results.append(generate_signal(ticker.strip(), "KR", mode))
        except Exception as e:
            logger.error(f"KR {ticker}: {e}")
    results.sort(key=lambda x: abs(x["score"]), reverse=True)
    return results
