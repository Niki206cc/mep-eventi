from __future__ import annotations

import html
import logging

import requests

from .config import Settings

log = logging.getLogger(__name__)


def telegram(st: Settings, text: str) -> None:
    if not (st.telegram_token and st.telegram_chat_id):
        return
    # Telegram accetta al massimo 4096 caratteri per messaggio
    chunks, cur = [], ""
    for line in text.splitlines(keepends=True):
        if len(cur) + len(line) > 3900:
            chunks.append(cur)
            cur = ""
        cur += line
    if cur:
        chunks.append(cur)
    for c in chunks:
        try:
            requests.post(
                f"https://api.telegram.org/bot{st.telegram_token}/sendMessage",
                json={"chat_id": st.telegram_chat_id, "text": c, "parse_mode": "HTML",
                      "disable_web_page_preview": True},
                timeout=20,
            ).raise_for_status()
        except Exception as e:  # noqa: BLE001
            log.warning("notifica Telegram non inviata: %s", e)


def esc(s: str) -> str:
    return html.escape(s or "", quote=False)
