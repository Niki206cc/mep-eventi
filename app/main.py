"""Avvio: `python -m app.main` (servizio con pianificazione + interfaccia web) oppure `--once` / `--dry-run`."""
from __future__ import annotations

import argparse
import logging
import sys
import threading
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .config import Settings
from .pipeline import Pipeline
from .state import LIVE, RING, RUN_LOCK
from .store import Store

log = logging.getLogger("mep-eventi")


def next_run(now: datetime, times: list[str]) -> datetime:
    candidates = []
    for t in times:
        try:
            h, m = (int(x) for x in t.split(":")[:2])
        except ValueError:
            continue
        c = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if c <= now:
            c += timedelta(days=1)
        candidates.append(c)
    return min(candidates) if candidates else now + timedelta(days=1)


def run_once(st: Settings, dry: bool, source: str | None, limit: int | None, trigger: str = "pianificato") -> bool:
    """Esegue un giro se non ce n'è già uno in corso. Ritorna False se occupato."""
    if not RUN_LOCK.acquire(blocking=False):
        log.warning("giro già in corso: richiesta ignorata")
        return False
    try:
        Pipeline(st, dry_run=dry).run(only_source=source, limit=limit, trigger=trigger)
    except Exception:  # noqa: BLE001
        log.exception("esecuzione fallita")
    finally:
        RUN_LOCK.release()
    return True


def setup_logging(level: str) -> None:
    logging.basicConfig(level=level.upper(), stream=sys.stdout,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger().addHandler(RING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Import eventi su Montagne & Paesi (The Events Calendar)")
    ap.add_argument("--once", action="store_true", help="esegue un solo giro ed esce")
    ap.add_argument("--dry-run", action="store_true", help="non scrive su WordPress: stampa cosa farebbe")
    ap.add_argument("--source", help="solo questa fonte (id in sources.yaml)")
    ap.add_argument("--limit", type=int, help="massimo N eventi per fonte (per i test)")
    args = ap.parse_args(argv)

    st = Settings()
    setup_logging(st.log_level)

    if args.once or args.dry_run:
        run_once(st, args.dry_run, args.source, args.limit, trigger="manuale (console)")
        return 0

    Store(st.data_dir).mark_interrupted_runs()
    wake = threading.Event()

    def start_from_web(source: str | None, dry: bool) -> bool:
        if RUN_LOCK.locked():
            return False
        threading.Thread(target=run_once, args=(st, dry, source, None, "manuale (web)" + (" prova" if dry else "")),
                         daemon=True, name="run-web").start()
        return True

    if st.web_enabled:
        from .web import serve
        serve(st, start_from_web)

    tz = ZoneInfo(st.timezone)
    log.info("Servizio avviato. Esecuzioni alle %s (%s)", ", ".join(st.run_at), st.timezone)
    if st.run_on_start:
        run_once(st, False, args.source, args.limit, trigger="avvio")
    while True:
        nxt = next_run(datetime.now(tz), st.run_at)
        LIVE.update(next_run=nxt)
        log.info("Prossima esecuzione: %s", nxt.strftime("%d/%m/%Y %H:%M"))
        while (remaining := (nxt - datetime.now(tz)).total_seconds()) > 0:
            wake.wait(min(remaining, 60))
        run_once(st, False, args.source, args.limit)


if __name__ == "__main__":
    sys.exit(main())
