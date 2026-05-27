"""
멀티소스 가격 데이터 모듈.

우선순위:
  1. Polygon.io  — US 주식, 무료 API 키, IP 제한 없음
  2. Twelve Data — US + KR(KRX) 주식, 무료 800req/일
  3. Alpha Vantage — US, 무료 25req/일 (비상용)
  4. yfinance    — 최후 수단 (클라우드에서 차단될 수 있음)

환경변수:
  POLYGON_API_KEY       polygon.io 키 (무료: polygon.io/dashboard)
  TWELVE_DATA_KEY       twelvedata.com 키 (무료: twelvedata.com)
  ALPHA_VANTAGE_KEY     alphavantage.co 키 (무료: alphavantage.co)
"""

import logging
import time
from datetime import datetime, timedelta
from functools import lru_cache

import pandas as pd
import requests

from trading import config

logger = logging.getLogger(__name__)

_POLYGON_KEY    = getattr(config, "POLYGON_API_KEY",    "")
_TWELVE_KEY     = getattr(config, "TWELVE_DATA_KEY",    "")
_AV_KEY         = getattr(config, "ALPHA_VANTAGE_KEY",  "")

# 인메모리 캐시: {key → (timestamp, DataFrame)}
_cache: dict = {}
_CACHE_TTL = 3600  # 1시간


def _cached(key: str) -> pd.DataFrame | None:
    entry = _cache.get(key)
    if entry and time.time() - entry[0] < _CACHE_TTL:
        return entry[1]
    return None


def _store(key: str, df: pd.DataFrame) -> pd.DataFrame:
    _cache[key] = (time.time(), df)
    return df


def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    """컬럼명 통일 + DatetimeIndex 정렬"""
    col_map = {c.lower(): c for c in df.columns}
    rename = {}
    for want, variants in [
        ("Open",   ["open"]),
        ("High",   ["high"]),
        ("Low",    ["low"]),
        ("Close",  ["close", "adj close", "adjusted_close"]),
        ("Volume", ["volume"]),
    ]:
        for v in variants:
            if v in col_map:
                rename[col_map[v]] = want
    df = df.rename(columns=rename)
    for c in ["Open", "High", "Low", "Close", "Volume"]:
        if c not in df.columns:
            df[c] = 0.0
    df.index = pd.to_datetime(df.index)
    df = df[["Open", "High", "Low", "Close", "Volume"]].sort_index()
    df = df[~df.index.duplicated(keep="last")]
    return df.dropna(subset=["Close"])


# ── Polygon.io ────────────────────────────────────────────────

def _polygon_history(ticker: str, days: int) -> pd.DataFrame:
    if not _POLYGON_KEY:
        return pd.DataFrame()
    end   = datetime.now()
    start = end - timedelta(days=days + 10)
    url   = (
        f"https://api.polygon.io/v2/aggs/ticker/{ticker}/range/1/day"
        f"/{start.strftime('%Y-%m-%d')}/{end.strftime('%Y-%m-%d')}"
        f"?adjusted=true&sort=asc&limit=5000&apiKey={_POLYGON_KEY}"
    )
    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        results = r.json().get("results", [])
        if not results:
            return pd.DataFrame()
        df = pd.DataFrame(results)
        df.index = pd.to_datetime(df["t"], unit="ms")
        df = df.rename(columns={"o":"Open","h":"High","l":"Low","c":"Close","v":"Volume"})
        logger.info(f"[Polygon] {ticker} {len(df)}일")
        return _normalize(df)
    except Exception as e:
        logger.warning(f"[Polygon] {ticker} 실패: {e}")
        return pd.DataFrame()


def _polygon_current(ticker: str) -> float:
    if not _POLYGON_KEY:
        return 0.0
    url = f"https://api.polygon.io/v2/aggs/ticker/{ticker}/prev?adjusted=true&apiKey={_POLYGON_KEY}"
    try:
        r = requests.get(url, timeout=10)
        results = r.json().get("results", [])
        if results:
            return float(results[0]["c"])
    except Exception as e:
        logger.warning(f"[Polygon] 현재가 {ticker}: {e}")
    return 0.0


# ── Twelve Data ───────────────────────────────────────────────

def _twelve_symbol(ticker: str, market: str) -> str:
    if market == "KR":
        return f"{ticker}:KRX"
    return ticker


def _twelve_history(ticker: str, market: str, days: int) -> pd.DataFrame:
    if not _TWELVE_KEY:
        return pd.DataFrame()
    symbol   = _twelve_symbol(ticker, market)
    n_points = min(days + 10, 5000)
    url = (
        f"https://api.twelvedata.com/time_series"
        f"?symbol={symbol}&interval=1day&outputsize={n_points}"
        f"&order=ASC&apikey={_TWELVE_KEY}"
    )
    try:
        r = requests.get(url, timeout=15)
        data = r.json()
        if data.get("status") == "error" or "values" not in data:
            logger.warning(f"[TwelveData] {symbol}: {data.get('message','오류')}")
            return pd.DataFrame()
        df = pd.DataFrame(data["values"])
        df.index = pd.to_datetime(df["datetime"])
        df = df.drop(columns=["datetime"], errors="ignore")
        for c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
        logger.info(f"[TwelveData] {symbol} {len(df)}일")
        return _normalize(df)
    except Exception as e:
        logger.warning(f"[TwelveData] {ticker}/{market} 실패: {e}")
        return pd.DataFrame()


def _twelve_current(ticker: str, market: str) -> float:
    if not _TWELVE_KEY:
        return 0.0
    symbol = _twelve_symbol(ticker, market)
    url    = f"https://api.twelvedata.com/price?symbol={symbol}&apikey={_TWELVE_KEY}"
    try:
        r = requests.get(url, timeout=10)
        return float(r.json().get("price", 0))
    except Exception as e:
        logger.warning(f"[TwelveData] 현재가 {symbol}: {e}")
    return 0.0


# ── Alpha Vantage ─────────────────────────────────────────────

def _av_history(ticker: str, days: int) -> pd.DataFrame:
    if not _AV_KEY:
        return pd.DataFrame()
    url = (
        "https://www.alphavantage.co/query"
        f"?function=TIME_SERIES_DAILY_ADJUSTED&symbol={ticker}"
        f"&outputsize={'full' if days > 100 else 'compact'}&apikey={_AV_KEY}"
    )
    try:
        r    = requests.get(url, timeout=20)
        data = r.json().get("Time Series (Daily)", {})
        if not data:
            return pd.DataFrame()
        df = pd.DataFrame.from_dict(data, orient="index")
        df.index = pd.to_datetime(df.index)
        df = df.rename(columns={
            "1. open":"Open","2. high":"High","3. low":"Low",
            "5. adjusted close":"Close","6. volume":"Volume",
        })
        logger.info(f"[AlphaVantage] {ticker} {len(df)}일")
        return _normalize(df)
    except Exception as e:
        logger.warning(f"[AlphaVantage] {ticker} 실패: {e}")
        return pd.DataFrame()


def _av_current(ticker: str) -> float:
    if not _AV_KEY:
        return 0.0
    url = (
        "https://www.alphavantage.co/query"
        f"?function=GLOBAL_QUOTE&symbol={ticker}&apikey={_AV_KEY}"
    )
    try:
        r    = requests.get(url, timeout=10)
        data = r.json().get("Global Quote", {})
        price = data.get("05. price", 0)
        return float(price) if price else 0.0
    except Exception as e:
        logger.warning(f"[AlphaVantage] 현재가 {ticker}: {e}")
    return 0.0


# ── yfinance 폴백 ─────────────────────────────────────────────

def _yf_history(ticker: str, market: str, days: int) -> pd.DataFrame:
    try:
        import yfinance as yf
        sym = f"{ticker}.KS" if market == "KR" else ticker
        df  = yf.download(sym, period=f"{days}d", progress=False, auto_adjust=True)
        if not df.empty:
            logger.info(f"[yfinance] {sym} {len(df)}일")
        return _normalize(df) if not df.empty else pd.DataFrame()
    except Exception as e:
        logger.warning(f"[yfinance] {ticker} 실패: {e}")
        return pd.DataFrame()


def _yf_current(ticker: str, market: str) -> float:
    try:
        import yfinance as yf
        sym = f"{ticker}.KS" if market == "KR" else ticker
        t   = yf.Ticker(sym)
        p   = getattr(t.fast_info, "last_price", None)
        if p and p > 0:
            return float(p)
        h = t.history(period="2d")
        if not h.empty:
            return float(h["Close"].iloc[-1])
    except Exception:
        pass
    return 0.0


# ── 공개 API ─────────────────────────────────────────────────

def get_price_history(ticker: str, market: str = "US", days: int = 365) -> pd.DataFrame:
    """
    멀티소스 OHLCV 히스토리.
    Polygon → TwelveData → AlphaVantage → yfinance 순으로 시도.
    """
    key = f"hist:{ticker}:{market}:{days}"
    cached = _cached(key)
    if cached is not None:
        return cached

    ticker = ticker.strip().upper()
    df     = pd.DataFrame()

    if market == "US":
        if df.empty: df = _polygon_history(ticker, days)
        if df.empty: df = _twelve_history(ticker, market, days)
        if df.empty: df = _av_history(ticker, days)
        if df.empty: df = _yf_history(ticker, market, days)
    else:  # KR
        if df.empty: df = _twelve_history(ticker, market, days)
        if df.empty: df = _yf_history(ticker, market, days)

    if not df.empty:
        _store(key, df)
    else:
        logger.error(f"모든 소스 실패: {ticker}/{market} (API 키 확인 필요)")
    return df


def get_current_price(ticker: str, market: str = "US") -> float:
    """
    멀티소스 현재가.
    캐시 TTL 60초 (1분마다 갱신).
    """
    key = f"cur:{ticker}:{market}"
    entry = _cache.get(key)
    if entry and time.time() - entry[0] < 60:
        return entry[1]

    ticker = ticker.strip().upper()
    price  = 0.0

    if market == "US":
        if price <= 0: price = _polygon_current(ticker)
        if price <= 0: price = _twelve_current(ticker, market)
        if price <= 0: price = _av_current(ticker)
        if price <= 0: price = _yf_current(ticker, market)
    else:
        if price <= 0: price = _twelve_current(ticker, market)
        if price <= 0: price = _yf_current(ticker, market)

    if price > 0:
        _cache[key] = (time.time(), price)
    return price


def get_data_source_status() -> dict:
    """현재 사용 가능한 데이터 소스 상태 반환"""
    return {
        "polygon":      "✅ 활성" if _POLYGON_KEY else "❌ 키 없음 (polygon.io 무료 등록)",
        "twelve_data":  "✅ 활성" if _TWELVE_KEY  else "❌ 키 없음 (twelvedata.com 무료 등록)",
        "alpha_vantage":"✅ 활성" if _AV_KEY      else "❌ 키 없음 (alphavantage.co 무료 등록)",
        "yfinance":     "⚠️  폴백 (클라우드 환경에서 차단될 수 있음)",
    }


# ── 한국 종목 표시용 ─────────────────────────────────────────

KR_NAMES = {
    "005930": "삼성전자", "000660": "SK하이닉스", "035420": "네이버",
    "005380": "현대차",   "051910": "LG화학",     "035720": "카카오",
    "000270": "기아",     "068270": "셀트리온",
}


def ticker_display_name(ticker: str, market: str) -> str:
    if market == "KR":
        return KR_NAMES.get(ticker, ticker)
    return ticker
