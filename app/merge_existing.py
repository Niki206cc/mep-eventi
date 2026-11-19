"""Unisce gli eventi già creati su giorni consecutivi in un solo evento su più giorni.

Uso (dentro il container):
    python -m app.merge_existing            # prova: mostra cosa farebbe
    python -m app.merge_existing --apply    # applica

Per ogni scheda importata con più eventi, raggruppa quelli in giorni consecutivi:
il primo evento del gruppo prende le date dal primo all'ultimo giorno, gli altri
vengono spostati nel cestino di WordPress (recuperabili).
"""
from __future__ import annotations

import argparse
import json
import logging
import time
from datetime import datetime

from .config import Settings
from .store import Store
from .wordpress import WordPress, WordPressError

log = logging.getLogger("merge")


def _dt(v: str) -> datetime:
    return datetime.strptime(v[:19], "%Y-%m-%d %H:%M:%S")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--pause", type=float, default=8)
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    st = Settings()
    store = Store(st.data_dir)
    wp = WordPress(st, store)

    rows = store.db.execute(
        "SELECT * FROM items WHERE status IN ('created','updated') AND wp_ids LIKE '%,%'").fetchall()
    log.info("schede con più eventi: %d", len(rows))
    merged = trashed = 0
    for row in rows:
        ids = store.wp_ids(row)
        evs = []
        for i in ids:
            try:
                e = wp._req("GET", f"/tribe/events/v1/events/{i}")
            except WordPressError as ex:
                log.info("  #%s non trovato (%s)", i, str(ex)[:60])
                continue
            evs.append({"id": i, "start": _dt(e["start_date"]), "end": _dt(e["end_date"]),
                        "all_day": e.get("all_day"), "status": e.get("status"), "title": e.get("title")})
        evs.sort(key=lambda x: x["start"])
        groups: list[list[dict]] = []
        for e in evs:
            if groups and (e["start"].date() - groups[-1][-1]["end"].date()).days <= 1:
                groups[-1].append(e)
            else:
                groups.append([e])
        keep_ids = []
        for g in groups:
            keep = g[0]
            keep_ids.append(keep["id"])
            if len(g) == 1:
                continue
            last = g[-1]
            log.info("%s: #%s %s -> %s, nel cestino %s", keep["title"][:60], keep["id"],
                     keep["start"], last["end"], [x["id"] for x in g[1:]])
            if not a.apply:
                continue
            wp._req("POST", f"/tribe/events/v1/events/{keep['id']}", json={
                "start_date": keep["start"].strftime("%Y-%m-%d %H:%M:%S"),
                "end_date": last["end"].strftime("%Y-%m-%d %H:%M:%S"),
                "all_day": bool(keep["all_day"]),
            })
            merged += 1
            time.sleep(a.pause)
            for x in g[1:]:
                wp._req("DELETE", f"/tribe/events/v1/events/{x['id']}")
                trashed += 1
                time.sleep(a.pause)
        if a.apply and len(keep_ids) != len(ids):
            store.save(row["source_id"], row["uid"], wp_ids=json.dumps(keep_ids))
    log.info("Fatto: %d eventi uniti, %d spostati nel cestino%s", merged, trashed, "" if a.apply else " (prova)")


if __name__ == "__main__":
    main()
