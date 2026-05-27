"""
한국투자증권 Open API 브로커 (한국 주식).

환경변수:
  KIS_APP_KEY      — 앱 키
  KIS_APP_SECRET   — 앱 시크릿
  KIS_ACCOUNT_NO   — 계좌번호 (8자리-2자리, 예: 12345678-01)
  KIS_MOCK         — "true" → 모의투자 엔드포인트 (기본값)

신청: https://apiportal.koreainvestment.com
모의투자 BASE: https://openapivts.koreainvestment.com:29443
실투자  BASE: https://openapi.koreainvestment.com:9443

TR ID (모의):  VTTC0802U (매수), VTTC0801U (매도)
TR ID (실거래): TTTC0802U (매수), TTTC0801U (매도)
"""

import logging
import os
import time

import requests

logger = logging.getLogger(__name__)

_APP_KEY    = os.getenv("KIS_APP_KEY", "")
_APP_SECRET = os.getenv("KIS_APP_SECRET", "")
_ACCOUNT    = os.getenv("KIS_ACCOUNT_NO", "")   # "12345678-01" 형식
_MOCK       = os.getenv("KIS_MOCK", "true").lower() != "false"

_BASE = (
    "https://openapivts.koreainvestment.com:29443"
    if _MOCK else
    "https://openapi.koreainvestment.com:9443"
)

# 토큰 캐시
_token_cache: dict = {}
_TOKEN_TTL = 21600  # 6시간


def is_configured() -> bool:
    return bool(_APP_KEY and _APP_SECRET and _ACCOUNT)


def _get_token() -> str:
    """OAuth2 접근 토큰 발급 (캐시)."""
    now = time.time()
    if _token_cache.get("token") and now - _token_cache.get("ts", 0) < _TOKEN_TTL:
        return _token_cache["token"]

    url = f"{_BASE}/oauth2/tokenP"
    try:
        r = requests.post(
            url,
            json={
                "grant_type":   "client_credentials",
                "appkey":       _APP_KEY,
                "appsecret":    _APP_SECRET,
            },
            timeout=15,
        )
        r.raise_for_status()
        token = r.json().get("access_token", "")
        _token_cache["token"] = token
        _token_cache["ts"]    = now
        logger.info("[KIS] 토큰 발급 성공")
        return token
    except Exception as e:
        logger.error(f"[KIS] 토큰 발급 실패: {e}")
        return ""


def _headers(tr_id: str) -> dict:
    token = _get_token()
    acc_parts  = _ACCOUNT.split("-")
    acc_no     = acc_parts[0] if acc_parts else _ACCOUNT
    prod_code  = acc_parts[1] if len(acc_parts) > 1 else "01"
    return {
        "content-type":  "application/json; charset=utf-8",
        "authorization": f"Bearer {token}",
        "appkey":        _APP_KEY,
        "appsecret":     _APP_SECRET,
        "tr_id":         tr_id,
        "custtype":      "P",    # 개인
    }


def get_account() -> dict:
    """잔고 조회."""
    if not is_configured():
        return {"error": "KIS_APP_KEY / KIS_APP_SECRET / KIS_ACCOUNT_NO 미설정"}
    acc_parts  = _ACCOUNT.split("-")
    acc_no     = acc_parts[0] if acc_parts else _ACCOUNT
    prod_code  = acc_parts[1] if len(acc_parts) > 1 else "01"
    # 모의: VTTC8434R / 실거래: TTTC8434R
    tr_id = "VTTC8434R" if _MOCK else "TTTC8434R"
    try:
        r = requests.get(
            f"{_BASE}/uapi/domestic-stock/v1/trading/inquire-balance",
            headers=_headers(tr_id),
            params={
                "CANO":         acc_no,
                "ACNT_PRDT_CD": prod_code,
                "AFHR_FLPR_YN": "N",
                "OFL_YN":       "",
                "INQR_DVSN":    "02",
                "UNPR_DVSN":    "01",
                "FUND_STTL_ICLD_YN": "N",
                "FNCG_AMT_AUTO_RDPT_YN": "N",
                "PRCS_DVSN":    "01",
                "CTX_AREA_FK100": "",
                "CTX_AREA_NK100": "",
            },
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()
        output2 = data.get("output2", [{}])
        summary = output2[0] if output2 else {}
        return {
            "cash":          float(summary.get("dnca_tot_amt", 0)),
            "total_eval":    float(summary.get("tot_evlu_amt", 0)),
            "buy_power":     float(summary.get("prvs_rcdl_excc_amt", 0)),
            "mock":          _MOCK,
        }
    except Exception as e:
        logger.error(f"[KIS] 잔고 조회 실패: {e}")
        return {"error": str(e)}


def get_positions() -> list[dict]:
    """보유 종목 조회."""
    if not is_configured():
        return []
    acc_parts  = _ACCOUNT.split("-")
    acc_no     = acc_parts[0] if acc_parts else _ACCOUNT
    prod_code  = acc_parts[1] if len(acc_parts) > 1 else "01"
    tr_id = "VTTC8434R" if _MOCK else "TTTC8434R"
    try:
        r = requests.get(
            f"{_BASE}/uapi/domestic-stock/v1/trading/inquire-balance",
            headers=_headers(tr_id),
            params={
                "CANO":         acc_no,
                "ACNT_PRDT_CD": prod_code,
                "AFHR_FLPR_YN": "N",
                "OFL_YN":       "",
                "INQR_DVSN":    "02",
                "UNPR_DVSN":    "01",
                "FUND_STTL_ICLD_YN": "N",
                "FNCG_AMT_AUTO_RDPT_YN": "N",
                "PRCS_DVSN":    "01",
                "CTX_AREA_FK100": "",
                "CTX_AREA_NK100": "",
            },
            timeout=15,
        )
        r.raise_for_status()
        output1 = r.json().get("output1", [])
        result  = []
        for p in output1:
            qty = float(p.get("hldg_qty", 0))
            if qty <= 0:
                continue
            avg  = float(p.get("pchs_avg_pric", 0))
            cur  = float(p.get("prpr", 0))
            pnl  = (cur - avg) * qty
            result.append({
                "ticker":        p.get("pdno", ""),
                "market":        "KR",
                "shares":        qty,
                "avg_cost":      avg,
                "current_price": cur,
                "pnl":           round(pnl, 0),
                "pnl_pct":       round((cur / avg - 1) * 100, 2) if avg > 0 else 0,
                "name":          p.get("prdt_name", ""),
            })
        return result
    except Exception as e:
        logger.error(f"[KIS] 포지션 조회 실패: {e}")
        return []


def place_order(
    ticker: str,
    side: str,       # "buy" | "sell"
    qty: int,
    price: int = 0,  # 0 = 시장가
) -> dict:
    """
    주식 주문.
    price=0 이면 시장가(시장가주문), 아니면 지정가.
    """
    if not is_configured():
        return {"ok": False, "msg": "KIS 키 미설정"}

    acc_parts  = _ACCOUNT.split("-")
    acc_no     = acc_parts[0] if acc_parts else _ACCOUNT
    prod_code  = acc_parts[1] if len(acc_parts) > 1 else "01"

    if _MOCK:
        tr_id = "VTTC0802U" if side == "buy" else "VTTC0801U"
    else:
        tr_id = "TTTC0802U" if side == "buy" else "TTTC0801U"

    ord_dvsn = "01" if price == 0 else "00"  # 01=시장가, 00=지정가
    body = {
        "CANO":         acc_no,
        "ACNT_PRDT_CD": prod_code,
        "PDNO":         ticker,
        "ORD_DVSN":     ord_dvsn,
        "ORD_QTY":      str(qty),
        "ORD_UNPR":     str(price),
    }

    try:
        r = requests.post(
            f"{_BASE}/uapi/domestic-stock/v1/trading/order-cash",
            headers=_headers(tr_id),
            json=body,
            timeout=15,
        )
        if r.status_code not in (200, 201):
            msg = r.json().get("msg1", r.text)
            logger.error(f"[KIS] 주문 실패 {ticker}: {msg}")
            return {"ok": False, "msg": msg}
        data   = r.json()
        output = data.get("output", {})
        logger.info(f"[KIS] {side.upper()} {ticker} {qty}주 주문번호={output.get('ODNO','')}")
        return {
            "ok":       True,
            "order_id": output.get("ODNO", ""),
            "ticker":   ticker,
            "side":     side,
            "qty":      qty,
            "mock":     _MOCK,
        }
    except Exception as e:
        logger.error(f"[KIS] 주문 오류 {ticker}: {e}")
        return {"ok": False, "msg": str(e)}


def get_current_price(ticker: str) -> float:
    """KIS에서 현재가 조회."""
    if not is_configured():
        return 0.0
    try:
        r = requests.get(
            f"{_BASE}/uapi/domestic-stock/v1/quotations/inquire-price",
            headers=_headers("FHKST01010100"),
            params={"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": ticker},
            timeout=10,
        )
        r.raise_for_status()
        output = r.json().get("output", {})
        return float(output.get("stck_prpr", 0))
    except Exception as e:
        logger.warning(f"[KIS] 현재가 조회 실패 {ticker}: {e}")
        return 0.0
