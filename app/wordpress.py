"""Client per WordPress + The Events Calendar (API REST tribe/events/v1)."""
from __future__ import annotations

import logging
import re
import unicodedata
from difflib import SequenceMatcher

import requests

from .config import Settings
from .store import Store

log = logging.getLogger(__name__)


def norm(s: str | None) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def similar(a: str, b: str) -> float:
    return SequenceMatcher(None, norm(a), norm(b)).ratio()


class WordPressError(RuntimeError):
    pass


class WordPress:
    def __init__(self, st: Settings, store: Store):
        self.st = st
        self.store = store
        self.api = f"{st.wp_url}/wp-json"
        self.s = requests.Session()
        self.s.auth = (st.wp_user, st.wp_app_password.replace(" ", ""))
        self.s.headers["User-Agent"] = "MEP-Eventi/1.0"

    # ------------------------------------------------------------------ base
    def _req(self, method: str, path: str, **kw):
        url = path if path.startswith("http") else f"{self.api}{path}"
        kw.setdefault("timeout", 60)
        r = self.s.request(method, url, **kw)
        if r.status_code >= 400:
            raise WordPressError(f"{method} {path} -> {r.status_code}: {r.text[:400]}")
        return r.json() if r.content else {}

    def check(self) -> None:
        """Verifica credenziali e presenza di The Events Calendar."""
        me = self._req("GET", "/wp/v2/users/me", params={"context": "edit"})
        log.info("WordPress: autenticato come %s", me.get("name"))
        root = self._req("GET", "/")
        if "tribe/events/v1" not in root.get("namespaces", []):
            raise WordPressError("API di The Events Calendar non trovata (namespace tribe/events/v1)")

    # ------------------------------------------------------------------ media
    def upload_media(self, data: bytes, filename: str, mime: str, title: str, alt: str, caption: str = "") -> int:
        media = self._req(
            "POST", "/wp/v2/media", data=data,
            headers={"Content-Disposition": f'attachment; filename="{filename}"', "Content-Type": mime},
        )
        mid = media["id"]
        try:
            self._req("POST", f"/wp/v2/media/{mid}", json={"title": title, "alt_text": alt, "caption": caption})
        except WordPressError as e:
            log.warning("metadati immagine non aggiornati: %s", e)
        return mid

    # ------------------------------------------------------------------ termini
    def category_id(self, name: str) -> int | None:
        if not name:
            return None
        cached = self.store.cache_get("cat", norm(name))
        if cached:
            return cached
        found = self._req("GET", "/tribe/events/v1/categories", params={"search": name, "per_page": 50})
        for c in found.get("categories", []):
            if norm(c.get("name")) == norm(name):
                self.store.cache_set("cat", norm(name), c["id"])
                return c["id"]
        c = self._req("POST", "/tribe/events/v1/categories", json={"name": name})
        self.store.cache_set("cat", norm(name), c["id"])
        return c["id"]

    def tag_id(self, name: str) -> int | None:
        if not name:
            return None
        cached = self.store.cache_get("tag", norm(name))
        if cached:
            return cached
        found = self._req("GET", "/wp/v2/tags", params={"search": name, "per_page": 50})
        for t in found:
            if norm(t.get("name")) == norm(name):
                self.store.cache_set("tag", norm(name), t["id"])
                return t["id"]
        try:
            t = self._req("POST", "/wp/v2/tags", json={"name": name})
        except WordPressError as e:  # term_exists -> id nei dati dell'errore
            m = re.search(r'"term_id":\s*(\d+)', str(e))
            if not m:
                raise
            t = {"id": int(m.group(1))}
        self.store.cache_set("tag", norm(name), t["id"])
        return t["id"]

    # ------------------------------------------------------------------ luoghi e organizzatori
    def venue_id(self, v: dict | None) -> int | None:
        if not v or not (v.get("name") or v.get("address")):
            return None
        name = v.get("name") or v.get("address")
        city = v.get("city") or ""
        key = f"{norm(name)}|{norm(city)}"
        cached = self.store.cache_get("venue", key)
        if cached:
            return cached
        found = self._req("GET", "/tribe/events/v1/venues", params={"search": name, "per_page": 50, "status": "publish"})
        for x in found.get("venues", []):
            if similar(x.get("venue", ""), name) > 0.88 and (not city or norm(x.get("city")) == norm(city)):
                self.store.cache_set("venue", key, x["id"])
                return x["id"]
        payload = {
            "venue": name, "address": v.get("address") or "", "city": city,
            "province": v.get("province") or "", "zip": v.get("zip") or "",
            "country": "Italia", "status": "publish",
        }
        x = self._req("POST", "/tribe/events/v1/venues", json=payload)
        self.store.cache_set("venue", key, x["id"])
        return x["id"]

    def organizer_id(self, o: dict | None) -> int | None:
        if not o or not o.get("name"):
            return None
        key = norm(o["name"])
        cached = self.store.cache_get("org", key)
        if cached:
            return cached
        found = self._req("GET", "/tribe/events/v1/organizers", params={"search": o["name"], "per_page": 50})
        for x in found.get("organizers", []):
            if similar(x.get("organizer", ""), o["name"]) > 0.9:
                self.store.cache_set("org", key, x["id"])
                return x["id"]
        payload = {"organizer": o["name"], "status": "publish"}
        for k in ("phone", "email", "website"):
            if o.get(k):
                payload[k] = o[k]
        x = self._req("POST", "/tribe/events/v1/organizers", json=payload)
        self.store.cache_set("org", key, x["id"])
        return x["id"]

    # ------------------------------------------------------------------ eventi
    def find_existing(self, title: str, day: str) -> int | None:
        """Cerca sul sito un evento con titolo simile nello stesso giorno (anche inserito a mano)."""
        try:
            res = self._req("GET", "/tribe/events/v1/events", params={
                "start_date": f"{day} 00:00:00", "end_date": f"{day} 23:59:59",
                "per_page": 50,
            })
        except WordPressError as e:
            log.debug("ricerca eventi esistenti fallita: %s", e)
            return None
        for ev in res.get("events", []):
            if similar(ev.get("title", ""), title) > 0.8:
                return ev["id"]
        return None

    def create_event(self, payload: dict) -> dict:
        return self._req("POST", "/tribe/events/v1/events", json=payload)

    def update_event(self, event_id: int, payload: dict) -> dict:
        return self._req("POST", f"/tribe/events/v1/events/{event_id}", json=payload)

    def edit_link(self, post_id: int) -> str:
        return f"{self.st.wp_url}/wp-admin/post.php?post={post_id}&action=edit"
