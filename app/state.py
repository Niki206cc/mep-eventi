"""Stato condiviso tra il servizio pianificato e l'interfaccia web (stesso processo)."""
from __future__ import annotations

import logging
import threading
from collections import deque
from datetime import datetime

RUN_LOCK = threading.Lock()
STOP = threading.Event()        # richiesta di fermare il giro in corso (dashboard)
CONTINUOUS = threading.Event()  # scansione continua attiva


class Live:
    """Avanzamento del giro in corso, letto dalla dashboard."""

    def __init__(self):
        self._l = threading.Lock()
        self.reset()

    def reset(self):
        with getattr(self, "_l", threading.Lock()):
            self.running = False
            self.trigger = ""
            self.started_at = None
            self.source = ""
            self.done = 0
            self.total = 0
            self.current = ""
            self.next_run = getattr(self, "next_run", None)

    def update(self, **kw):
        with self._l:
            for k, v in kw.items():
                setattr(self, k, v)

    def as_dict(self) -> dict:
        with self._l:
            return {
                "running": self.running, "trigger": self.trigger,
                "started_at": self.started_at.isoformat(timespec="seconds") if self.started_at else None,
                "source": self.source, "done": self.done, "total": self.total, "current": self.current,
                "next_run": self.next_run.isoformat(timespec="minutes") if self.next_run else None,
            }


LIVE = Live()


class RingLog(logging.Handler):
    """Ultime righe di log in memoria, per la pagina Log."""

    def __init__(self, size: int = 1500):
        super().__init__()
        self.lines: deque[tuple[int, str, str]] = deque(maxlen=size)
        self.seq = 0
        self._l = threading.Lock()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
        except Exception:  # noqa: BLE001
            msg = record.getMessage()
        with self._l:
            self.seq += 1
            self.lines.append((self.seq, record.levelname, msg))

    def since(self, seq: int = 0, limit: int = 500) -> list[dict]:
        with self._l:
            rows = [r for r in self.lines if r[0] > seq]
        return [{"seq": s, "level": lv, "msg": m} for s, lv, m in rows[-limit:]]


RING = RingLog()
RING.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s", "%d/%m %H:%M:%S"))


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")
