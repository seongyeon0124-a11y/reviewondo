"""
트레이딩 사이클 실행기.
한 번 호출하면: SL/TP 체크 → 신호 스캔 → 매수/매도 실행.
APScheduler나 cron으로 주기적으로 호출하거나,
대시보드에서 수동으로 실행할 수 있다.
"""

import logging

from trading.broker.paper import check_sl_tp, execute_buy, execute_sell, init_db
from trading.strategy.signals import scan_all

logger = logging.getLogger(__name__)


def run_cycle() -> dict:
    """
    1회 트레이딩 사이클 실행.
    반환:
      {
        "sl_tp": [실행된 손절/익절 거래],
        "signals": [전체 신호 목록],
        "executed": [신호 기반 실행 거래],
      }
    """
    init_db()

    # 1. 손절 / 익절 체크
    sl_tp_actions = check_sl_tp()
    if sl_tp_actions:
        logger.info(f"SL/TP 실행: {len(sl_tp_actions)}건")

    # 2. 전체 종목 신호 스캔
    signals = scan_all()
    executed = []

    for sig in signals:
        ticker = sig["ticker"]
        market = sig["market"]
        action = sig["action"]
        score = sig["score"]
        reason = (
            f"신호 {score:+.3f} "
            f"(정치인{sig['breakdown']['politician']:+.3f} "
            f"뉴스{sig['breakdown']['news']:+.3f} "
            f"기술{sig['breakdown']['technical']:+.3f})"
        )

        if action == "BUY":
            r = execute_buy(ticker, market, reason=reason)
            if r["ok"]:
                executed.append({**r, "score": score})
        elif action == "SELL":
            r = execute_sell(ticker, market, reason=reason)
            if r["ok"]:
                executed.append({**r, "score": score})

    return {"sl_tp": sl_tp_actions, "signals": signals, "executed": executed}
