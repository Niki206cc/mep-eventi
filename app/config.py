"""Configurazione letta dalle variabili d'ambiente (stack Portainer / file .env)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml


def _bool(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None or v.strip() == "":
        return default
    return v.strip().lower() in {"1", "true", "yes", "si", "sì", "on"}


def _int(name: str, default: int) -> int:
    v = os.getenv(name)
    try:
        return int(v) if v not in (None, "") else default
    except ValueError:
        return default


def _list(name: str, default: list[str]) -> list[str]:
    v = os.getenv(name)
    if not v:
        return default
    return [x.strip() for x in v.split(",") if x.strip()]


DEFAULT_CATEGORIES = [
    "Sagre e feste",
    "Musica e concerti",
    "Teatro e cinema",
    "Mostre e cultura",
    "Incontri e presentazioni",
    "Sport e outdoor",
    "Escursioni e visite guidate",
    "Bambini e famiglie",
    "Mercati e mercatini",
    "Natale",
    "Corsi e laboratori",
    "Enogastronomia",
    "Altro",
]


@dataclass
class Settings:
    # WordPress / The Events Calendar
    wp_url: str = field(default_factory=lambda: os.getenv("WP_URL", "https://www.montagneepaesi.com").rstrip("/"))
    wp_user: str = field(default_factory=lambda: os.getenv("WP_USER", ""))
    wp_app_password: str = field(default_factory=lambda: os.getenv("WP_APP_PASSWORD", ""))
    wp_request_delay: float = field(default_factory=lambda: float(os.getenv("WP_REQUEST_DELAY", "3")))
    wp_timeout: int = field(default_factory=lambda: _int("WP_TIMEOUT", 40))
    wp_max_failures: int = field(default_factory=lambda: _int("WP_MAX_FAILURES", 3))
    publish_status: str = field(default_factory=lambda: os.getenv("PUBLISH_STATUS", "draft"))  # draft | pending | publish
    add_source_link: bool = field(default_factory=lambda: _bool("ADD_SOURCE_LINK", True))
    categories: list[str] = field(default_factory=lambda: _list("EVENT_CATEGORIES", DEFAULT_CATEGORIES))
    tag_comune: bool = field(default_factory=lambda: _bool("TAG_COMUNE", True))
    tag_zona: bool = field(default_factory=lambda: _bool("TAG_ZONA", True))

    # IA
    llm_provider: str = field(default_factory=lambda: os.getenv("LLM_PROVIDER", "anthropic").lower())
    anthropic_api_key: str = field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY", ""))
    anthropic_model: str = field(default_factory=lambda: os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5-5"))
    openai_api_key: str = field(default_factory=lambda: os.getenv("OPENAI_API_KEY", ""))
    openai_model: str = field(default_factory=lambda: os.getenv("OPENAI_MODEL", "gpt-4.1-mini"))
    llm_vision: bool = field(default_factory=lambda: _bool("LLM_VISION", True))

    # Regole sugli eventi
    horizon_days: int = field(default_factory=lambda: _int("HORIZON_DAYS", 120))
    max_occurrences: int = field(default_factory=lambda: _int("MAX_OCCURRENCES", 8))
    skip_recurring: bool = field(default_factory=lambda: _bool("SKIP_RECURRING", True))
    max_period_days: int = field(default_factory=lambda: _int("MAX_PERIOD_DAYS", 120))
    max_new_per_run: int = field(default_factory=lambda: _int("MAX_NEW_PER_RUN", 15))
    min_image_side: int = field(default_factory=lambda: _int("MIN_IMAGE_SIDE", 300))
    check_existing_on_site: bool = field(default_factory=lambda: _bool("CHECK_EXISTING_ON_SITE", True))

    # Esecuzione
    timezone: str = field(default_factory=lambda: os.getenv("TZ", "Europe/Rome"))
    run_at: list[str] = field(default_factory=lambda: _list("RUN_AT", ["05:30"]))
    run_on_start: bool = field(default_factory=lambda: _bool("RUN_ON_START", False))
    data_dir: Path = field(default_factory=lambda: Path(os.getenv("DATA_DIR", "/data")))
    sources_file: Path = field(default_factory=lambda: Path(os.getenv("SOURCES_FILE", str(Path(__file__).resolve().parent.parent / "config" / "sources.yaml"))))
    user_agent: str = field(default_factory=lambda: os.getenv(
        "USER_AGENT",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36 MEP-Eventi/1.0",
    ))
    request_delay: float = field(default_factory=lambda: float(os.getenv("REQUEST_DELAY", "1.0")))

    # Notifiche Telegram
    telegram_token: str = field(default_factory=lambda: os.getenv("TELEGRAM_BOT_TOKEN", ""))
    telegram_chat_id: str = field(default_factory=lambda: os.getenv("TELEGRAM_CHAT_ID", ""))

    # Interfaccia web
    web_enabled: bool = field(default_factory=lambda: _bool("WEB_ENABLED", True))
    web_port: int = field(default_factory=lambda: _int("WEB_PORT", 8080))
    web_user: str = field(default_factory=lambda: os.getenv("WEB_USER", "admin"))
    web_password: str = field(default_factory=lambda: os.getenv("WEB_PASSWORD", ""))

    log_level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO"))

    def load_sources(self) -> list[dict]:
        with open(self.sources_file, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return [s for s in data.get("sources", []) if s.get("enabled", True)]
