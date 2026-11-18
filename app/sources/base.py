from __future__ import annotations

import logging
from datetime import date

from ..http import Http
from ..models import RawEvent


class Source:
    def __init__(self, cfg: dict, http: Http, today: date):
        self.cfg = cfg
        self.http = http
        self.today = today
        self.id = cfg["id"]
        self.name = cfg.get("name", self.id)
        self.log = logging.getLogger(f"source.{self.id}")

    def base_hints(self) -> dict:
        h = {}
        for k in ("comune", "zona", "provincia"):
            if self.cfg.get(k):
                h[k] = self.cfg[k]
        return h

    def fetch(self) -> list[RawEvent]:  # pragma: no cover - interfaccia
        raise NotImplementedError
