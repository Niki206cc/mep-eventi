"""Fonte generica WordPress: un post type esposto in REST (es. turismovallecamonica.it/wp-json/wp/v2/eventi).
Le date non sono strutturate: si leggono dalla pagina dell'evento (IA)."""
from __future__ import annotations

from datetime import datetime, timedelta

from ..extract import html_to_text
from ..models import RawEvent
from .base import Source


class WpRestSource(Source):
    def fetch(self) -> list[RawEvent]:
        base = self.cfg["base_url"].rstrip("/")
        rest_base = self.cfg.get("rest_base", "eventi")
        days = int(self.cfg.get("modified_days", 90))
        after = (datetime.combine(self.today, datetime.min.time()) - timedelta(days=days)).isoformat()
        per_page = int(self.cfg.get("per_page", 50))
        out: list[RawEvent] = []
        for page in range(1, int(self.cfg.get("max_pages", 2)) + 1):
            url = (f"{base}/wp-json/wp/v2/{rest_base}?per_page={per_page}&page={page}"
                   f"&orderby=modified&order=desc&modified_after={after}&_embed=wp:featuredmedia,wp:term")
            try:
                posts = self.http.get_json(url)
            except Exception as e:  # noqa: BLE001
                self.log.debug("stop paginazione a %d: %s", page, e)
                break
            if not posts:
                break
            for p in posts:
                out.append(self._to_raw(p))
            if len(posts) < per_page:
                break
        self.log.info("%d schede modificate negli ultimi %d giorni", len(out), days)
        return out

    def _to_raw(self, p: dict) -> RawEvent:
        emb = p.get("_embedded") or {}
        images = []
        media = emb.get("wp:featuredmedia") or []
        if media and isinstance(media[0], dict) and media[0].get("source_url"):
            images.append(media[0]["source_url"])
        terms: dict[str, list[str]] = {}
        for grp in emb.get("wp:term") or []:
            for t in grp or []:
                if isinstance(t, dict) and t.get("taxonomy"):
                    terms.setdefault(t["taxonomy"], []).append(t.get("name", ""))
        # campi ACF: locandine (oggetti immagine) e dati utili (date, luogo...) come testo per l'IA
        acf_lines = []
        acf = p.get("acf") if isinstance(p.get("acf"), dict) else {}
        for k, v in acf.items():
            if isinstance(v, dict) and v.get("url") and str(v.get("mime_type", "image")).startswith("image"):
                if v["url"] not in images:
                    images.insert(0, v["url"])  # la locandina esplicita ha la precedenza
            elif isinstance(v, (str, int, float)) and str(v).strip() and len(str(v)) < 300:
                acf_lines.append(f"{k}: {v}")
        hints = self.base_hints()
        loc_tax = self.cfg.get("place_taxonomy")
        if loc_tax and terms.get(loc_tax):
            hints["comune"] = ", ".join(terms[loc_tax])
        cats = [n for k in (self.cfg.get("category_taxonomies") or []) for n in terms.get(k, [])]
        if cats:
            hints["categorie_fonte"] = cats
        return RawEvent(
            source_id=self.id,
            source_name=self.name,
            uid=str(p["id"]),
            url=p.get("link"),
            title=html_to_text((p.get("title") or {}).get("rendered", "")),
            text=html_to_text((p.get("content") or {}).get("rendered", ""))
            + ("\n\nDati della scheda:\n" + "\n".join(acf_lines) if acf_lines else ""),
            image_urls=images,
            hints=hints,
            needs_page_fetch=True,
        )

