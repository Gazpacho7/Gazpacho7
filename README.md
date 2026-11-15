# Agente AI per il portafoglio

Un agente che ogni giorno analizza il tuo portafoglio di azioni ed ETF e ti dice,
in italiano, cosa conviene fare: cosa comprare, vendere, mantenere o tenere d'occhio.

Usa Claude per il ragionamento, Yahoo Finance per prezzi e fondamentali, la ricerca
web per le notizie, e tiene un diario delle raccomandazioni passate per dare
continuità ai consigli.

> **Nota.** L'agente dà suggerimenti, non esegue ordini e non ha accesso al tuo
> conto. Nessun modello può prevedere i mercati né garantire guadagni: le decisioni
> restano tue. Non è consulenza finanziaria personalizzata ai sensi di legge.

## Installazione

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...        # da console.anthropic.com
cp portfolio.example.yaml portfolio.yaml   # poi inserisci le tue posizioni
```

In `portfolio.yaml` indichi posizioni, liquidità, prezzo di carico, pesi obiettivo
e il tuo profilo (orizzonte, tolleranza al rischio). Tienilo aggiornato dopo ogni
operazione: è l'unica fonte da cui l'agente conosce il tuo portafoglio.

## Uso

```bash
python -m portfolio_agent status   # fotografia del portafoglio (gratis, senza AI)
python -m portfolio_agent daily    # analisi del giorno, salvata in reports/AAAA-MM-GG.md
python -m portfolio_agent chat     # domande libere: "ha senso aggiungere un ETF small cap?"
```

Il report giornaliero contiene: sintesi, tabella del portafoglio, notizie rilevanti
con fonti, rischi e squilibri, azioni consigliate con importi, cose da monitorare e
verifica delle indicazioni precedenti.

## Esecuzione automatica ogni giorno

Il workflow `.github/workflows/daily-report.yml` genera il report dal lunedì al
venerdì prima dell'apertura dei mercati europei e lo salva nel repository
(lo trovi anche nel riepilogo dell'esecuzione, scheda *Actions*).

1. Aggiungi la chiave in *Settings → Secrets and variables → Actions* come `ANTHROPIC_API_KEY`.
2. Fai il commit del tuo `portfolio.yaml`. **Se il repository è pubblico, le tue
   posizioni saranno visibili a tutti: rendilo privato prima.**
3. Il workflow deve trovarsi sul branch predefinito perché la pianificazione parta.

In alternativa, sul tuo computer: `cron` con `python -m portfolio_agent daily`.

## Come funziona

| File | Ruolo |
|---|---|
| `portfolio_agent/market.py` | Prezzi, cambi, pesi, P&L, volatilità, drawdown, RSI, correlazioni, ribilanciamento |
| `portfolio_agent/tools.py` | Strumenti che il modello può chiamare |
| `portfolio_agent/agent.py` | Istruzioni dell'agente e ciclo modello ↔ strumenti |
| `portfolio_agent/cli.py` | Comandi `status`, `daily`, `chat` |
| `memory/journal.md` | Diario delle raccomandazioni (scritto dall'agente) |

I calcoli sono fatti dal codice, non dal modello: Claude legge i numeri e ragiona
su quelli. Il modello predefinito è `claude-opus-5-5`; si cambia con la variabile
`PORTFOLIO_AGENT_MODEL`. Ogni analisi giornaliera costa indicativamente qualche
decina di centesimi di API.

Test: `pip install pytest && pytest`.
