"""
페이퍼 트레이딩 브로커.
SQLite에 포트폴리오·거래 내역·잔고를 저장한다.
실계좌 연동 전 전략 검증용.
"""

import logging
import sqlite3
from datetime import datetime

from trading import config
from trading.data.prices import get_current_price

logger = logging.getLogger(__name__)


# ── DB 헬퍼 ──────────────────────────────────────────────────

def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(config.DB_PATH, check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c


def init_db() -> None:
    with _conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS portfolio (
            ticker      TEXT NOT NULL,
            market      TEXT NOT NULL,
            shares      REAL NOT NULL,
            avg_cost    REAL NOT NULL,
            entry_date  TEXT NOT NULL,
            PRIMARY KEY (ticker, market)
        );
        CREATE TABLE IF NOT EXISTS trades (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker      TEXT,
            market      TEXT,
            action      TEXT,
            shares      REAL,
            price       REAL,
            pnl         REAL DEFAULT 0,
            reason      TEXT DEFAULT '',
            timestamp   TEXT
        );
        CREATE TABLE IF NOT EXISTS cash (
            id     INTEGER PRIMARY KEY,
            amount REAL NOT NULL
        );
        """)
        row = c.execute("SELECT amount FROM cash WHERE id=1").fetchone()
        if not row:
            c.execute("INSERT INTO cash VALUES (1, ?)", (config.INITIAL_CAPITAL,))


# ── 잔고 / 포트폴리오 조회 ────────────────────────────────────

def get_cash() -> float:
    with _conn() as c:
        row = c.execute("SELECT amount FROM cash WHERE id=1").fetchone()
        return round(float(row["amount"]), 4) if row else 0.0


def get_positions() -> list[dict]:
    with _conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM portfolio").fetchall()]


def get_portfolio_value() -> float:
    """현금 + 보유 주식 평가액"""
    total = get_cash()
    for pos in get_positions():
        price = get_current_price(pos["ticker"], pos["market"])
        total += pos["shares"] * price
    return round(total, 4)


def get_positions_with_pnl() -> list[dict]:
    result = []
    for pos in get_positions():
        price = get_current_price(pos["ticker"], pos["market"])
        pnl = (price - pos["avg_cost"]) * pos["shares"]
        pct = (price / pos["avg_cost"] - 1) * 100 if pos["avg_cost"] > 0 else 0
        result.append({
            **pos,
            "current_price": round(price, 4),
            "value": round(pos["shares"] * price, 4),
            "pnl": round(pnl, 4),
            "pnl_pct": round(pct, 2),
        })
    return result


# ── 매수 / 매도 ───────────────────────────────────────────────

def execute_buy(ticker: str, market: str, reason: str = "") -> dict:
    price = get_current_price(ticker, market)
    if price <= 0:
        return {"ok": False, "msg": "현재가 조회 실패"}

    cash = get_cash()
    total_value = get_portfolio_value()
    invest = min(total_value * config.MAX_POSITION_SIZE, cash * 0.95)

    if invest < price * 0.001:  # 너무 소액이면 skip
        return {"ok": False, "msg": f"투자 가능 금액 부족 (가용 {cash:.2f})"}

    shares = invest / price

    with _conn() as c:
        existing = c.execute(
            "SELECT * FROM portfolio WHERE ticker=? AND market=?", (ticker, market)
        ).fetchone()

        if existing:
            total_sh = existing["shares"] + shares
            avg = (existing["shares"] * existing["avg_cost"] + shares * price) / total_sh
            c.execute(
                "UPDATE portfolio SET shares=?, avg_cost=? WHERE ticker=? AND market=?",
                (total_sh, avg, ticker, market),
            )
        else:
            c.execute(
                "INSERT INTO portfolio VALUES (?,?,?,?,?)",
                (ticker, market, shares, price, datetime.now().isoformat()),
            )

        c.execute("UPDATE cash SET amount=amount-? WHERE id=1", (shares * price,))
        c.execute(
            "INSERT INTO trades (ticker,market,action,shares,price,pnl,reason,timestamp) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (ticker, market, "BUY", shares, price, 0.0, reason, datetime.now().isoformat()),
        )

    logger.info(f"BUY {ticker}/{market} {shares:.4f}주 @ {price} ({reason})")
    return {
        "ok": True, "action": "BUY", "ticker": ticker, "market": market,
        "shares": round(shares, 4), "price": price,
        "invested": round(shares * price, 4),
    }


def execute_sell(ticker: str, market: str, reason: str = "") -> dict:
    with _conn() as c:
        pos = c.execute(
            "SELECT * FROM portfolio WHERE ticker=? AND market=?", (ticker, market)
        ).fetchone()
        if not pos:
            return {"ok": False, "msg": "보유 포지션 없음"}

        price = get_current_price(ticker, market)
        if price <= 0:
            return {"ok": False, "msg": "현재가 조회 실패"}

        pnl = (price - pos["avg_cost"]) * pos["shares"]
        proceeds = pos["shares"] * price

        c.execute("DELETE FROM portfolio WHERE ticker=? AND market=?", (ticker, market))
        c.execute("UPDATE cash SET amount=amount+? WHERE id=1", (proceeds,))
        c.execute(
            "INSERT INTO trades (ticker,market,action,shares,price,pnl,reason,timestamp) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (ticker, market, "SELL", pos["shares"], price, pnl, reason, datetime.now().isoformat()),
        )

    logger.info(f"SELL {ticker}/{market} @ {price} PnL={pnl:.4f} ({reason})")
    return {
        "ok": True, "action": "SELL", "ticker": ticker, "market": market,
        "price": price, "pnl": round(pnl, 4),
        "proceeds": round(proceeds, 4),
    }


# ── 손절 / 익절 자동 처리 ─────────────────────────────────────

def check_sl_tp() -> list[dict]:
    """모든 포지션 손절·익절 조건 체크 후 자동 매도"""
    actions = []
    for pos in get_positions():
        price = get_current_price(pos["ticker"], pos["market"])
        if price <= 0 or pos["avg_cost"] <= 0:
            continue
        pct = (price - pos["avg_cost"]) / pos["avg_cost"]
        if pct <= -config.STOP_LOSS_PCT:
            r = execute_sell(pos["ticker"], pos["market"], reason=f"손절 ({pct:+.1%})")
            actions.append(r)
        elif pct >= config.TAKE_PROFIT_PCT:
            r = execute_sell(pos["ticker"], pos["market"], reason=f"익절 ({pct:+.1%})")
            actions.append(r)
    return actions


# ── 거래 내역 ─────────────────────────────────────────────────

def get_trade_history(limit: int = 100) -> list[dict]:
    with _conn() as c:
        return [
            dict(r) for r in c.execute(
                "SELECT * FROM trades ORDER BY timestamp DESC LIMIT ?", (limit,)
            ).fetchall()
        ]


def reset_portfolio() -> None:
    """포트폴리오 초기화 (테스트용)"""
    with _conn() as c:
        c.execute("DELETE FROM portfolio")
        c.execute("DELETE FROM trades")
        c.execute("UPDATE cash SET amount=? WHERE id=1", (config.INITIAL_CAPITAL,))
    logger.info(f"포트폴리오 초기화 완료 (자본금 {config.INITIAL_CAPITAL})")
