import logging
from datetime import datetime, timedelta

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

try:
    import FinanceDataReader as fdr
    _FDR = True
except ImportError:
    _FDR = False
    logger.warning("FinanceDataReader 없음 – 한국 주식 가격 데이터 불가")

# 한국 종목코드 → 회사명 (표시용)
KR_NAMES = {
    "005930": "삼성전자",
    "000660": "SK하이닉스",
    "035420": "네이버",
    "005380": "현대차",
    "051910": "LG화학",
    "035720": "카카오",
    "000270": "기아",
    "068270": "셀트리온",
}


def get_price_history(ticker: str, market: str = "US", days: int = 90) -> pd.DataFrame:
    """OHLCV 히스토리 반환"""
    try:
        if market == "US":
            df = yf.download(ticker, period=f"{days}d", progress=False, auto_adjust=True)
            return df
        if _FDR:
            end = datetime.now()
            start = end - timedelta(days=days)
            return fdr.DataReader(ticker, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
    except Exception as e:
        logger.error(f"가격 조회 실패 {ticker}: {e}")
    return pd.DataFrame()


def get_current_price(ticker: str, market: str = "US") -> float:
    """현재가 반환 (0이면 조회 실패)"""
    try:
        if market == "US":
            t = yf.Ticker(ticker)
            fi = t.fast_info
            price = getattr(fi, "last_price", None)
            if price and price > 0:
                return float(price)
            hist = t.history(period="2d")
            if not hist.empty:
                return float(hist["Close"].iloc[-1])
        else:
            df = get_price_history(ticker, market, days=5)
            if not df.empty:
                return float(df["Close"].iloc[-1])
    except Exception as e:
        logger.error(f"현재가 조회 실패 {ticker}: {e}")
    return 0.0


def ticker_display_name(ticker: str, market: str) -> str:
    if market == "KR":
        return KR_NAMES.get(ticker, ticker)
    return ticker
