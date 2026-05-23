"""
정치인 카피트레이딩 전략.

원칙:
  1. 최근 30일 의회 의원 매수 공시 스캔
  2. 유의미한 금액($15,001+)의 매수 → 즉시 따라 매수
  3. 해당 의원이 매도 공시 → 따라 매도
  4. 90일 후 자동 청산 (정치인 정보 우위 희석 시점)
  5. 손절: -12%
"""

import logging
from datetime import datetime, timedelta

from trading.data.politician import get_all_recent_trades, get_politician_trades

logger = logging.getLogger(__name__)


def get_pol_buy_candidates(days: int = 30) -> list[dict]:
    """
    최근 정치인 매수 공시 중 따라살 후보 반환.
    동일 종목에 여러 의원이 샀으면 신뢰도 ↑
    """
    trades = get_all_recent_trades(days=days)
    buys   = [t for t in trades if t["is_buy"]]

    # 종목별 집계
    ticker_map: dict[str, dict] = {}
    for t in buys:
        tk = t["ticker"]
        if tk not in ticker_map:
            ticker_map[tk] = {
                "ticker":      tk,
                "politicians": [],
                "count":       0,
                "sig_count":   0,
                "latest_date": t["date"],
            }
        entry = ticker_map[tk]
        entry["politicians"].append({"name": t["name"], "date": t["date"], "amount": t["amount"]})
        entry["count"] += 1
        if t["significant"]:
            entry["sig_count"] += 1
        if t["date"] > entry["latest_date"]:
            entry["latest_date"] = t["date"]

    # 신뢰도 점수: 의원 수 + 유의미 금액 비중
    candidates = []
    for tk, info in ticker_map.items():
        score = min(1.0, info["count"] / 3) * 0.5 + min(1.0, info["sig_count"] / 2) * 0.5
        candidates.append({**info, "confidence": round(score, 2)})

    return sorted(candidates, key=lambda x: (-x["confidence"], x["latest_date"]), reverse=False)


def get_pol_sell_signal(ticker: str, entry_date: str, days_held: int = 90) -> tuple[bool, str]:
    """
    종목 매도 여부 판단.
    반환: (True/False, 사유)
    """
    # 1. 보유 기간 초과
    try:
        entry_dt = datetime.strptime(entry_date, "%Y-%m-%d")
        if (datetime.now() - entry_dt).days >= days_held:
            return True, f"보유 {days_held}일 초과 자동 청산"
    except ValueError:
        pass

    # 2. 정치인이 매도 공시
    recent = get_politician_trades(ticker, days=45)
    sells  = [t for t in recent if t["is_sell"]]
    if sells:
        names = list({t["name"] for t in sells})[:2]
        return True, f"정치인 매도 공시: {', '.join(names)}"

    return False, ""
