import json

import numpy as np
import pandas as pd
import pytest

from portfolio_agent import market
from portfolio_agent.tools import TOOL_DEFINITIONS, Toolbox

PORTFOLIO = """
base_currency: EUR
cash: 1000
holdings:
  - {ticker: AAA, quantity: 10, avg_cost: 80, target_weight: 50}
  - {ticker: BBB, quantity: 5, avg_cost: 100, currency: USD, target_weight: 40}
  - {ticker: GONE, quantity: 1}
  - {ticker: FUND, quantity: 10, manual_price: 50, manual_price_date: "2026-01-01"}
"""

PRICES = {"AAA": [90.0, 100.0], "BBB": [200.0, 200.0], "USDEUR=X": [0.5, 0.5]}


@pytest.fixture
def fake_market(monkeypatch, tmp_path):
    def fetch(tickers, period="1y"):
        idx = pd.date_range("2026-01-01", periods=2, freq="B")
        return pd.DataFrame({t: PRICES[t] for t in tickers if t in PRICES}, index=idx)

    monkeypatch.setattr(market, "fetch_closes", fetch)
    path = tmp_path / "portfolio.yaml"
    path.write_text(PORTFOLIO)
    return path


def test_snapshot_values_weights_and_fx(fake_market):
    snap = market.portfolio_snapshot(market.load_portfolio(fake_market))
    by = {h["ticker"]: h for h in snap["holdings"]}
    assert by["AAA"]["value_base"] == 1000        # 10 * 100
    assert by["BBB"]["value_base"] == 500         # 5 * 200 USD * 0.5
    assert by["FUND"]["value_base"] == 500        # prezzo manuale
    assert "manuale" in by["FUND"]["price_date"]
    assert snap["total_value"] == 3000            # + 1000 di liquidità
    assert by["AAA"]["weight_pct"] == pytest.approx(33.33)
    assert by["AAA"]["drift_pct"] == pytest.approx(-16.67)
    assert by["AAA"]["pnl_pct"] == 25
    assert by["AAA"]["day_change_pct"] == pytest.approx(11.11)
    assert by["BBB"]["pnl_base"] == 250           # (200-100) * 5 * 0.5
    assert snap["tickers_without_data"] == ["GONE"]


def test_rebalance_trades(fake_market):
    snap = market.portfolio_snapshot(market.load_portfolio(fake_market))
    plan = market.rebalance_trades(snap, new_cash=500)
    by = {t["ticker"]: t for t in plan["trades"]}
    assert plan["total_value_after_new_cash"] == 3500
    assert by["AAA"] == {**by["AAA"], "action": "COMPRA", "amount_base": 750, "approx_units": 7.5}
    assert by["BBB"]["action"] == "COMPRA" and by["BBB"]["amount_base"] == 900


def test_price_stats():
    idx = pd.date_range("2025-01-01", periods=260, freq="B")
    up = pd.Series(np.linspace(100, 200, 260), index=idx)
    crash = pd.Series([100.0] * 130 + [50.0] * 130, index=idx)
    stats = market.price_stats(pd.DataFrame({"UP": up, "CRASH": crash}))
    assert stats["UP"]["return_period_pct"] == 100
    assert stats["UP"]["max_drawdown_pct"] == 0
    assert stats["UP"]["rsi_14"] == 100
    assert stats["UP"]["vs_sma200_pct"] > 0
    assert stats["CRASH"]["max_drawdown_pct"] == -50
    assert stats["CRASH"]["current_drawdown_pct"] == -50


def test_correlation():
    idx = pd.date_range("2025-01-01", periods=50, freq="B")
    a = pd.Series(100 * np.cumprod(1 + np.sin(np.arange(50)) / 100), index=idx)
    corr = market.correlation_matrix(pd.DataFrame({"A": a, "B": a * 2}))
    assert corr["A"]["B"] == 1.0


def test_toolbox_dispatch_and_journal(fake_market, tmp_path):
    box = Toolbox(fake_market, tmp_path / "memory" / "journal.md")
    out, err = box.execute("get_portfolio", {})
    assert not err and json.loads(out)["total_value"] == 3000
    assert "prima analisi" in box.execute("read_journal", {})[0]
    assert box.execute("append_journal", {"note": "Mantieni AAA"}) == ("Nota salvata nel diario.", False)
    assert "Mantieni AAA" in box.execute("read_journal", {})[0]
    assert box.execute("nope", {})[1] is True
    assert box.execute("get_price_stats", {"tickers": ["AAA"]})[1] is True  # argomento mancante


def test_every_local_tool_has_a_handler():
    for tool in TOOL_DEFINITIONS:
        if "input_schema" in tool:
            assert hasattr(Toolbox, f"_{tool['name']}")
