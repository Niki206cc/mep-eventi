"""Interfaccia web di monitoraggio (stdlib, nessuna dipendenza): http://<host>:<WEB_PORT>/"""
from __future__ import annotations

import base64
import hmac
import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .config import Settings
from .state import LIVE, RING, RUN_LOCK
from .store import Store

log = logging.getLogger(__name__)
PAGE = (Path(__file__).parent / "static" / "index.html").read_text(encoding="utf-8")


class App:
    def __init__(self, st: Settings, start_run):
        self.st = st
        self.start_run = start_run  # callable(source: str|None, dry: bool) -> bool

    def store(self) -> Store:
        return Store(self.st.data_dir)

    def status(self) -> dict:
        s = self.store()
        runs = s.runs(1)
        sources = []
        for cfg in self.st.load_sources():
            sources.append({"id": cfg["id"], "name": cfg.get("name", cfg["id"]), "type": cfg.get("type")})
        return {
            "live": LIVE.as_dict(),
            "last_run": runs[0] if runs else None,
            "counts": s.counts(),
            "sources": sources,
            "config": {
                "wp_url": self.st.wp_url, "publish_status": self.st.publish_status, "run_at": self.st.run_at,
                "llm": f"{self.st.llm_provider} / {self.st.anthropic_model if self.st.llm_provider != 'openai' else self.st.openai_model}",
                "horizon_days": self.st.horizon_days, "skip_recurring": self.st.skip_recurring,
                "max_new_per_run": self.st.max_new_per_run, "telegram": bool(self.st.telegram_token),
            },
        }


def make_handler(app: App):
    st = app.st

    class H(BaseHTTPRequestHandler):
        server_version = "MEP-Eventi"

        def log_message(self, fmt, *args):  # niente log di ogni richiesta
            pass

        # --- auth facoltativa
        def _auth_ok(self) -> bool:
            if not st.web_password:
                return True
            hdr = self.headers.get("Authorization", "")
            if hdr.startswith("Basic "):
                try:
                    user, _, pwd = base64.b64decode(hdr[6:]).decode().partition(":")
                except Exception:  # noqa: BLE001
                    return False
                return hmac.compare_digest(user, st.web_user) and hmac.compare_digest(pwd, st.web_password)
            return False

        def _deny(self):
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Basic realm="MEP Eventi"')
            self.end_headers()

        def _send(self, code: int, body: bytes, ctype: str):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, data, code: int = 200):
            self._send(code, json.dumps(data, ensure_ascii=False, default=str).encode(), "application/json; charset=utf-8")

        def _body(self) -> dict:
            n = int(self.headers.get("Content-Length") or 0)
            if not n:
                return {}
            try:
                return json.loads(self.rfile.read(n))
            except json.JSONDecodeError:
                return {}

        # --- routing
        def do_GET(self):
            if not self._auth_ok():
                return self._deny()
            u = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            try:
                if u.path in ("/", "/index.html"):
                    return self._send(200, PAGE.encode(), "text/html; charset=utf-8")
                if u.path == "/api/status":
                    return self._json(app.status())
                if u.path == "/api/runs":
                    return self._json(app.store().runs(int(q.get("limit", 30))))
                if u.path == "/api/items":
                    return self._json(app.store().items(q.get("status") or None, q.get("source") or None,
                                                        q.get("q") or None, int(q.get("limit", 300))))
                if u.path == "/api/logs":
                    return self._json(RING.since(int(q.get("since", 0))))
                if u.path == "/health":
                    return self._send(200, b"ok", "text/plain")
                self._send(404, b"not found", "text/plain")
            except Exception as e:  # noqa: BLE001
                log.exception("errore web")
                self._json({"error": str(e)}, 500)

        def do_POST(self):
            if not self._auth_ok():
                return self._deny()
            u = urlparse(self.path)
            data = self._body()
            try:
                if u.path == "/api/run":
                    ok = app.start_run(data.get("source") or None, bool(data.get("dry")))
                    return self._json({"started": ok, "message": None if ok else "C'è già un giro in corso"})
                if u.path == "/api/items/retry":
                    app.store().reset_item(data["source_id"], data["uid"])
                    return self._json({"ok": True})
                self._send(404, b"not found", "text/plain")
            except Exception as e:  # noqa: BLE001
                log.exception("errore web")
                self._json({"error": str(e)}, 500)

    return H


def serve(st: Settings, start_run) -> threading.Thread:
    app = App(st, start_run)
    httpd = ThreadingHTTPServer(("0.0.0.0", st.web_port), make_handler(app))
    t = threading.Thread(target=httpd.serve_forever, name="web", daemon=True)
    t.start()
    log.info("Interfaccia web su http://0.0.0.0:%d%s", st.web_port, " (con password)" if st.web_password else "")
    return t


def is_running() -> bool:
    return RUN_LOCK.locked()
