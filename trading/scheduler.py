"""
트레이딩 사이클 실행기.

LONG (장기): 월 1회 체크, 손절 없는 추세 추종
SHORT (단타): 주 1회 체크, 타이트한 손절/익절
"""

import logging

from trading.broker.paper import check_sl_tp, execute_buy, execute_sell, init_db
from trading.strategy.signals import scan_all

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


def run_all_cycles() -> dict:
    """장기 + 단타 동시 실행"""
    return {
        "LONG":  run_cycle("LONG"),
        "SHORT": run_cycle("SHORT"),
    }
