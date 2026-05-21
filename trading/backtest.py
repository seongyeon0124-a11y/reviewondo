"""
백테스트 엔진.

방식: 워크포워드(walk-forward) — 각 시뮬레이션 날짜 기준으로
      그 이전 데이터만 사용해 신호를 계산하므로 미래 정보 누출이 없다.

신호 체크 주기: 기본 매주 금요일 (W-FRI)
거래 체결가: 신호 발생 당일 종가 (다음 거래일 시가 근사)
수수료: 0.1% (왕복 0.2%)
"""

import logging
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from trading import config
from trading.data.politician import get_politician_trades
from trading.data.prices import get_price_history
from trading.strategy.technical import get_technical_signal

logger = logging.getLogger(__name__)

COMMISSION = 0.001  # 편도 0.1%


# ── 헬퍼 ──────────────────────────────────────────────────────

def _pol_signal_as_of(pol_trades: list, as_of: datetime) -> float:
    """as_of 날짜 기준 과거 90일 정치인 거래 신호"""
    cutoff = as_of - timedelta(days=90)
    relevant = [
        t for t in pol_trades
        if cutoff <= datetime.strptime(t["date"], "%Y-%m-%d") <= as_of
    ]
    if not relevant:
        return 0.0
    buys = sum(1 for t in relevant if t["is_buy"])
    sells = sum(1 for t in relevant if t["is_sell"])
    total = buys + sells
    if total == 0:
        return 0.0
    confidence = min(1.0, total / 5)
    return round(((buys - sells) / total) * 0.4 * confidence, 3)


def _price_on(df: pd.DataFrame, date) -> float:
    """date 당일 또는 가장 가까운 과거 종가"""
    sub = df[df.index.normalize() <= pd.Timestamp(date)]
    if sub.empty:
        return 0.0
    return float(sub["Close"].squeeze().iloc[-1])


# ── 메인 백테스트 ─────────────────────────────────────────────

def run_backtest(
    tickers_markets: list[tuple[str, str]] | None = None,
    period_days: int = 365,
    initial_capital: float = 100.0,
    freq: str = "W-FRI",
    use_politician: bool = True,
) -> dict:
    """
    백테스트 실행 후 성과 지표 딕셔너리 반환.

    tickers_markets: [("AAPL", "US"), ...] 형태. None이면 config 감시 목록 사용.
    period_days: 백테스트 기간 (일)
    freq: 신호 체크 주기 ("W-FRI"=매주, "ME"=매월말)
    """
    if tickers_markets is None:
        tickers_markets = [(t.strip(), "US") for t in config.WATCHLIST_US]

    logger.info(f"백테스트 시작: {len(tickers_markets)}개 종목, {period_days}일")

    # ── 1. 데이터 수집 ─────────────────────────────────────
    price_data: dict[tuple, pd.DataFrame] = {}
    pol_cache: dict[str, list] = {}

    for ticker, market in tickers_markets:
        df = get_price_history(ticker, market, days=period_days + 120)
        if df.empty:
            logger.warning(f"가격 데이터 없음: {ticker}/{market}")
            continue
        # Close 컬럼 정규화
        if isinstance(df.columns, pd.MultiIndex):
            df = df.droplevel(1, axis=1)
        df.index = pd.to_datetime(df.index).normalize()
        price_data[(ticker, market)] = df

        if use_politician and market == "US":
            pol_cache[ticker] = get_politician_trades(ticker, days=period_days + 90)

    if not price_data:
        return {"error": "가격 데이터 없음 (인터넷 연결 확인)"}

    # ── 2. 시뮬레이션 날짜 범위 ────────────────────────────
    end_date = datetime.now()
    start_date = end_date - timedelta(days=period_days)
    check_dates = pd.date_range(start=start_date, end=end_date, freq=freq)

    # ── 3. 포트폴리오 초기화 ───────────────────────────────
    cash = initial_capital
    positions: dict[tuple, dict] = {}  # (ticker,market) → {shares, avg_cost}
    equity_curve: list[dict] = []
    trades: list[dict] = []

    # ── 4. 워크포워드 루프 ─────────────────────────────────
    for ts in check_dates:
        check_dt = ts.to_pydatetime()

        # 포트폴리오 시가 평가
        port_value = cash
        for key, pos in positions.items():
            tk, mkt = key
            df = price_data.get(key)
            if df is None:
                continue
            px = _price_on(df, check_dt)
            if px > 0:
                port_value += pos["shares"] * px

        equity_curve.append({"date": check_dt.strftime("%Y-%m-%d"), "value": round(port_value, 4)})

        # 종목별 신호 처리
        for key, df in price_data.items():
            ticker, market = key
            hist = df[df.index.normalize() <= pd.Timestamp(check_dt)]
            if len(hist) < 30:
                continue

            tech = get_technical_signal(hist)
            pol = _pol_signal_as_of(pol_cache.get(ticker, []), check_dt) if use_politician else 0.0
            score = round(pol + tech, 3)

            px = _price_on(hist, check_dt)
            if px <= 0:
                continue

            holding = key in positions

            # ── 손절 / 익절 ──
            if holding:
                pos = positions[key]
                pct = (px - pos["avg_cost"]) / pos["avg_cost"]
                if pct <= -config.STOP_LOSS_PCT or pct >= config.TAKE_PROFIT_PCT:
                    sell_px = px * (1 - COMMISSION)
                    pnl = (sell_px - pos["avg_cost"]) * pos["shares"]
                    cash += pos["shares"] * sell_px
                    reason = f"손절 {pct:+.1%}" if pct < 0 else f"익절 {pct:+.1%}"
                    trades.append({
                        "date": check_dt.strftime("%Y-%m-%d"),
                        "ticker": ticker, "market": market,
                        "action": "SELL", "price": round(sell_px, 4),
                        "pnl": round(pnl, 4), "reason": reason, "score": score,
                    })
                    del positions[key]
                    continue

            # ── 신호 매수 ──
            if score >= config.BUY_THRESHOLD and not holding:
                invest = min(port_value * config.MAX_POSITION_SIZE, cash * 0.95)
                buy_px = px * (1 + COMMISSION)
                if invest >= buy_px:
                    shares = invest / buy_px
                    cash -= shares * buy_px
                    positions[key] = {"shares": shares, "avg_cost": buy_px}
                    trades.append({
                        "date": check_dt.strftime("%Y-%m-%d"),
                        "ticker": ticker, "market": market,
                        "action": "BUY", "price": round(buy_px, 4),
                        "pnl": 0.0, "reason": f"신호 {score:+.3f}", "score": score,
                    })

            # ── 신호 매도 ──
            elif score <= config.SELL_THRESHOLD and holding:
                pos = positions[key]
                sell_px = px * (1 - COMMISSION)
                pnl = (sell_px - pos["avg_cost"]) * pos["shares"]
                cash += pos["shares"] * sell_px
                trades.append({
                    "date": check_dt.strftime("%Y-%m-%d"),
                    "ticker": ticker, "market": market,
                    "action": "SELL", "price": round(sell_px, 4),
                    "pnl": round(pnl, 4), "reason": f"신호 {score:+.3f}", "score": score,
                })
                del positions[key]

    # 종료 시 잔여 포지션 청산
    for key, pos in list(positions.items()):
        ticker, market = key
        df = price_data.get(key)
        if df is None:
            continue
        px = float(df["Close"].squeeze().iloc[-1]) * (1 - COMMISSION)
        if px > 0:
            pnl = (px - pos["avg_cost"]) * pos["shares"]
            cash += pos["shares"] * px
            trades.append({
                "date": end_date.strftime("%Y-%m-%d"),
                "ticker": ticker, "market": market,
                "action": "SELL(청산)", "price": round(px, 4),
                "pnl": round(pnl, 4), "reason": "기간 종료 청산", "score": 0,
            })

    # ── 5. 성과 지표 ─────────────────────────────────────
    if not equity_curve:
        return {"error": "결과 없음"}

    final_value = cash
    total_return_pct = (final_value - initial_capital) / initial_capital * 100
    ann_return_pct = total_return_pct * (365 / max(period_days, 1))

    vals = [e["value"] for e in equity_curve]
    peak = initial_capital
    max_dd = 0.0
    for v in vals:
        if v > peak:
            peak = v
        dd = (v - peak) / peak * 100
        if dd < max_dd:
            max_dd = dd

    pct_changes = pd.Series(vals).pct_change().dropna()
    weeks_per_year = 52
    sharpe = 0.0
    if len(pct_changes) > 1 and pct_changes.std() > 0:
        sharpe = float(pct_changes.mean() / pct_changes.std() * (weeks_per_year ** 0.5))

    sell_trades = [t for t in trades if "SELL" in t["action"]]
    winning = [t for t in sell_trades if t["pnl"] > 0]
    win_rate = len(winning) / len(sell_trades) * 100 if sell_trades else 0.0
    avg_win = sum(t["pnl"] for t in winning) / len(winning) if winning else 0.0
    losers = [t for t in sell_trades if t["pnl"] <= 0]
    avg_loss = sum(t["pnl"] for t in losers) / len(losers) if losers else 0.0
    profit_factor = abs(sum(t["pnl"] for t in winning) / sum(t["pnl"] for t in losers)) if losers and sum(t["pnl"] for t in losers) != 0 else float("inf")

    return {
        "period_days": period_days,
        "initial_capital": initial_capital,
        "final_value": round(final_value, 4),
        "total_return": round(total_return_pct, 2),
        "annualized_return": round(ann_return_pct, 2),
        "max_drawdown": round(max_dd, 2),
        "sharpe_ratio": round(sharpe, 3),
        "win_rate": round(win_rate, 1),
        "trade_count": len(trades),
        "sell_count": len(sell_trades),
        "avg_win": round(avg_win, 4),
        "avg_loss": round(avg_loss, 4),
        "profit_factor": round(profit_factor, 2) if profit_factor != float("inf") else "∞",
        "equity_curve": equity_curve,
        "trades": sorted(trades, key=lambda x: x["date"], reverse=True)[:100],
    }
