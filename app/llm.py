"""Estrazione dei dati e scrittura della descrizione con un modello IA (Anthropic o OpenAI)."""
from __future__ import annotations

import base64
import json
import logging
import re
from datetime import date

import requests

from .config import Settings
from .images import Picture
from .models import RawEvent

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """Sei il redattore eventi di Montagne & Paesi, sito di notizie locali delle valli \
bergamasche, bresciane e valtellinesi (Val Seriana, Val di Scalve, Alto Sebino, Valle Camonica...).
Ricevi il contenuto grezzo di una scheda evento presa dal sito di un comune o di un ente turistico, \
a volte con l'immagine della locandina. Devi:
1) capire se è davvero un evento aperto al pubblico (concerto, sagra, mostra, incontro, gara, visita guidata, \
corso, spettacolo...). NON sono eventi: avvisi amministrativi, bandi, chiusure di uffici, lavori stradali, \
allerte meteo, notizie generiche senza una data di svolgimento;
2) estrarre i dati in modo preciso, senza inventare nulla: se un dato manca lascia null;
3) scrivere una descrizione ORIGINALE (non copiare frasi dalla fonte) in italiano, tono giornalistico \
caldo e chiaro, 120-250 parole, in HTML semplice: <p>, <strong>, <ul><li> per programmi o orari. \
Chiudi con un breve elenco "Info utili" (quando, dove, costo, contatti/prenotazioni se presenti). \
Niente titoli <h1>/<h2>, niente emoji, niente superlativi esagerati, niente frasi tipo "non perdere".

Regole sulle date:
- Oggi è {today}. Formato ISO YYYY-MM-DD, orari HH:MM (24h, ora italiana).
- Se manca l'anno, scegli quello che rende l'evento futuro o in corso.
- I link "aggiungi al calendario" contengono date in UTC (es. 20261212T190000Z): converti in ora italiana.
- kind = "singolo" (un giorno), "piu_date" (poche date distinte, es. 2-8 serate), \
"periodo" (mostra/rassegna/festival aperto con continuità tra start e end), \
"ricorrente" (corso settimanale, mercato settimanale, appuntamento fisso per mesi).
- occurrences: per "singolo" e "piu_date" elenca ogni data con i suoi orari; per "periodo" e "ricorrente" \
metti una sola voce con la data di inizio, e indica period_end.

Categoria: scegli UNA tra: {categories}.

Rispondi SOLO con un oggetto JSON valido, senza testo prima o dopo, con questo schema:
{{
  "is_event": true,
  "not_event_reason": null,
  "title": "titolo chiaro e breve, senza date, max 90 caratteri",
  "kind": "singolo|piu_date|periodo|ricorrente",
  "occurrences": [{{"date": "YYYY-MM-DD", "start_time": "HH:MM o null", "end_time": "HH:MM o null"}}],
  "period_end": "YYYY-MM-DD o null",
  "venue": {{"name": "nome del luogo o null", "address": "via e numero o null", "city": "comune", "province": "BG|BS|SO|...", "zip": "CAP o null"}},
  "organizer": {{"name": null, "phone": null, "email": null, "website": null}},
  "cost": "Ingresso libero / 10 euro / null",
  "category": "una delle categorie",
  "excerpt": "riassunto di una frase, max 160 caratteri",
  "description_html": "<p>...</p>"
}}"""


def build_user_prompt(raw: RawEvent, extra_pdf_text: str = "") -> str:
    parts = [
        f"FONTE: {raw.source_name}",
        f"URL: {raw.url}",
        f"TITOLO ORIGINALE: {raw.title or '(non indicato)'}",
    ]
    if raw.hints:
        parts.append("DATI STRUTTURATI DALLA FONTE (affidabili): " + json.dumps(raw.hints, ensure_ascii=False, default=str))
    parts.append("TESTO DELLA SCHEDA:\n" + (raw.text or "(vuoto)")[:12000])
    if extra_pdf_text:
        parts.append("TESTO DEL PDF ALLEGATO (locandina/programma):\n" + extra_pdf_text[:4000])
    return "\n\n".join(parts)


def parse_json(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            raise
        return json.loads(m.group(0))


class LLM:
    def __init__(self, st: Settings):
        self.st = st

    def analyze(self, raw: RawEvent, today: date, picture: Picture | None, pdf_text: str = "") -> dict:
        system = SYSTEM_PROMPT.format(today=today.isoformat(), categories=", ".join(self.st.categories))
        user = build_user_prompt(raw, pdf_text)
        img = picture if (picture and self.st.llm_vision) else None
        if self.st.llm_provider == "openai":
            out = self._openai(system, user, img)
        else:
            out = self._anthropic(system, user, img)
        data = parse_json(out)
        if not isinstance(data, dict):
            raise ValueError("risposta IA non valida")
        return data

    def _anthropic(self, system: str, user: str, img: Picture | None) -> str:
        if not self.st.anthropic_api_key:
            raise RuntimeError("ANTHROPIC_API_KEY mancante")
        content: list[dict] = []
        if img:
            content.append({"type": "image", "source": {
                "type": "base64", "media_type": img.mime, "data": base64.b64encode(img.data).decode()}})
        content.append({"type": "text", "text": user})
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": self.st.anthropic_api_key, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": self.st.anthropic_model, "max_tokens": 3000, "system": system,
                  "messages": [{"role": "user", "content": content}]},
            timeout=180,
        )
        if r.status_code >= 400:
            raise RuntimeError(f"Anthropic {r.status_code}: {r.text[:300]}")
        data = r.json()
        return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")

    def _openai(self, system: str, user: str, img: Picture | None) -> str:
        if not self.st.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY mancante")
        content: list[dict] = [{"type": "text", "text": user}]
        if img:
            content.append({"type": "image_url", "image_url": {
                "url": f"data:{img.mime};base64,{base64.b64encode(img.data).decode()}"}})
        r = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {self.st.openai_api_key}"},
            json={"model": self.st.openai_model, "response_format": {"type": "json_object"},
                  "messages": [{"role": "system", "content": system}, {"role": "user", "content": content}]},
            timeout=180,
        )
        if r.status_code >= 400:
            raise RuntimeError(f"OpenAI {r.status_code}: {r.text[:300]}")
        return r.json()["choices"][0]["message"]["content"]
