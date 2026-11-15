"""Strumenti che l'agente può chiamare: schema per l'API + esecuzione locale."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from . import market

PERIODS = ["1mo", "3mo", "6mo", "1y", "2y", "5y"]

_TICKERS = {
    "type": "array",
    "items": {"type": "string"},
    "description": "Ticker Yahoo Finance, es. ['VWCE.DE', 'AAPL', 'ENI.MI'].",
}
_PERIOD = {"type": "string", "enum": PERIODS, "description": "Finestra storica."}


def _schema(properties: dict, required: list[str]) -> dict:
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


TOOL_DEFINITIONS = [
    {
        "name": "get_portfolio",
        "description": (
            "Stato attuale del portafoglio dell'utente: posizioni valorizzate ai "
            "prezzi più recenti, pesi, P&L rispetto al prezzo di carico, liquidità, "
            "scostamento dai pesi obiettivo e profilo dell'investitore. "
            "Chiamalo sempre per primo."
        ),
        "input_schema": _schema({}, []),
        "strict": True,
    },
    {
        "name": "get_price_stats",
        "description": (
            "Statistiche di prezzo per uno o più ticker (anche non in portafoglio, "
            "es. benchmark o candidati all'acquisto): rendimenti a 1g/1s/1m/3m, "
            "volatilità annualizzata, drawdown massimo e corrente, RSI a 14 giorni, "
            "distanza dalle medie mobili a 50 e 200 giorni."
        ),
        "input_schema": _schema({"tickers": _TICKERS, "period": _PERIOD}, ["tickers", "period"]),
        "strict": True,
    },
    {
        "name": "get_correlations",
        "description": (
            "Matrice di correlazione dei rendimenti giornalieri tra ticker. Utile "
            "per individuare sovrapposizioni e valutare la reale diversificazione."
        ),
        "input_schema": _schema({"tickers": _TICKERS, "period": _PERIOD}, ["tickers", "period"]),
        "strict": True,
    },
    {
        "name": "get_fundamentals",
        "description": (
            "Dati fondamentali di un titolo o ETF: settore, P/E, dividend yield, "
            "margini, crescita, beta, costi dell'ETF (TER), consenso degli analisti."
        ),
        "input_schema": _schema(
            {"ticker": {"type": "string", "description": "Ticker Yahoo Finance."}}, ["ticker"]
        ),
        "strict": True,
    },
    {
        "name": "simulate_rebalance",
        "description": (
            "Calcola le operazioni di acquisto/vendita necessarie per riportare il "
            "portafoglio ai pesi obiettivo, con eventuale nuova liquidità da investire."
        ),
        "input_schema": _schema(
            {
                "new_cash": {
                    "type": "number",
                    "description": "Liquidità aggiuntiva da investire, in valuta base (0 se nessuna).",
                }
            },
            ["new_cash"],
        ),
        "strict": True,
    },
    {
        "name": "read_journal",
        "description": (
            "Legge il diario delle analisi precedenti: raccomandazioni già date, tesi "
            "aperte, punti da ricontrollare. Usalo per dare continuità ai consigli."
        ),
        "input_schema": _schema({}, []),
        "strict": True,
    },
    {
        "name": "append_journal",
        "description": (
            "Aggiunge una nota datata al diario: raccomandazioni di oggi, motivazione "
            "sintetica e cosa verificare la prossima volta. Chiamalo una sola volta, "
            "alla fine di ogni analisi giornaliera."
        ),
        "input_schema": _schema(
            {"note": {"type": "string", "description": "Nota sintetica in Markdown."}}, ["note"]
        ),
        "strict": True,
    },
    # Eseguito sui server Anthropic: notizie e contesto di mercato aggiornati.
    {"type": "web_search_20260209", "name": "web_search", "max_uses": 8},
]


class Toolbox:
    """Esegue gli strumenti locali sul portafoglio e sul diario dell'utente."""

    JOURNAL_MAX_CHARS = 12_000

    def __init__(self, portfolio_path: str | Path, journal_path: str | Path):
        self.portfolio_path = Path(portfolio_path)
        self.journal_path = Path(journal_path)

    def execute(self, name: str, args: dict) -> tuple[str, bool]:
        """Ritorna (risultato, is_error). Gli errori tornano al modello, non al chiamante."""
        handler = getattr(self, f"_{name}", None)
        if handler is None:
            return f"Strumento sconosciuto: {name}", True
        try:
            result = handler(**args)
        except Exception as exc:  # il modello può correggersi o segnalarlo nel report
            return f"{type(exc).__name__}: {exc}", True
        if isinstance(result, str):
            return result, False
        return json.dumps(result, ensure_ascii=False, default=str), False

    def _snapshot(self) -> dict:
        return market.portfolio_snapshot(market.load_portfolio(self.portfolio_path))

    def _get_portfolio(self) -> dict:
        return self._snapshot()

    def _get_price_stats(self, tickers: list[str], period: str) -> dict:
        return market.price_stats(market.fetch_closes(tickers, period))

    def _get_correlations(self, tickers: list[str], period: str) -> dict:
        return market.correlation_matrix(market.fetch_closes(tickers, period))

    def _get_fundamentals(self, ticker: str) -> dict:
        return market.fundamentals(ticker)

    def _simulate_rebalance(self, new_cash: float) -> dict:
        return market.rebalance_trades(self._snapshot(), new_cash)

    def _read_journal(self) -> str:
        if not self.journal_path.exists():
            return "Il diario è vuoto: questa è la prima analisi."
        text = self.journal_path.read_text(encoding="utf-8")
        if len(text) > self.JOURNAL_MAX_CHARS:
            text = "[...note più vecchie omesse...]\n" + text[-self.JOURNAL_MAX_CHARS:]
        return text

    def _append_journal(self, note: str) -> str:
        self.journal_path.parent.mkdir(parents=True, exist_ok=True)
        with self.journal_path.open("a", encoding="utf-8") as f:
            f.write(f"\n## {dt.date.today().isoformat()}\n\n{note.strip()}\n")
        return "Nota salvata nel diario."
