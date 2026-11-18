"""Comuni su piattaforma Municipium: API JSON pubblica *-api.municipiumapp.it/api/site/v2/events."""
from __future__ import annotations

from datetime import date

from ..extract import html_to_text
from ..models import RawEvent
from .base import Source

S3_BASE = "https://municipium-images-production.s3-website-eu-west-1.amazonaws.com"


def _time(v: str | None) -> str | None:
    """'2000-01-01T20:30:55Z' -> '20:30' (Municipium usa una data fittizia per gli orari)."""
    if not v or "T" not in v:
        return None
    hhmm = v.split("T", 1)[1][:5]
    return hhmm if hhmm != "00:00" else None


def _time_tz(item: dict, key: str) -> str | None:
    # preferisci il campo con fuso orario, che è già in ora locale
    return _time(item.get(f"{key}_with_timezone")) or _time(item.get(key))


def image_urls(img: dict | None, api_base: str) -> list[str]:
    """URL candidati per l'immagine originale (il primo che risponde viene usato)."""
    if not img or not isinstance(img, dict):
        return []
    out = []
    orig = img.get("url") or img.get("default")
    big = img.get("i1440x1920") or img.get("i1280")
    base = img.get("base_url") or S3_BASE
    for path, host in ((orig, api_base), (big, base), (orig, base)):
        if not path:
            continue
        u = path if path.startswith("http") else host.rstrip("/") + path
        if u not in out:
            out.append(u)
    return out


def parse_date(v: str | None) -> date | None:
    try:
        return date.fromisoformat(v[:10]) if v else None
    except ValueError:
        return None


class MunicipiumSource(Source):
    def fetch(self) -> list[RawEvent]:
        api = self.cfg["api"].rstrip("/")
        items = self.http.get_json(f"{api}/api/site/v2/events")
        if isinstance(items, dict):  # alcune versioni restituiscono {"data": [...]}
            items = items.get("data") or items.get("events") or []
        out: list[RawEvent] = []
        for it in items:
            end = parse_date(it.get("end_date")) or parse_date(it.get("start_date"))
            if not end or end < self.today:
                continue
            try:
                d = self.http.get_json(f"{api}/api/site/v2/events/{it['id']}")
            except Exception as e:  # noqa: BLE001
                self.log.warning("dettaglio evento %s non disponibile: %s", it.get("id"), e)
                d = it
            out.append(self._to_raw(d, api))
        self.log.info("%d eventi futuri", len(out))
        return out

    def _to_raw(self, d: dict, api: str) -> RawEvent:
        text_parts = []
        for k in ("subtitle", "breve", "content", "excerpt"):
            v = d.get(k)
            if v:
                text_parts.append(html_to_text(v) if "<" in v else v)
                if k == "content":
                    break
        for k, label in (("costo", "Costo"), ("rivolto_a", "Rivolto a"), ("ulteriori_informazioni", "Ulteriori informazioni"),
                         ("patrocinato_da", "Patrocinato da"), ("punti_contatto", "Contatti")):
            v = d.get(k)
            if v:
                v = html_to_text(v) if isinstance(v, str) and "<" in v else v
                text_parts.append(f"{label}: {v}")

        luogo = d.get("luogo") or {}
        hints = self.base_hints() | {
            "start_date": d.get("start_date"),
            "end_date": d.get("end_date"),
            "start_time": _time_tz(d, "start_time"),
            "end_time": _time_tz(d, "end_time"),
            "address": d.get("address") or (luogo.get("address") if isinstance(luogo, dict) else None),
            "venue": luogo.get("name") if isinstance(luogo, dict) else None,
            "lat": d.get("latitude"),
            "lng": d.get("longitude"),
            "categorie_fonte": [c.get("name") for c in d.get("event_categories") or [] if isinstance(c, dict)],
        }
        hints = {k: v for k, v in hints.items() if v not in (None, "", [])}

        images: list[str] = []
        if d.get("has_image", True):
            images.extend(image_urls(d.get("image"), api))
        for im in d.get("images") or []:
            for u in image_urls(im if isinstance(im, dict) else None, api):
                if u not in images:
                    images.append(u)

        pdfs = []
        for a in d.get("attachments") or []:
            if isinstance(a, dict):
                u = a.get("url") or a.get("file_url") or a.get("path")
                if u and u.lower().split("?")[0].endswith(".pdf"):
                    pdfs.append(u if u.startswith("http") else api + u)

        return RawEvent(
            source_id=self.id,
            source_name=self.name,
            uid=str(d.get("id")),
            url=(f"{self.cfg['site_url'].rstrip('/')}/it/events/{d['slug']}" if self.cfg.get("site_url") and d.get("slug")
                 else d.get("url") or f"{api}/event/{d.get('id')}"),
            title=d.get("title") or "",
            text="\n\n".join(text_parts),
            image_urls=images,
            pdf_urls=pdfs,
            hints=hints,
        )
