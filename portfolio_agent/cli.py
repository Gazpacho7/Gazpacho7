"""Riga di comando: `python -m portfolio_agent daily | chat | status`."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

import anthropic

from . import market
from .agent import PortfolioAgent, RefusalError
from .tools import Toolbox


def _log_tool(name: str, args: dict) -> None:
    detail = json.dumps(args, ensure_ascii=False) if args else ""
    print(f"  · {name} {detail}", file=sys.stderr)


def _agent(args) -> PortfolioAgent:
    toolbox = Toolbox(args.portfolio, args.journal)
    return PortfolioAgent(toolbox, on_tool=None if args.quiet else _log_tool)


def cmd_daily(args) -> int:
    today = dt.date.today()
    report = _agent(args).daily_report(today)
    out_dir = Path(args.reports)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{today.isoformat()}.md"
    path.write_text(report + "\n", encoding="utf-8")
    print(report)
    print(f"\nReport salvato in {path}", file=sys.stderr)
    return 0


def cmd_chat(args) -> int:
    agent = _agent(args)
    print("Chiedimi qualsiasi cosa sul tuo portafoglio (invio a vuoto o Ctrl-D per uscire).")
    while True:
        try:
            question = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not question:
            break
        print("\n" + agent.ask(question))
    return 0


def cmd_status(args) -> int:
    """Fotografia del portafoglio senza chiamare il modello (nessun costo API)."""
    snap = market.portfolio_snapshot(market.load_portfolio(args.portfolio))
    cur = snap["base_currency"]
    print(f"{'Ticker':<12}{'Valore':>12}{'Peso %':>8}{'Target %':>10}{'Oggi %':>8}{'P&L %':>8}")
    for h in snap["holdings"]:
        target = "-" if h["target_weight_pct"] is None else f"{h['target_weight_pct']:.1f}"
        pnl = f"{h['pnl_pct']:.1f}" if "pnl_pct" in h else "-"
        print(
            f"{h['ticker']:<12}{h['value_base']:>12,.2f}{h['weight_pct']:>8.1f}"
            f"{target:>10}{h['day_change_pct']:>8.2f}{pnl:>8}"
        )
    print(f"\nLiquidità: {snap['cash']:,.2f} {cur} ({snap['cash_weight_pct']:.1f}%)")
    print(f"Totale:    {snap['total_value']:,.2f} {cur}")
    if snap["tickers_without_data"]:
        print(f"Senza dati: {', '.join(snap['tickers_without_data'])}", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="portfolio_agent", description="Agente AI per il portafoglio di azioni ed ETF."
    )
    parser.add_argument("--portfolio", default="portfolio.yaml", help="file del portafoglio")
    parser.add_argument("--journal", default="memory/journal.md", help="diario delle analisi")
    parser.add_argument("--reports", default="reports", help="cartella dei report giornalieri")
    parser.add_argument("--quiet", action="store_true", help="non mostrare gli strumenti usati")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("daily", help="analisi giornaliera, salvata in reports/").set_defaults(func=cmd_daily)
    sub.add_parser("chat", help="conversazione interattiva").set_defaults(func=cmd_chat)
    sub.add_parser("status", help="fotografia del portafoglio, senza AI").set_defaults(func=cmd_status)
    args = parser.parse_args(argv)

    if not Path(args.portfolio).exists():
        print(
            f"Portafoglio non trovato: {args.portfolio}. "
            "Copia portfolio.example.yaml in portfolio.yaml e inserisci le tue posizioni.",
            file=sys.stderr,
        )
        return 2
    try:
        return args.func(args)
    except RefusalError as exc:
        print(f"Errore: {exc}", file=sys.stderr)
    except anthropic.AuthenticationError:
        print("Errore: chiave API mancante o non valida (imposta ANTHROPIC_API_KEY).", file=sys.stderr)
    except anthropic.RateLimitError:
        print("Errore: limite di richieste raggiunto, riprova tra qualche minuto.", file=sys.stderr)
    except anthropic.APIStatusError as exc:
        print(f"Errore API ({exc.status_code}): {exc.message}", file=sys.stderr)
    except anthropic.APIConnectionError:
        print("Errore: impossibile raggiungere l'API Anthropic.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
