from __future__ import annotations

from datetime import date

from ..http import Http
from ..models import RawEvent
from .html_generic import HtmlSource
from .municipium import MunicipiumSource
from .wp_rest import WpRestSource
from .wp_valseriana import ValserianaSource

REGISTRY = {
    "html": HtmlSource,
    "municipium": MunicipiumSource,
    "wp_valseriana": ValserianaSource,
    "wp_rest": WpRestSource,
}


def build_source(cfg: dict, http: Http, today: date):
    cls = REGISTRY.get(cfg.get("type"))
    if not cls:
        raise ValueError(f"Tipo di fonte sconosciuto: {cfg.get('type')} ({cfg.get('id')})")
    return cls(cfg, http, today)


__all__ = ["build_source", "RawEvent"]
