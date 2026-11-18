from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field


@dataclass
class RawEvent:
    """Evento grezzo come arriva da una fonte, prima dell'elaborazione IA."""

    source_id: str
    source_name: str
    uid: str                      # id stabile all'interno della fonte
    url: str                      # pagina pubblica dell'evento
    title: str = ""
    text: str = ""                # testo della scheda / pagina
    image_urls: list[str] = field(default_factory=list)
    pdf_urls: list[str] = field(default_factory=list)
    hints: dict = field(default_factory=dict)   # dati strutturati già noti (date, luogo, comune...)
    needs_page_fetch: bool = False  # True = scaricare la pagina url per avere il testo

    def content_hash(self) -> str:
        payload = json.dumps(
            {"t": self.title, "x": self.text[:20000], "h": self.hints, "i": self.image_urls[:3]},
            sort_keys=True, ensure_ascii=False, default=str,
        )
        return hashlib.sha1(payload.encode("utf-8")).hexdigest()
