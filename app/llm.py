"""Estrazione dei dati e scrittura della descrizione con un modello IA (Anthropic o OpenAI)."""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import re
from datetime import date

import requests

from .config import Settings
from .images import Picture, shrink_for_llm
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


def build_user_prompt(raw: RawEvent, extra_pdf_text: str = "", max_chars: int = 6000) -> str:
    parts = [
        f"FONTE: {raw.source_name}",
        f"URL: {raw.url}",
        f"TITOLO ORIGINALE: {raw.title or '(non indicato)'}",
    ]
    if raw.hints:
        parts.append("DATI STRUTTURATI DALLA FONTE (affidabili): " + json.dumps(raw.hints, ensure_ascii=False, default=str))
    parts.append("TESTO DELLA SCHEDA:\n" + (raw.text or "(vuoto)")[:max_chars])
    if extra_pdf_text:
        parts.append("TESTO DEL PDF ALLEGATO (locandina/programma):\n" + extra_pdf_text[:2500])
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


class Deferred(Exception):
    """L'analisi è stata messa in coda per l'elaborazione in differita."""


def cache_key(raw: RawEvent) -> str:
    return f"{raw.source_id}|{raw.uid}|{(raw.title or '').strip()}"


class LLM:
    def __init__(self, st: Settings, store=None, batch: bool = False):
        self.st = st
        self.store = store
        self.batch = batch and st.llm_provider != "openai" and store is not None
        self.queue: list[tuple[str, str, dict]] = []   # (custom_id, key, params)
        self.calls = 0
        self.tokens_in = 0
        self.tokens_out = 0

    def analyze(self, raw: RawEvent, today: date, picture: Picture | None, pdf_text: str = "") -> dict:
        system = SYSTEM_PROMPT.format(today=today.isoformat(), categories=", ".join(self.st.categories))
        key = cache_key(raw)
        if self.store is not None:
            cached = self.store.llm_cached(key)
            if cached:
                data = parse_json(cached)
                if isinstance(data, dict):
                    return data
        user = build_user_prompt(raw, pdf_text, self.st.llm_text_chars)
        img = shrink_for_llm(picture, self.st.llm_image_side) if (picture and self.st.llm_vision) else None
        if self.batch:
            if self.store.llm_is_pending(key) or any(k == key for _, k, _ in self.queue):
                raise Deferred()
            cid = hashlib.sha1(key.encode()).hexdigest()[:40]
            self.queue.append((cid, key, self._anthropic_params(system, user, img)))
            self.calls += 1
            raise Deferred()
        self.calls += 1
        if self.st.llm_provider == "openai":
            out = self._openai(system, user, img)
        else:
            out = self._anthropic(system, user, img)
        data = parse_json(out)
        if not isinstance(data, dict):
            raise ValueError("risposta IA non valida")
        return data

    def _headers(self) -> dict:
        return {"x-api-key": self.st.anthropic_api_key, "anthropic-version": "2023-06-01",
                "content-type": "application/json"}

    def _anthropic_params(self, system: str, user: str, img: Picture | None) -> dict:
        content: list[dict] = []
        if img:
            content.append({"type": "image", "source": {
                "type": "base64", "media_type": img.mime, "data": base64.b64encode(img.data).decode()}})
        content.append({"type": "text", "text": user})
        return {"model": self.st.anthropic_model, "max_tokens": 3000, "system": system,
                "messages": [{"role": "user", "content": content}]}

    # ------------------------------------------------------------------ differita (Message Batches)
    def submit_batch(self) -> str | None:
        """Invia la coda come un'unica richiesta in differita. Ritorna l'id del batch."""
        if not self.queue:
            return None
        if not self.st.anthropic_api_key:
            raise RuntimeError("ANTHROPIC_API_KEY mancante")
        reqs = [{"custom_id": cid, "params": params} for cid, _, params in self.queue]
        r = requests.post("https://api.anthropic.com/v1/messages/batches", headers=self._headers(),
                          json={"requests": reqs}, timeout=300)
        if r.status_code >= 400:
            raise RuntimeError(f"Anthropic batch {r.status_code}: {r.text[:300]}")
        batch_id = r.json()["id"]
        self.store.llm_add_batch(batch_id, [(cid, key) for cid, key, _ in self.queue])
        log.info("IA in differita: inviate %d analisi (batch %s)", len(self.queue), batch_id)
        self.queue.clear()
        return batch_id

    def collect_batches(self) -> int:
        """Scarica i risultati dei batch conclusi nella cache. Ritorna quanti risultati nuovi."""
        got = 0
        for b in self.store.llm_open_batches():
            r = requests.get(f"https://api.anthropic.com/v1/messages/batches/{b['id']}", headers=self._headers(), timeout=60)
            if r.status_code == 404:
                self.store.llm_close_batch(b["id"], "perso", 0, 0)
                continue
            r.raise_for_status()
            info = r.json()
            if info.get("processing_status") != "ended":
                continue
            res = requests.get(info["results_url"], headers=self._headers(), timeout=300)
            res.raise_for_status()
            tin = tout = 0
            for line in res.text.splitlines():
                if not line.strip():
                    continue
                item = json.loads(line)
                result = item.get("result") or {}
                key = self.store.llm_pending_key(item.get("custom_id", ""))
                if not key or result.get("type") != "succeeded":
                    continue
                msg = result.get("message") or {}
                usage = msg.get("usage") or {}
                tin += int(usage.get("input_tokens") or 0)
                tout += int(usage.get("output_tokens") or 0)
                text = "".join(c.get("text", "") for c in msg.get("content", []) if c.get("type") == "text")
                if text:
                    self.store.llm_cache_put(key, text)
                    got += 1
            self.store.llm_close_batch(b["id"], "concluso", tin, tout)
            cost = (tin * self.st.price_in + tout * self.st.price_out) / 1e6 / 2
            log.info("IA in differita: batch %s concluso, %d risultati, circa %.3f $", b["id"], got, cost)
        return got

    def _anthropic(self, system: str, user: str, img: Picture | None) -> str:
        if not self.st.anthropic_api_key:
            raise RuntimeError("ANTHROPIC_API_KEY mancante")
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers=self._headers(),
            json=self._anthropic_params(system, user, img),
            timeout=180,
        )
        if r.status_code >= 400:
            raise RuntimeError(f"Anthropic {r.status_code}: {r.text[:300]}")
        data = r.json()
        usage = data.get("usage") or {}
        self.tokens_in += int(usage.get("input_tokens") or 0)
        self.tokens_out += int(usage.get("output_tokens") or 0)
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
