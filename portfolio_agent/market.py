"""Dati di mercato (Yahoo Finance) e metriche di portafoglio.

Tutta la matematica sta qui, in funzioni deterministiche: il modello ragiona
sui numeri calcolati, non li inventa.
"""

from __future__ import annotations

import math
from pathlib import Path

import pandas as pd
import yaml

TRADING_DAYS = 252


# --------------------------------------------------------------------------
# Accesso ai dati (unico punto che tocca la rete)
# --------------------------------------------------------------------------

def fetch_closes(tickers: list[str], period: str = "1y") -> pd.DataFrame:
    """Prezzi di chiusura rettificati: una colonna per ticker."""
    import yfinance as yf

    data = yf.download(
        tickers, period=period, auto_adjust=True, progress=False, group_by="column"
    )
    if data.empty:
        return pd.DataFrame(columns=tickers)
    closes = data["Close"]
    if isinstance(closes, pd.Series):
        closes = closes.to_frame(tickers[0])
    return closes.dropna(how="all")


def fetch_info(ticker: str) -> dict:
    """Dati anagrafici e fondamentali di un titolo o ETF."""
    import yfinance as yf

    return yf.Ticker(ticker).info or {}


# --------------------------------------------------------------------------
# Portafoglio
# --------------------------------------------------------------------------

def load_portfolio(path: str | Path) -> dict:
    with open(path, encoding="utf-8") as f:
        portfolio = yaml.safe_load(f) or {}
    portfolio.setdefault("base_currency", "EUR")
    portfolio.setdefault("cash", 0.0)
    portfolio.setdefault("holdings", [])
    portfolio.setdefault("profile", {})
    for h in portfolio["holdings"]:
        h.setdefault("currency", portfolio["base_currency"])
        h.setdefault("target_weight", None)
    return portfolio


def fx_rates(currencies: set[str], base: str) -> dict[str, float]:
    """Tassi di cambio valuta -> valuta base."""
    rates = {base: 1.0}
    pairs = {c: f"{c}{base}=X" for c in currencies if c != base}
    if pairs:
        closes = fetch_closes(list(pairs.values()), period="5d")
        for cur, pair in pairs.items():
            series = closes[pair].dropna() if pair in closes else pd.Series(dtype=float)
            if series.empty:
                raise ValueError(f"Tasso di cambio non disponibile per {cur}/{base}")
            rates[cur] = float(series.iloc[-1])
    return rates


def portfolio_snapshot(portfolio: dict) -> dict:
    """Valore corrente, pesi, P&L e scostamento dai pesi obiettivo."""
    base = portfolio["base_currency"]
    holdings = portfolio["holdings"]
    tickers = [h["ticker"] for h in holdings]
    closes = fetch_closes(tickers, period="5d") if tickers else pd.DataFrame()
    rates = fx_rates({h["currency"] for h in holdings}, base)

    rows, missing = [], []
    for h in holdings:
        series = closes[h["ticker"]].dropna() if h["ticker"] in closes else pd.Series(dtype=float)
        if series.empty:
            # Strumenti non quotati su Yahoo (es. fondi comuni): prezzo inserito a mano.
            if not h.get("manual_price"):
                missing.append(h["ticker"])
                continue
            price = prev = float(h["manual_price"])
            price_date = f"{h.get('manual_price_date', 'data ignota')} (prezzo manuale)"
        else:
            price = float(series.iloc[-1])
            prev = float(series.iloc[-2]) if len(series) > 1 else price
            price_date = str(series.index[-1].date())
        rate = rates[h["currency"]]
        value = price * h["quantity"] * rate
        row = {
            "ticker": h["ticker"],
            "name": h.get("name"),
            "quantity": h["quantity"],
            "currency": h["currency"],
            "price": round(price, 4),
            "price_date": price_date,
            "day_change_pct": round((price / prev - 1) * 100, 2),
            "value_base": round(value, 2),
            "target_weight_pct": h["target_weight"],
        }
        if h.get("avg_cost"):
            cost = h["avg_cost"] * h["quantity"] * rate
            row["pnl_base"] = round(value - cost, 2)
            row["pnl_pct"] = round((price / h["avg_cost"] - 1) * 100, 2)
        rows.append(row)

    invested = sum(r["value_base"] for r in rows)
    total = invested + float(portfolio["cash"])
    for r in rows:
        r["weight_pct"] = round(r["value_base"] / total * 100, 2) if total else 0.0
        if r["target_weight_pct"] is not None:
            r["drift_pct"] = round(r["weight_pct"] - r["target_weight_pct"], 2)

    return {
        "base_currency": base,
        "total_value": round(total, 2),
        "invested_value": round(invested, 2),
        "cash": float(portfolio["cash"]),
        "cash_weight_pct": round(float(portfolio["cash"]) / total * 100, 2) if total else 0.0,
        "holdings": sorted(rows, key=lambda r: -r["value_base"]),
        "tickers_without_data": missing,
        "profile": portfolio["profile"],
    }


# --------------------------------------------------------------------------
# Metriche
# --------------------------------------------------------------------------

def _rsi(series: pd.Series, window: int = 14) -> float | None:
    if len(series) <= window:
        return None
    delta = series.diff().dropna()
    gain = delta.clip(lower=0).tail(window).mean()
    loss = -delta.clip(upper=0).tail(window).mean()
    if loss == 0:
        return 100.0
    return round(100 - 100 / (1 + gain / loss), 1)


def _pct(series: pd.Series, days: int) -> float | None:
    if len(series) <= days:
        return None
    return round((series.iloc[-1] / series.iloc[-1 - days] - 1) * 100, 2)


def price_stats(closes: pd.DataFrame) -> dict:
    """Rendimenti, volatilità, drawdown e indicatori tecnici per ticker."""
    out = {}
    for ticker in closes.columns:
        s = closes[ticker].dropna()
        if len(s) < 2:
            out[ticker] = {"error": "dati insufficienti"}
            continue
        rets = s.pct_change().dropna()
        vol = rets.std() * math.sqrt(TRADING_DAYS)
        drawdown = s / s.cummax() - 1
        last = float(s.iloc[-1])
        stats = {
            "last_price": round(last, 4),
            "last_date": str(s.index[-1].date()),
            "return_1d_pct": _pct(s, 1),
            "return_1w_pct": _pct(s, 5),
            "return_1m_pct": _pct(s, 21),
            "return_3m_pct": _pct(s, 63),
            "return_period_pct": round((last / float(s.iloc[0]) - 1) * 100, 2),
            "volatility_annual_pct": round(vol * 100, 2),
            "max_drawdown_pct": round(float(drawdown.min()) * 100, 2),
            "current_drawdown_pct": round(float(drawdown.iloc[-1]) * 100, 2),
            "rsi_14": _rsi(s),
            "observations": len(s),
        }
        for window in (50, 200):
            if len(s) >= window:
                sma = float(s.tail(window).mean())
                stats[f"vs_sma{window}_pct"] = round((last / sma - 1) * 100, 2)
        out[ticker] = stats
    return out


def correlation_matrix(closes: pd.DataFrame) -> dict:
    corr = closes.pct_change().dropna(how="all").corr().round(2)
    return {a: {b: float(corr.loc[a, b]) for b in corr.columns} for a in corr.index}


def rebalance_trades(snapshot: dict, new_cash: float = 0.0) -> dict:
    """Operazioni per riportare le posizioni ai pesi obiettivo.

    Considera solo le posizioni con target_weight impostato; `new_cash` è
    liquidità aggiuntiva da investire (es. versamento mensile).
    """
    total = snapshot["total_value"] + new_cash
    trades = []
    for h in snapshot["holdings"]:
        target = h.get("target_weight_pct")
        if target is None:
            continue
        delta_value = total * target / 100 - h["value_base"]
        price_base = h["value_base"] / h["quantity"] if h["quantity"] else None
        trades.append({
            "ticker": h["ticker"],
            "action": "COMPRA" if delta_value > 0 else "VENDI",
            "amount_base": round(abs(delta_value), 2),
            "approx_units": round(abs(delta_value) / price_base, 2) if price_base else None,
            "current_weight_pct": h["weight_pct"],
            "target_weight_pct": target,
        })
    trades.sort(key=lambda t: -t["amount_base"])
    return {
        "base_currency": snapshot["base_currency"],
        "total_value_after_new_cash": round(total, 2),
        "trades": trades,
        "note": "Importi lordi: non includono commissioni né imposte sulle plusvalenze.",
    }


INFO_FIELDS = (
    "longName", "quoteType", "sector", "industry", "category", "fundFamily",
    "currency", "marketCap", "totalAssets", "trailingPE", "forwardPE",
    "priceToBook", "dividendYield", "yield", "payoutRatio", "beta", "beta3Year",
    "profitMargins", "revenueGrowth", "earningsGrowth", "debtToEquity",
    "returnOnEquity", "netExpenseRatio", "annualReportExpenseRatio",
    "fiftyTwoWeekLow", "fiftyTwoWeekHigh", "targetMeanPrice",
    "recommendationKey", "numberOfAnalystOpinions",
)


def fundamentals(ticker: str) -> dict:
    info = fetch_info(ticker)
    data = {k: info[k] for k in INFO_FIELDS if info.get(k) is not None}
    return data or {"error": f"Nessun dato disponibile per {ticker}"}
