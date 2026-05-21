"""
미국 의회 의원 주식 거래 추적 (STOCK Act 공시 기반).

데이터 출처:
  - House Stock Watcher  : https://housestockwatcher.com
  - Senate Stock Watcher : https://senatestockwatcher.com
  두 사이트 모두 무료 오픈 데이터를 S3에 공개한다.

한국:
  - DART 전자공시 (주요주주·임원 지분 변동) – DART_API_KEY 필요
"""

import logging
import time
from datetime import datetime, timedelta

import requests

logger = logging.getLogger(__name__)

HOUSE_URL = (
    "https://house-stock-watcher-data.s3-us-east-2.amazonaws.com"
    "/data/all_transactions.json"
)
SENATE_URL = (
    "https://senate-stock-watcher-data.s3-us-east-2.amazonaws.com"
    "/aggregate/all_transactions_for_senator.json"
)

_cache: dict = {}
_CACHE_TTL = 3600  # 1시간


def _fetch_json(url: str) -> list:
    now = time.time()
    if url in _cache and now - _cache[url]["ts"] < _CACHE_TTL:
        return _cache[url]["data"]
    try:
        resp = requests.get(url, timeout=20)
        resp.raise_for_status()
        raw = resp.json()
        # Senate 데이터는 {senator: [trades]} 딕셔너리
        if isinstance(raw, dict):
            flat = []
            for senator, trades in raw.items():
                for t in trades:
                    t = dict(t)
                    t.setdefault("representative", senator)
                    t.setdefault("chamber", "Senate")
                    flat.append(t)
            raw = flat
        else:
            for t in raw:
                t.setdefault("chamber", "House")
        _cache[url] = {"ts": now, "data": raw}
        logger.info(f"정치인 거래 데이터 갱신: {url} ({len(raw)}건)")
        return raw
    except Exception as e:
        logger.warning(f"정치인 데이터 조회 실패 ({url}): {e}")
        return _cache.get(url, {}).get("data", [])


def get_politician_trades(ticker: str, days: int = 90) -> list:
    """특정 종목에 대한 최근 의회 거래 목록 반환"""
    cutoff = datetime.now() - timedelta(days=days)
    result = []
    ticker_up = ticker.upper().strip()

    for url in [HOUSE_URL, SENATE_URL]:
        for t in _fetch_json(url):
            raw_ticker = str(t.get("ticker", "")).upper().strip()
            if ticker_up not in raw_ticker.split("--")[0].split(","):
                # 쉼표/대시로 여러 종목이 묶인 경우도 처리
                if ticker_up != raw_ticker:
                    continue
            date_str = str(t.get("transaction_date", ""))[:10]
            try:
                date = datetime.strptime(date_str, "%Y-%m-%d")
            except ValueError:
                continue
            if date < cutoff:
                continue

            trade_type = str(t.get("type", "")).lower()
            result.append({
                "chamber": t.get("chamber", "House"),
                "name": t.get("representative", ""),
                "ticker": raw_ticker,
                "type": t.get("type", ""),
                "is_buy": "purchase" in trade_type or "buy" in trade_type,
                "is_sell": "sale" in trade_type or "sell" in trade_type,
                "amount": t.get("amount", ""),
                "date": date_str,
            })

    return sorted(result, key=lambda x: x["date"], reverse=True)


def get_politician_signal(ticker: str, days: int = 90) -> float:
    """
    정치인 순매수/순매도 비율을 신호로 변환.
    반환: -0.4 ~ +0.4 (BUY 우세 → 양수, SELL 우세 → 음수)
    """
    trades = get_politician_trades(ticker, days)
    if not trades:
        return 0.0
    buys = sum(1 for t in trades if t["is_buy"])
    sells = sum(1 for t in trades if t["is_sell"])
    total = buys + sells
    if total == 0:
        return 0.0
    ratio = (buys - sells) / total
    # 거래 건수 가중 (많을수록 신뢰도 ↑, 최대 1.0)
    confidence = min(1.0, total / 5)
    return round(ratio * 0.4 * confidence, 3)


def get_dart_insider_signal(ticker: str, api_key: str) -> float:
    """
    DART 주요주주·임원 지분 변동 신호 (한국 주식).
    api_key 없으면 0 반환.
    """
    if not api_key:
        return 0.0
    url = "https://opendart.fss.or.kr/api/majorstock.json"
    params = {
        "crtfc_key": api_key,
        "corp_code": ticker,  # DART corp_code 필요 (종목코드와 다름)
        "bgn_de": (datetime.now() - timedelta(days=90)).strftime("%Y%m%d"),
        "end_de": datetime.now().strftime("%Y%m%d"),
    }
    try:
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()
        items = data.get("list", [])
        buys = sum(1 for i in items if int(i.get("sp_stock_lmp_cnt", 0)) > 0)
        sells = sum(1 for i in items if int(i.get("sp_stock_lmp_cnt", 0)) < 0)
        total = buys + sells
        if total == 0:
            return 0.0
        return round(((buys - sells) / total) * 0.4, 3)
    except Exception as e:
        logger.warning(f"DART 조회 실패 {ticker}: {e}")
        return 0.0
