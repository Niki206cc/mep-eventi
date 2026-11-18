"""valseriana.eu (Promoserio): post type 'eventi' via REST, date nella tassonomia 'eventi_date' (YYYYMMDD)."""
from __future__ import annotations

from datetime import date, datetime

from ..extract import html_to_text
from ..models import RawEvent
from .base import Source


def term_dates(terms: list[dict]) -> list[date]:
    out = []
    for t in terms:
        name = (t.get("name") or t.get("slug") or "").strip()
        try:
            out.append(datetime.strptime(name[:8], "%Y%m%d").date())
        except ValueError:
            continue
    return sorted(set(out))


def embedded_terms(post: dict) -> dict[str, list[dict]]:
    """Raggruppa i termini embeddati per tassonomia."""
    groups: dict[str, list[dict]] = {}
    for group in (post.get("_embedded") or {}).get("wp:term") or []:
        for t in group or []:
            if isinstance(t, dict) and t.get("taxonomy"):
                groups.setdefault(t["taxonomy"], []).append(t)
    return groups


class ValserianaSource(Source):
    def fetch(self) -> list[RawEvent]:
        base = self.cfg.get("base_url", "https://www.valseriana.eu").rstrip("/")
        only = {c.lower() for c in self.cfg.get("only_comuni") or []}
        out: list[RawEvent] = []
        seen = set()
        for page in range(1, int(self.cfg.get("max_pages", 4)) + 1):
            url = f"{base}/wp-json/wp/v2/eventi?per_page=50&page={page}&orderby=modified&order=desc&_embed=1"
            try:
                posts = self.http.get_json(url)
            except Exception as e:  # noqa: BLE001  (pagina oltre l'ultima -> 400)
                self.log.debug("stop paginazione a %d: %s", page, e)
                break
            if not posts:
                break
            for p in posts:
                if p["id"] in seen:
                    continue
                seen.add(p["id"])
                raw = self._to_raw(p, only)
                if raw:
                    out.append(raw)
            if len(posts) < 50:
                break
        self.log.info("%d eventi futuri", len(out))
        return out

    def _to_raw(self, p: dict, only: set[str]) -> RawEvent | None:
        terms = embedded_terms(p)
        dates = term_dates(terms.get("eventi_date", []))
        if dates and dates[-1] < self.today:
            return None
        comuni = [t.get("name") for t in terms.get("comuni", [])]
        comuni_slug = {t.get("slug", "").lower() for t in terms.get("comuni", [])}
        if only and not (only & comuni_slug):
            return None

        images = []
        media = (p.get("_embedded") or {}).get("wp:featuredmedia") or []
        if media and isinstance(media[0], dict) and media[0].get("source_url"):
            images.append(media[0]["source_url"])

        future = [d for d in dates if d >= self.today]
        hints = self.base_hints() | {
            "date_evento": [d.isoformat() for d in future[:30]],
            "start_date": dates[0].isoformat() if dates else None,
            "end_date": dates[-1].isoformat() if dates else None,
            "comune": ", ".join(c for c in comuni if c) or self.cfg.get("comune"),
            "categorie_fonte": [t.get("name") for t in terms.get("categorie_eventi", [])],
        }
        hints = {k: v for k, v in hints.items() if v not in (None, "", [])}
        title = html_to_text((p.get("title") or {}).get("rendered", ""))
        content = html_to_text((p.get("content") or {}).get("rendered", ""))

        return RawEvent(
            source_id=self.id,
            source_name=self.name,
            uid=str(p["id"]),
            url=p.get("link"),
            title=title,
            text=content,
            image_urls=images,
            hints=hints,
            needs_page_fetch=True,  # orari, luogo e PDF sono solo nella pagina
        )

