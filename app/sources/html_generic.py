"""Fonte generica: legge le pagine elenco, raccoglie i link agli eventi e scarica ogni scheda."""
from __future__ import annotations

import hashlib

from ..extract import find_links
from ..models import RawEvent
from .base import Source


class HtmlSource(Source):
    def fetch(self) -> list[RawEvent]:
        listing = list(self.cfg.get("listing_urls") or [])
        pag = self.cfg.get("pagination")
        if pag and listing:
            first = listing[0].rstrip("/") + "/"
            for n in range(2, int(self.cfg.get("max_pages", 1)) + 1):
                listing.append(first + pag.format(n=n))

        links: list[str] = []
        for url in listing:
            try:
                html = self.http.get_text(url)
            except Exception as e:  # noqa: BLE001
                self.log.warning("elenco %s non raggiungibile: %s", url, e)
                continue
            for link in find_links(html, url, self.cfg["link_pattern"], self.cfg.get("exclude_pattern"),
                                   external=bool(self.cfg.get("external_links"))):
                if link not in links:
                    links.append(link)

        limit = int(self.cfg.get("max_links", 60))
        out = [
            RawEvent(
                source_id=self.id,
                source_name=self.name,
                uid=hashlib.sha1(link.encode()).hexdigest()[:16],
                url=link,
                hints=self.base_hints(),
                needs_page_fetch=True,
            )
            for link in links[:limit]
        ]
        self.log.info("%d link a schede evento", len(out))
        return out
