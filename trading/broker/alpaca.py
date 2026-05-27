"""
Alpaca Markets 브로커 (미국 주식).

환경변수:
  ALPACA_API_KEY      — Alpaca API Key ID
  ALPACA_SECRET_KEY   — Alpaca Secret Key
  ALPACA_PAPER        — "true" → 페이퍼 트레이딩 엔드포인트 (기본값)

무료 가입: https://alpaca.markets
Paper: https://paper-api.alpaca.markets
Live:  https://api.alpaca.markets
"""

import logging
import os

import requests

logger = logging.getLogger(__name__)

_KEY    = os.getenv("ALPACA_API_KEY", "")
_SECRET = os.getenv("ALPACA_SECRET_KEY", "")
_PAPER  = os.getenv("ALPACA_PAPER", "true").lower() != "false"

_BASE = (
    "https://paper-api.alpaca.markets"
    if _PAPER else
    "https://api.alpaca.markets"
)


def _headers() -> dict:
    return {
        "APCA-API-KEY-ID":     _KEY,
        "APCA-API-SECRET-KEY": _SECRET,
        "Content-Type":        "application/json",
    }


def is_configured() -> bool:
    return bool(_KEY and _SECRET)


def get_account() -> dict:
    """계좌 정보 반환 (잔고, 구매력 등)."""
    if not is_configured():
        return {"error": "ALPACA_API_KEY / ALPACA_SECRET_KEY 미설정"}
    try:
        r = requests.get(f"{_BASE}/v2/account", headers=_headers(), timeout=10)
        r.raise_for_status()
        d = r.json()
        return {
            "cash":         float(d.get("cash", 0)),
            "buying_power": float(d.get("buying_power", 0)),
            "portfolio_value": float(d.get("portfolio_value", 0)),
            "equity":       float(d.get("equity", 0)),
            "paper":        _PAPER,
            "status":       d.get("status", ""),
        }
    except Exception as e:
        logger.error(f"[Alpaca] 계좌 조회 실패: {e}")
        return {"error": str(e)}


def get_positions() -> list[dict]:
    """보유 포지션 목록."""
    if not is_configured():
        return []
    try:
        r = requests.get(f"{_BASE}/v2/positions", headers=_headers(), timeout=10)
        r.raise_for_status()
        return [
            {
                "ticker":       p["symbol"],
                "market":       "US",
                "shares":       float(p["qty"]),
                "avg_cost":     float(p["avg_entry_price"]),
                "current_price": float(p["current_price"]),
                "pnl":          float(p["unrealized_pl"]),
                "pnl_pct":      round(float(p["unrealized_plpc"]) * 100, 2),
            }
            for p in r.json()
        ]
    except Exception as e:
        logger.error(f"[Alpaca] 포지션 조회 실패: {e}")
        return []


def place_order(
    ticker: str,
    side: str,       # "buy" | "sell"
    notional: float | None = None,  # 금액 기준 (USD)
    qty: float | None = None,        # 수량 기준
    order_type: str = "market",
    time_in_force: str = "day",
) -> dict:
    """
    주문 제출.
    notional(금액) 또는 qty(수량) 중 하나 필요.
    분할주 거래 가능 (notional 사용 시).
    """
    if not is_configured():
        return {"ok": False, "msg": "Alpaca 키 미설정"}

    payload: dict = {
        "symbol":        ticker.upper(),
        "side":          side,
        "type":          order_type,
        "time_in_force": time_in_force,
    }
    if notional is not None:
        payload["notional"] = str(round(notional, 2))
    elif qty is not None:
        payload["qty"] = str(qty)
    else:
        return {"ok": False, "msg": "notional 또는 qty 필요"}

    try:
        r = requests.post(
            f"{_BASE}/v2/orders",
            headers=_headers(),
            json=payload,
            timeout=15,
        )
        if r.status_code not in (200, 201):
            body = r.json()
            msg = body.get("message", r.text)
            logger.error(f"[Alpaca] 주문 실패 {ticker}: {msg}")
            return {"ok": False, "msg": msg}
        data = r.json()
        logger.info(f"[Alpaca] {side.upper()} {ticker} id={data['id']}")
        return {
            "ok":       True,
            "order_id": data["id"],
            "ticker":   ticker,
            "side":     side,
            "status":   data.get("status", ""),
            "paper":    _PAPER,
        }
    except Exception as e:
        logger.error(f"[Alpaca] 주문 오류 {ticker}: {e}")
        return {"ok": False, "msg": str(e)}


def cancel_all_orders() -> bool:
    """미체결 주문 전부 취소."""
    if not is_configured():
        return False
    try:
        r = requests.delete(f"{_BASE}/v2/orders", headers=_headers(), timeout=10)
        return r.status_code in (200, 207)
    except Exception:
        return False


def get_orders(status: str = "open", limit: int = 50) -> list[dict]:
    """주문 목록 조회."""
    if not is_configured():
        return []
    try:
        r = requests.get(
            f"{_BASE}/v2/orders",
            headers=_headers(),
            params={"status": status, "limit": limit},
            timeout=10,
        )
        r.raise_for_status()
        return [
            {
                "order_id": o["id"],
                "ticker":   o["symbol"],
                "side":     o["side"],
                "qty":      o.get("qty"),
                "notional": o.get("notional"),
                "status":   o["status"],
                "filled_qty": o.get("filled_qty"),
                "filled_avg_price": o.get("filled_avg_price"),
                "created_at": str(o.get("created_at", ""))[:16],
            }
            for o in r.json()
        ]
    except Exception as e:
        logger.error(f"[Alpaca] 주문 조회 실패: {e}")
        return []
