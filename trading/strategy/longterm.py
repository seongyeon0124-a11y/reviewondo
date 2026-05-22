"""
장기 보유 전략 신호.

핵심: 12개월 모멘텀 + 200MA 추세 + 정치인 신호(180일 윈도우)
체크 주기: 월 1회 (매월 첫 번째 거래일)
목적: 수개월~1년 보유, 큰 추세 편승
"""

import pandas as pd


def _momentum_12m(close: pd.Series) -> float:
    """12개월(252일) 수익률. 최근 1주 제외(단기반전 회피)."""
    if len(close) < 260:
        return 0.0
    ret = float(close.iloc[-5] / close.iloc[-257] - 1)
    return max(-1.0, min(1.0, ret / 0.50))  # ±50% → ±1.0


def _trend_strength(close: pd.Series) -> float:
    """200MA 위치 + 방향성 (기울기)."""
    if len(close) < 210:
        return 0.0
    ma200_now  = float(close.rolling(200).mean().iloc[-1])
    ma200_prev = float(close.rolling(200).mean().iloc[-20])
    cur        = float(close.iloc[-1])
    if ma200_now < 1e-9:
        return 0.0
    position  = (cur - ma200_now) / ma200_now        # 200MA 위/아래
    slope     = (ma200_now - ma200_prev) / ma200_prev  # 200MA 방향
    return max(-1.0, min(1.0, position * 8 + slope * 20))


def _volatility_penalty(close: pd.Series) -> float:
    """연환산 변동성이 50% 초과하면 신호 감쇄 패널티."""
    if len(close) < 60:
        return 1.0
    ann_vol = float(close.pct_change().dropna().iloc[-60:].std() * (252 ** 0.5))
    if ann_vol > 0.50:
        return max(0.3, 1.0 - (ann_vol - 0.50) * 2)
    return 1.0


def get_longterm_signal(df: pd.DataFrame) -> float:
    """
    장기 보유 기술 신호 (범위 ±0.50).

    가중치:
      12M 모멘텀  55% → 최대 ±0.275
      200MA 추세  35% → 최대 ±0.175
      단기 확인   10% → 최대 ±0.050
    """
    if df is None or df.empty or len(df) < 60:
        return 0.0

    close = df["Close"].squeeze()
    if hasattr(close, "columns"):
        close = close.iloc[:, 0]

    mom12  = _momentum_12m(close)
    trend  = _trend_strength(close)
    pen    = _volatility_penalty(close)

    # 단기(1M) 모멘텀 확인 — 추세 진입 타이밍
    if len(close) >= 25:
        mom1m = float(close.iloc[-1] / close.iloc[-22] - 1)
        confirm = max(-1.0, min(1.0, mom1m / 0.10))
    else:
        confirm = 0.0

    combined = mom12 * 0.55 + trend * 0.35 + confirm * 0.10
    return round(combined * pen * 0.50, 3)
