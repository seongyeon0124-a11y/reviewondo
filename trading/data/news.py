"""
뉴스 감성 분석.
- Yahoo Finance RSS (무료, API 키 불필요)
- Naver Finance RSS (한국)
- 간단한 키워드 감성 사전 기반
"""

import logging
import xml.etree.ElementTree as ET
from urllib.request import urlopen, Request
from urllib.error import URLError

logger = logging.getLogger(__name__)

POSITIVE = [
    # 영어
    "surge", "rally", "beat", "profit", "gain", "rise", "strong", "bullish",
    "upgrade", "buy", "growth", "record", "exceed", "outperform", "breakout",
    "momentum", "optimistic", "rebound", "recovery", "boom",
    # 한국어
    "상승", "급등", "호실적", "매수", "성장", "흑자", "긍정", "최고",
    "수익", "호황", "돌파", "회복", "반등", "강세",
]
NEGATIVE = [
    # 영어
    "fall", "drop", "loss", "miss", "decline", "weak", "bearish", "downgrade",
    "sell", "cut", "concern", "risk", "warn", "underperform", "crash",
    "recession", "layoff", "bankruptcy", "fraud",
    # 한국어
    "하락", "급락", "손실", "매도", "우려", "위기", "적자", "약세",
    "폭락", "부진", "침체", "경고", "리콜", "소송",
]


def _score_text(text: str) -> float:
    text = text.lower()
    score = 0.0
    for w in POSITIVE:
        if w in text:
            score += 0.15
    for w in NEGATIVE:
        if w in text:
            score -= 0.15
    return max(-1.0, min(1.0, score))


def _fetch_rss_titles(url: str, max_items: int = 15) -> list[str]:
    try:
        req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(req, timeout=10) as resp:
            xml = resp.read()
        root = ET.fromstring(xml)
        titles = []
        for item in root.iter("item"):
            title = item.findtext("title") or ""
            desc = item.findtext("description") or ""
            titles.append(title + " " + desc)
            if len(titles) >= max_items:
                break
        return titles
    except (URLError, ET.ParseError) as e:
        logger.debug(f"RSS 조회 실패 ({url}): {e}")
        return []


def get_news_sentiment(ticker: str, market: str = "US") -> float:
    """최근 뉴스 헤드라인 평균 감성 점수 (-1 ~ +1)"""
    urls = []
    if market == "US":
        urls.append(
            f"https://feeds.finance.yahoo.com/rss/2.0/headline"
            f"?s={ticker}&region=US&lang=en-US"
        )
        urls.append(
            f"https://news.google.com/rss/search?q={ticker}+stock"
            f"&hl=en&gl=US&ceid=US:en"
        )
    else:
        # 한국: 네이버 금융 뉴스
        urls.append(
            f"https://finance.naver.com/item/news_news.nhn?code={ticker}"
        )
        urls.append(
            f"https://news.google.com/rss/search?q={ticker}&hl=ko&gl=KR&ceid=KR:ko"
        )

    all_texts: list[str] = []
    for url in urls:
        all_texts.extend(_fetch_rss_titles(url))

    if not all_texts:
        return 0.0

    scores = [_score_text(t) for t in all_texts]
    return round(sum(scores) / len(scores), 3)


def get_news_signal(ticker: str, market: str = "US") -> float:
    """뉴스 신호 (최대 ±0.3 기여)"""
    raw = get_news_sentiment(ticker, market)
    return round(raw * 0.3, 3)
