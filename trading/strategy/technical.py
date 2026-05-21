"""
기술적 지표 계산 모듈.
RSI + MACD + 이동평균 크로스를 조합한 합성 신호 반환.
"""

import pandas as pd


def _rsi(close: pd.Series, period: int = 14) -> float:
    delta = close.diff()
    up = delta.clip(lower=0).rolling(period).mean()
    down = (-delta.clip(upper=0)).rolling(period).mean()
    rs = up / down.replace(0, 1e-9)
    val = 100 - (100 / (1 + rs))
    return float(val.dropna().iloc[-1]) if len(val.dropna()) > 0 else 50.0


def _macd_hist(close: pd.Series) -> float:
    """MACD 히스토그램을 표준편차로 정규화 → -1 ~ +1"""
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    hist = macd - signal
    std = float(hist.std())
    if std < 1e-9:
        return 0.0
    return max(-1.0, min(1.0, float(hist.iloc[-1]) / std))


def _ma_trend(close: pd.Series) -> float:
    """MA20/MA50 괴리율 → -1 ~ +1 (골든크로스 영역 양수)"""
    if len(close) < 52:
        return 0.0
    ma20 = float(close.rolling(20).mean().iloc[-1])
    ma50 = float(close.rolling(50).mean().iloc[-1])
    if ma50 < 1e-9:
        return 0.0
    ratio = (ma20 - ma50) / ma50
    return max(-1.0, min(1.0, ratio * 20))  # ±5% → ±1


def _bollinger_position(close: pd.Series, period: int = 20) -> float:
    """볼린저밴드 내 현재가 위치 → -1(상단) ~ +1(하단)"""
    if len(close) < period + 2:
        return 0.0
    ma = close.rolling(period).mean()
    std = close.rolling(period).std()
    upper = ma + 2 * std
    lower = ma - 2 * std
    cur = float(close.iloc[-1])
    u = float(upper.iloc[-1])
    lo = float(lower.iloc[-1])
    band = u - lo
    if band < 1e-9:
        return 0.0
    pos = (cur - lo) / band  # 0(하단) ~ 1(상단)
    return round(1.0 - 2 * pos, 3)  # 하단 근처 → +1(매수), 상단 → -1(매도)


def get_technical_signal(df: pd.DataFrame) -> float:
    """
    합성 기술적 신호 (최대 기여도 ±0.3).
    각 지표 가중치:
      RSI  40% · MACD 30% · MA크로스 15% · 볼린저 15%
    """
    if df is None or df.empty or len(df) < 30:
        return 0.0

    close = df["Close"].squeeze()
    if hasattr(close, "columns"):  # MultiIndex 컬럼 방어
        close = close.iloc[:, 0]

    rsi_val = _rsi(close)
    rsi_sig = (50 - rsi_val) / 50  # 30→+0.4, 70→-0.4

    macd = _macd_hist(close)
    ma = _ma_trend(close)
    boll = _bollinger_position(close)

    combined = rsi_sig * 0.40 + macd * 0.30 + ma * 0.15 + boll * 0.15
    return round(combined * 0.30, 3)  # ±0.30 스케일
