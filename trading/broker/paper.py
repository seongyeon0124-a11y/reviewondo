"""
페이퍼 트레이딩 브로커.
LONG(장기) / SHORT(단타) 두 포트폴리오를 분리 관리.
"""

import logging
import sqlite3
from datetime import datetime

from trading import config
from trading.data.prices import get_current_price

logger = logging.getLogger(__name__)

PORTFOLIOS = ("LONG", "SHORT")
POS   = "positions"
TRD   = "trade_log"
CASH  = "cash_pool"


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(config.DB_PATH, check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c


def init_db() -> None:
    with _conn() as c:
        c.executescript(f"""
        CREATE TABLE IF NOT EXISTS {POS} (
            ticker      TEXT NOT NULL,
            market      TEXT NOT NULL,
            mode        TEXT NOT NULL DEFAULT 'SHORT',
            shares      REAL NOT NULL,
            avg_cost    REAL NOT NULL,
            entry_date  TEXT NOT NULL,
            PRIMARY KEY (ticker, market, mode)
        );
        CREATE TABLE IF NOT EXISTS {TRD} (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker      TEXT,
            market      TEXT,
            mode        TEXT DEFAULT 'SHORT',
            action      TEXT,
            shares      REAL,
            price       REAL,
            pnl         REAL DEFAULT 0,
            reason      TEXT DEFAULT '',
            timestamp   TEXT
        );
        CREATE TABLE IF NOT EXISTS {CASH} (
            mode   TEXT PRIMARY KEY,
            amount REAL NOT NULL
        );
        """)

        # 초기 자금 삽입 (없는 경우만)
        for mode, ratio in [("LONG", config.LONG_CAPITAL_RATIO), ("SHORT", config.SHORT_CAPITAL_RATIO)]:
            row = c.execute(f"SELECT amount FROM {CASH} WHERE mode=?", (mode,)).fetchone()
            if not row:
                c.execute(f"INSERT INTO {CASH} VALUES (?,?)", (mode, config.INITIAL_CAPITAL * ratio))


# ── 잔고 / 포트폴리오 조회 ────────────────────────────────────

def get_cash(mode: str = "SHORT") -> float:
    with _conn() as c:
        row = c.execute(f"SELECT amount FROM {CASH} WHERE mode=?", (mode,)).fetchone()
        return round(float(row["amount"]), 4) if row else 0.0


def get_positions(mode: str | None = None) -> list[dict]:
    with _conn() as c:
        if mode:
            rows = c.execute(f"SELECT * FROM {POS} WHERE mode=?", (mode,)).fetchall()
        else:
            rows = c.execute(f"SELECT * FROM {POS}").fetchall()
        return [dict(r) for r in rows]


def get_portfolio_value(mode: str | None = None) -> float:
    if mode:
        total = get_cash(mode)
        for pos in get_positions(mode):
            price = get_current_price(pos["ticker"], pos["market"])
            total += pos["shares"] * price
        return round(total, 4)
    return sum(get_portfolio_value(m) for m in PORTFOLIOS)


def get_positions_with_pnl(mode: str | None = None) -> list[dict]:
    result = []
    for pos in get_positions(mode):
        price = get_current_price(pos["ticker"], pos["market"])
        pnl   = (price - pos["avg_cost"]) * pos["shares"]
        pct   = (price / pos["avg_cost"] - 1) * 100 if pos["avg_cost"] > 0 else 0
        result.append({
            **pos,
            "current_price": round(price, 4),
            "value":         round(pos["shares"] * price, 4),
            "pnl":           round(pnl, 4),
            "pnl_pct":       round(pct, 2),
        })
    return result


# ── 매수 / 매도 ───────────────────────────────────────────────

def _cfg(mode: str) -> tuple[float, float, float]:
    if mode == "LONG":
        return config.LONG_MAX_POSITION, config.LONG_STOP_LOSS, config.LONG_TAKE_PROFIT
    return config.SHORT_MAX_POSITION, config.SHORT_STOP_LOSS, config.SHORT_TAKE_PROFIT


def execute_buy(ticker: str, market: str, reason: str = "", mode: str = "SHORT") -> dict:
    price = get_current_price(ticker, market)
    if price <= 0:
        return {"ok": False, "msg": "현재가 조회 실패"}

    max_pos, _, _ = _cfg(mode)
    cash       = get_cash(mode)
    port_value = get_portfolio_value(mode)
    invest     = min(port_value * max_pos, cash * 0.95)

    if invest < price * 0.001:
        return {"ok": False, "msg": f"투자 가능 금액 부족 ({cash:.2f})"}

    shares = invest / price

    with _conn() as c:
        existing = c.execute(
            f"SELECT * FROM {POS} WHERE ticker=? AND market=? AND mode=?",
            (ticker, market, mode),
        ).fetchone()

        if existing:
            total_sh = existing["shares"] + shares
            avg      = (existing["shares"] * existing["avg_cost"] + shares * price) / total_sh
            c.execute(
                f"UPDATE {POS} SET shares=?, avg_cost=? WHERE ticker=? AND market=? AND mode=?",
                (total_sh, avg, ticker, market, mode),
            )
        else:
            c.execute(
                f"INSERT INTO {POS} VALUES (?,?,?,?,?,?)",
                (ticker, market, mode, shares, price, datetime.now().isoformat()),
            )

        c.execute(f"UPDATE {CASH} SET amount=amount-? WHERE mode=?", (shares * price, mode))
        c.execute(
            f"INSERT INTO {TRD} (ticker,market,mode,action,shares,price,pnl,reason,timestamp) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (ticker, market, mode, "BUY", shares, price, 0.0, reason, datetime.now().isoformat()),
        )

    logger.info(f"[{mode}] BUY {ticker}/{market} {shares:.4f}주 @ {price}")
    return {
        "ok": True, "action": "BUY", "ticker": ticker, "market": market,
        "mode": mode, "shares": round(shares, 4), "price": price,
        "invested": round(shares * price, 4),
    }


def execute_sell(ticker: str, market: str, reason: str = "", mode: str = "SHORT") -> dict:
    with _conn() as c:
        pos = c.execute(
            f"SELECT * FROM {POS} WHERE ticker=? AND market=? AND mode=?",
            (ticker, market, mode),
        ).fetchone()
        if not pos:
            pos = c.execute(
                f"SELECT * FROM {POS} WHERE ticker=? AND market=?", (ticker, market)
            ).fetchone()
            if not pos:
                return {"ok": False, "msg": "보유 포지션 없음"}

        price       = get_current_price(ticker, market)
        if price <= 0:
            return {"ok": False, "msg": "현재가 조회 실패"}

        actual_mode = dict(pos).get("mode", mode)
        pnl         = (price - pos["avg_cost"]) * pos["shares"]
        proceeds    = pos["shares"] * price

        c.execute(f"DELETE FROM {POS} WHERE ticker=? AND market=? AND mode=?", (ticker, market, actual_mode))
        c.execute(f"UPDATE {CASH} SET amount=amount+? WHERE mode=?", (proceeds, actual_mode))
        c.execute(
            f"INSERT INTO {TRD} (ticker,market,mode,action,shares,price,pnl,reason,timestamp) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (ticker, market, actual_mode, "SELL", pos["shares"], price, pnl, reason,
             datetime.now().isoformat()),
        )

    logger.info(f"[{actual_mode}] SELL {ticker}/{market} @ {price} PnL={pnl:.4f}")
    return {
        "ok": True, "action": "SELL", "ticker": ticker, "market": market,
        "mode": actual_mode, "price": price, "pnl": round(pnl, 4),
        "proceeds": round(proceeds, 4),
    }


# ── 손절 / 익절 ───────────────────────────────────────────────

def check_sl_tp(mode: str = "SHORT") -> list[dict]:
    _, stop_loss, take_profit = _cfg(mode)
    actions = []
    for pos in get_positions(mode):
        price = get_current_price(pos["ticker"], pos["market"])
        if price <= 0 or pos["avg_cost"] <= 0:
            continue
        pct = (price - pos["avg_cost"]) / pos["avg_cost"]
        if pct <= -stop_loss:
            r = execute_sell(pos["ticker"], pos["market"], f"손절 ({pct:+.1%})", mode)
            actions.append(r)
        elif take_profit > 0 and pct >= take_profit:
            r = execute_sell(pos["ticker"], pos["market"], f"익절 ({pct:+.1%})", mode)
            actions.append(r)
    return actions


# ── 거래 내역 ─────────────────────────────────────────────────

def get_trade_history(limit: int = 100, mode: str | None = None) -> list[dict]:
    with _conn() as c:
        if mode:
            rows = c.execute(
                f"SELECT * FROM {TRD} WHERE mode=? ORDER BY timestamp DESC LIMIT ?",
                (mode, limit),
            ).fetchall()
        else:
            rows = c.execute(
                f"SELECT * FROM {TRD} ORDER BY timestamp DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]


def reset_portfolio(mode: str | None = None) -> None:
    modes  = [mode] if mode else list(PORTFOLIOS)
    ratios = {"LONG": config.LONG_CAPITAL_RATIO, "SHORT": config.SHORT_CAPITAL_RATIO}
    with _conn() as c:
        for m in modes:
            c.execute(f"DELETE FROM {POS} WHERE mode=?", (m,))
            c.execute(f"DELETE FROM {TRD} WHERE mode=?", (m,))
            c.execute(
                f"UPDATE {CASH} SET amount=? WHERE mode=?",
                (config.INITIAL_CAPITAL * ratios[m], m),
            )
    logger.info(f"포트폴리오 초기화: {modes}")
