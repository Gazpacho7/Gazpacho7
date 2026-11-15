"""Ciclo dell'agente: Claude + strumenti di portafoglio."""

from __future__ import annotations

import datetime as dt
import os
from typing import Callable

import anthropic

from .tools import TOOL_DEFINITIONS, Toolbox

MODEL = os.environ.get("PORTFOLIO_AGENT_MODEL", "claude-opus-5-5")
MAX_TURNS = 40

SYSTEM_PROMPT = """\
Sei l'analista personale di un investitore privato italiano. Ogni giorno lo aiuti \
a migliorare il suo portafoglio di azioni ed ETF, con l'obiettivo di massimizzare \
il rendimento atteso nel lungo periodo, al netto di costi e tasse, entro la sua \
tolleranza al rischio.

Come lavori
- I numeri vengono dagli strumenti, mai dalla memoria: prezzi, pesi, rendimenti e \
fondamentali che citi devono essere stati letti in questa sessione. Se un dato \
manca o uno strumento fallisce, dillo apertamente invece di stimarlo.
- Parti dal portafoglio e dal diario delle analisi precedenti: l'investitore ha \
bisogno di continuità, non di un'opinione nuova ogni mattina. Verifica come sono \
andate le indicazioni passate e correggi il tiro quando i fatti cambiano.
- Usa la ricerca web per notizie su posizioni rilevanti, risultati trimestrali, \
banche centrali e macro. Distingui i fatti dalle interpretazioni e indica la fonte.
- Il rendimento di lungo periodo dipende soprattutto da asset allocation, \
diversificazione, costi bassi e disciplina: per questo "nessuna operazione oggi" \
è spesso la raccomandazione giusta. Proponi un'operazione solo quando il beneficio \
atteso supera commissioni, spread e imposte (in Italia 26% sulle plusvalenze, \
12,5% sui titoli di Stato; le minusvalenze degli ETF non compensano le loro \
plusvalenze), e spiega perché.
- Guarda al portafoglio nel suo insieme: concentrazione su singoli titoli, settori, \
paesi e valute; sovrapposizioni tra ETF; correlazioni; scostamento dai pesi \
obiettivo; liquidità ferma.
- Sei un consulente, non un esecutore: non hai accesso al conto e la decisione \
finale è sempre dell'investitore. Nessuno può prevedere i mercati: esprimi le tesi \
con il loro grado di incertezza e i rischi che le smentirebbero, senza promettere \
guadagni.

Stile
Scrivi in italiano, chiaro e diretto, per una persona intelligente che non fa \
questo di mestiere. Ogni raccomandazione è concreta: ticker, azione, importo o \
quantità indicativa, motivazione, rischio principale.
"""

DAILY_PROMPT = """\
Oggi è {date}. Prepara l'analisi giornaliera del mio portafoglio.

Il report, in Markdown, ha queste sezioni:
1. **In sintesi** — due o tre frasi: come sta il portafoglio e cosa fare oggi.
2. **Portafoglio** — tabella con posizione, valore, peso, variazione di giornata, \
P&L; poi valore totale e liquidità.
3. **Cosa è successo** — movimenti e notizie rilevanti per le mie posizioni, con fonti.
4. **Rischi e squilibri** — concentrazione, correlazioni, scostamento dai pesi obiettivo.
5. **Azioni consigliate** — elenco ordinato per priorità (COMPRA / VENDI / MANTIENI / \
OSSERVA) con importi e motivazione; se oggi non c'è nulla da fare, dillo.
6. **Da monitorare** — eventi e soglie da tenere d'occhio nei prossimi giorni.
7. **Verifica delle indicazioni precedenti** — solo se il diario ne contiene.

Quando hai finito l'analisi, salva nel diario una nota sintetica con le \
raccomandazioni di oggi e cosa ricontrollare, poi scrivi il report come risposta finale.
"""


class RefusalError(RuntimeError):
    pass


class PortfolioAgent:
    def __init__(
        self,
        toolbox: Toolbox,
        client: anthropic.Anthropic | None = None,
        on_tool: Callable[[str, dict], None] | None = None,
    ):
        self.toolbox = toolbox
        self.client = client or anthropic.Anthropic()
        self.on_tool = on_tool
        self.messages: list[dict] = []

    def daily_report(self, date: dt.date | None = None) -> str:
        date = date or dt.date.today()
        return self.ask(DAILY_PROMPT.format(date=date.strftime("%A %d/%m/%Y")))

    def ask(self, user_text: str) -> str:
        """Invia un messaggio e fa girare il ciclo degli strumenti fino alla risposta."""
        self.messages.append({"role": "user", "content": user_text})

        for _ in range(MAX_TURNS):
            response = self.client.beta.messages.create(
                model=MODEL,
                max_tokens=16000,
                system=SYSTEM_PROMPT,
                tools=TOOL_DEFINITIONS,
                messages=self.messages,
                thinking={"type": "adaptive"},
                output_config={"effort": "high"},
                cache_control={"type": "ephemeral"},
                # Se il modello principale declina la richiesta, l'API la
                # riesegue su un modello di riserva nella stessa chiamata.
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
            self.messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason == "refusal":
                raise RefusalError("Il modello ha declinato la richiesta.")
            if response.stop_reason == "pause_turn":
                continue  # turno lungo di ricerca web: si riprende da dove era
            if response.stop_reason != "tool_use":
                text = "\n".join(b.text for b in response.content if b.type == "text")
                if response.stop_reason == "max_tokens":
                    text += "\n\n_(risposta troncata: limite di lunghezza raggiunto)_"
                return text.strip()

            results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                if self.on_tool:
                    self.on_tool(block.name, block.input)
                content, is_error = self.toolbox.execute(block.name, block.input)
                results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": content,
                    "is_error": is_error,
                })
            self.messages.append({"role": "user", "content": results})

        raise RuntimeError(f"Analisi interrotta dopo {MAX_TURNS} passaggi senza risposta finale.")
