"""
트레이딩 사이클 실행기.

LONG (장기): 월 1회 체크, 손절 없는 추세 추종
SHORT (단타): 주 1회 체크, 타이트한 손절/익절
"""

import logging

from trading.broker.paper import (
    check_sl_tp, execute_buy, execute_sell, get_positions, init_db,
)
from trading.strategy.pol_strategy import get_pol_buy_candidates, get_pol_sell_signal
from trading.strategy.signals import scan_all
from trading import config

logger = logging.getLogger(__name__)


def run_cycle(mode: str = "SHORT") -> dict:
    """
    1회 트레이딩 사이클.
    mode: 'SHORT' (단타, 주 1회) | 'LONG' (장기, 월 1회)
    """
    init_db()

    sl_tp_actions = check_sl_tp(mode)
    if sl_tp_actions:
        logger.info(f"[{mode}] SL/TP {len(sl_tp_actions)}건")

    signals  = scan_all(mode)
    executed = []

    for sig in signals:
        ticker = sig["ticker"]
        market = sig["market"]
        action = sig["action"]
        score  = sig["score"]
        reason = (
            f"신호 {score:+.3f} "
            f"(정치인{sig['breakdown']['politician']:+.3f} "
            f"뉴스{sig['breakdown']['news']:+.3f} "
            f"기술{sig['breakdown']['technical']:+.3f})"
        )

        if action == "BUY":
            r = execute_buy(ticker, market, reason=reason, mode=mode)
            if r["ok"]:
                executed.append({**r, "score": score})
        elif action == "SELL":
            r = execute_sell(ticker, market, reason=reason, mode=mode)
            if r["ok"]:
                executed.append({**r, "score": score})

    return {"mode": mode, "sl_tp": sl_tp_actions, "signals": signals, "executed": executed}


def run_pol_cycle() -> dict:
    """
    정치인 카피트레이딩 사이클.
    1. 보유 포지션 청산 조건 체크 (90일 초과 / 정치인 매도 공시 / 손절)
    2. 최신 정치인 매수 공시 스캔 → 따라 매수
    """
    init_db()
    executed = []
    sold     = []

    # ── 1. 기존 POL 포지션 청산 체크 ──
    # 손절 자동 처리
    sl_actions = check_sl_tp("POL")
    sold.extend(sl_actions)

    # 보유 기간 / 정치인 매도 공시 체크
    for pos in get_positions("POL"):
        should_sell, reason = get_pol_sell_signal(
            pos["ticker"], pos["entry_date"], config.POL_HOLD_DAYS
        )
        if should_sell:
            r = execute_sell(pos["ticker"], "US", reason=reason, mode="POL")
            if r["ok"]:
                sold.append(r)

    # ── 2. 최신 매수 후보 스캔 ──
    candidates = get_pol_buy_candidates(days=config.POL_SCAN_DAYS)
    current_tickers = {p["ticker"] for p in get_positions("POL")}

    for c in candidates:
        if c["ticker"] in current_tickers:
            continue
        if c["confidence"] < 0.3:   # 신뢰도 낮으면 스킵
            continue
        names   = ", ".join(p["name"] for p in c["politicians"][:2])
        reason  = f"정치인 매수 따라하기 ({names}) 신뢰도 {c['confidence']:.0%}"
        r = execute_buy(c["ticker"], "US", reason=reason, mode="POL")
        if r["ok"]:
            executed.append({**r, "politicians": c["politicians"]})
            current_tickers.add(c["ticker"])

    logger.info(f"[POL] 매수 {len(executed)}건, 매도 {len(sold)}건")
    return {
        "mode":      "POL",
        "executed":  executed,
        "sold":      sold,
        "candidates": candidates,
    }


def run_all_cycles() -> dict:
    """장기 + 단타 + 정치인 동시 실행"""
    return {
        "LONG":  run_cycle("LONG"),
        "SHORT": run_cycle("SHORT"),
        "POL":   run_pol_cycle(),
    }
