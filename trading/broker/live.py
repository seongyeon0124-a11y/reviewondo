"""
실계좌 매매 디스패처.

LIVE_MODE=true 환경변수가 설정된 경우에만 실제 주문 가능.
US → Alpaca, KR → KIS API 로 라우팅.

환경변수:
  LIVE_MODE    — "true" 일 때만 실거래 주문 허용 (기본 false)
"""

import logging
import os

from trading.broker import alpaca, kis

logger = logging.getLogger(__name__)

_LIVE_MODE = os.getenv("LIVE_MODE", "false").lower() == "true"


def is_live_enabled() -> bool:
    return _LIVE_MODE


def get_status() -> dict:
    """실계좌 연동 상태 요약."""
    return {
        "live_mode":        _LIVE_MODE,
        "alpaca_configured": alpaca.is_configured(),
        "alpaca_paper":     alpaca._PAPER,
        "kis_configured":   kis.is_configured(),
        "kis_mock":         kis._MOCK,
    }


def get_live_account(market: str = "US") -> dict:
    if market == "US":
        return alpaca.get_account()
    return kis.get_account()


def get_live_positions(market: str | None = None) -> list[dict]:
    result = []
    if market in (None, "US"):
        result.extend(alpaca.get_positions())
    if market in (None, "KR"):
        result.extend(kis.get_positions())
    return result


def execute_live_buy(
    ticker: str,
    market: str,
    amount_usd: float | None = None,
    qty: int | None = None,
) -> dict:
    """
    실계좌 매수.
    US: Alpaca notional(금액) 주문
    KR: KIS 수량 주문 (qty 필수, 또는 amount + 현재가로 수량 계산)
    """
    if not _LIVE_MODE:
        return {"ok": False, "msg": "LIVE_MODE=false — 실거래 비활성화 상태"}

    if market == "US":
        if not alpaca.is_configured():
            return {"ok": False, "msg": "Alpaca 키 미설정"}
        if amount_usd is None and qty is None:
            return {"ok": False, "msg": "amount_usd 또는 qty 필요"}
        return alpaca.place_order(ticker, "buy", notional=amount_usd, qty=qty)

    # KR
    if not kis.is_configured():
        return {"ok": False, "msg": "KIS 키 미설정"}
    if qty is None:
        if amount_usd:
            price = kis.get_current_price(ticker)
            qty   = max(1, int(amount_usd / price)) if price > 0 else 1
        else:
            return {"ok": False, "msg": "qty 필요"}
    return kis.place_order(ticker, "buy", qty=qty)


def execute_live_sell(
    ticker: str,
    market: str,
    qty: float | None = None,
) -> dict:
    """
    실계좌 매도.
    US: Alpaca — qty가 None이면 전량 매도
    KR: KIS   — qty 필요
    """
    if not _LIVE_MODE:
        return {"ok": False, "msg": "LIVE_MODE=false — 실거래 비활성화 상태"}

    if market == "US":
        if not alpaca.is_configured():
            return {"ok": False, "msg": "Alpaca 키 미설정"}
        if qty is None:
            # 전량 매도: Alpaca DELETE /v2/positions/{ticker}
            import requests
            try:
                r = requests.delete(
                    f"{alpaca._BASE}/v2/positions/{ticker.upper()}",
                    headers=alpaca._headers(),
                    timeout=10,
                )
                if r.status_code in (200, 204):
                    logger.info(f"[Alpaca] 전량 매도 {ticker}")
                    return {"ok": True, "ticker": ticker, "side": "sell", "note": "전량"}
                return {"ok": False, "msg": r.json().get("message", r.text)}
            except Exception as e:
                return {"ok": False, "msg": str(e)}
        return alpaca.place_order(ticker, "sell", qty=qty)

    # KR
    if not kis.is_configured():
        return {"ok": False, "msg": "KIS 키 미설정"}
    if qty is None:
        positions = kis.get_positions()
        pos = next((p for p in positions if p["ticker"] == ticker), None)
        if not pos:
            return {"ok": False, "msg": "보유 포지션 없음"}
        qty = int(pos["shares"])
    return kis.place_order(ticker, "sell", qty=int(qty))
