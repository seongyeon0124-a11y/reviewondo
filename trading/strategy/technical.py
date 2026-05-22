"""
개선된 기술적 신호 엔진.

핵심 철학: 모멘텀 + 트렌드 필터 + 타이밍
  - 모멘텀: 3개월 수익률 (가장 강력한 실증 예측 변수)
  - 트렌드: 200MA 위/아래 (상승장/하락장 필터)
  - 타이밍: MACD 전환 + RSI 극단값

신호 범위: ±0.50 (기존 ±0.30에서 확대)
"""

import pandas as pd


def _momentum(close: pd.Series) -> float:
    """3개월(63일) 수익률 신호. 최근 1주 제외(단기반전 회피)."""
    if len(close) < 70:
        return 0.0
    ret = float(close.iloc[-5] / close.iloc[-68] - 1)  # 63거래일 기준, 최근 5일 제외
    # ±30% 수익률 → ±1.0으로 정규화
    return max(-1.0, min(1.0, ret / 0.30))


def _trend_filter(close: pd.Series) -> float:
    """
    200MA 대비 현재가 위치 + 50/200 기울기.
    200MA 위 → 양수, 아래 → 음수
    """
    if len(close) < 210:
        return 0.0
    ma50  = float(close.rolling(50).mean().iloc[-1])
    ma200 = float(close.rolling(200).mean().iloc[-1])
    cur   = float(close.iloc[-1])
    if ma200 < 1e-9:
        return 0.0
    # 현재가 vs 200MA 괴리율
    position = (cur - ma200) / ma200
    # 50MA vs 200MA (골든/데스크로스 강도)
    cross = (ma50 - ma200) / ma200
    score = position * 0.6 + cross * 0.4
    return max(-1.0, min(1.0, score * 10))  # ±10% → ±1


def _macd_signal(close: pd.Series) -> float:
    """MACD 히스토그램 방향 + 크기 (표준편차 정규화)"""
    ema12  = close.ewm(span=12, adjust=False).mean()
    ema26  = close.ewm(span=26, adjust=False).mean()
    macd   = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    hist   = macd - signal
    std    = float(hist.rolling(52).std().iloc[-1])
    if std < 1e-9:
        return 0.0
    return max(-1.0, min(1.0, float(hist.iloc[-1]) / std))


def _rsi_signal(close: pd.Series, period: int = 14) -> float:
    """RSI 극단값만 포착. 30 이하 → 매수, 70 이상 → 매도"""
    delta = close.diff()
    up   = delta.clip(lower=0).rolling(period).mean()
    down = (-delta.clip(upper=0)).rolling(period).mean()
    rs   = up / down.replace(0, 1e-9)
    rsi  = float((100 - 100 / (1 + rs)).dropna().iloc[-1]) if len((100 - 100 / (1 + rs)).dropna()) > 0 else 50.0
    if rsi <= 30:
        return (30 - rsi) / 30  # 최대 +1.0
    if rsi >= 70:
        return (70 - rsi) / 30  # 최소 -1.0
    return 0.0  # 중간 구간은 신호 없음


def _volume_confirm(df: pd.DataFrame) -> float:
    """최근 거래량이 20일 평균보다 50% 이상 높으면 방향성 강화"""
    if "Volume" not in df.columns or len(df) < 25:
        return 0.0
    vol     = df["Volume"].squeeze()
    cur_vol = float(vol.iloc[-1])
    avg_vol = float(vol.iloc[-21:-1].mean())
    if avg_vol < 1e-3:
        return 0.0
    ratio   = cur_vol / avg_vol  # 1.5 이상이면 강한 거래량
    close   = df["Close"].squeeze()
    price_up = float(close.iloc[-1]) > float(close.iloc[-2])
    sign    = 1.0 if price_up else -1.0
    return sign * min(1.0, max(0.0, (ratio - 1.0)))  # 거래량 50% 초과분을 신호로


def get_technical_signal(df: pd.DataFrame) -> float:
    """
    개선된 합성 기술 신호 (범위 ±0.50).

    가중치:
      모멘텀(3M)   40% → 최대 ±0.20
      트렌드(200MA) 30% → 최대 ±0.15
      MACD         20% → 최대 ±0.10
      RSI 극단값    5% → 최대 ±0.025
      거래량 확인   5% → 최대 ±0.025
    """
    if df is None or df.empty or len(df) < 30:
        return 0.0

    close = df["Close"].squeeze()
    if hasattr(close, "columns"):
        close = close.iloc[:, 0]

    mom    = _momentum(close)
    trend  = _trend_filter(close)
    macd   = _macd_signal(close)
    rsi    = _rsi_signal(close)
    vol    = _volume_confirm(df)

    # 트렌드 필터: 200MA 아래면 모멘텀 신호를 50% 감쇄
    if trend < -0.3:
        mom = mom * 0.5

    combined = mom * 0.40 + trend * 0.30 + macd * 0.20 + rsi * 0.05 + vol * 0.05
    return round(combined * 0.50 / 0.50, 3)  # ±0.50 범위로 반환
