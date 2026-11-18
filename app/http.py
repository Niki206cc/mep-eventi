from __future__ import annotations

import logging
import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

log = logging.getLogger(__name__)


class Http:
    """Sessione HTTP condivisa con retry e una piccola pausa tra le richieste ai siti fonte."""

    def __init__(self, user_agent: str, delay: float = 1.0):
        self.delay = delay
        self._last = 0.0
        self.s = requests.Session()
        retry = Retry(total=3, backoff_factor=1.5, status_forcelist=(429, 500, 502, 503, 504),
                      allowed_methods=frozenset({"GET", "HEAD"}))
        self.s.mount("https://", HTTPAdapter(max_retries=retry))
        self.s.mount("http://", HTTPAdapter(max_retries=retry))
        self.s.headers.update({
            "User-Agent": user_agent,
            "Accept-Language": "it-IT,it;q=0.9,en;q=0.5",
        })

    def _throttle(self):
        wait = self.delay - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()

    def get(self, url: str, **kw) -> requests.Response:
        self._throttle()
        kw.setdefault("timeout", 30)
        r = self.s.get(url, **kw)
        r.raise_for_status()
        return r

    def get_json(self, url: str, **kw):
        headers = kw.pop("headers", {}) or {}
        headers.setdefault("Accept", "application/json")
        return self.get(url, headers=headers, **kw).json()

    def get_text(self, url: str, **kw) -> str:
        r = self.get(url, **kw)
        if not r.encoding or r.encoding.lower() == "iso-8859-1":
            r.encoding = r.apparent_encoding
        return r.text
