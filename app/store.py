"""Stato persistente (SQLite in /data): eventi già importati, cache di luoghi/categorie, impronte anti-duplicato."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    source_id TEXT NOT NULL,
    uid TEXT NOT NULL,
    url TEXT,
    title TEXT,
    content_hash TEXT,
    status TEXT,
    wp_ids TEXT DEFAULT '[]',
    media_id INTEGER,
    attempts INTEGER DEFAULT 0,
    note TEXT,
    first_seen TEXT,
    last_seen TEXT,
    PRIMARY KEY (source_id, uid)
);
CREATE TABLE IF NOT EXISTS fingerprints (
    day TEXT NOT NULL,
    city TEXT,
    title TEXT,
    wp_id INTEGER,
    source_id TEXT,
    uid TEXT
);
CREATE INDEX IF NOT EXISTS fp_day ON fingerprints(day);
CREATE TABLE IF NOT EXISTS cache (
    kind TEXT NOT NULL,
    key TEXT NOT NULL,
    wp_id INTEGER,
    PRIMARY KEY (kind, key)
);
"""

FINAL = {"created", "updated", "duplicate", "not_event", "past", "recurring_skipped", "out_of_horizon", "no_dates"}


class Store:
    def __init__(self, data_dir: Path):
        data_dir.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(data_dir / "state.db")
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self.db.commit()

    def get(self, source_id: str, uid: str) -> sqlite3.Row | None:
        return self.db.execute("SELECT * FROM items WHERE source_id=? AND uid=?", (source_id, uid)).fetchone()

    def save(self, source_id: str, uid: str, **fields) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        row = self.get(source_id, uid)
        if "wp_ids" in fields and not isinstance(fields["wp_ids"], str):
            fields["wp_ids"] = json.dumps(fields["wp_ids"])
        fields["last_seen"] = now
        if row is None:
            fields.setdefault("first_seen", now)
            cols = ["source_id", "uid", *fields.keys()]
            self.db.execute(
                f"INSERT INTO items ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                (source_id, uid, *fields.values()),
            )
        else:
            sets = ",".join(f"{k}=?" for k in fields)
            self.db.execute(f"UPDATE items SET {sets} WHERE source_id=? AND uid=?", (*fields.values(), source_id, uid))
        self.db.commit()

    def wp_ids(self, row) -> list[int]:
        try:
            return json.loads(row["wp_ids"] or "[]")
        except (TypeError, json.JSONDecodeError):
            return []

    # --- anti-duplicato tra fonti diverse
    def fingerprints_on(self, day: str) -> list[sqlite3.Row]:
        return self.db.execute("SELECT * FROM fingerprints WHERE day=?", (day,)).fetchall()

    def add_fingerprint(self, day: str, city: str, title: str, wp_id: int | None, source_id: str, uid: str) -> None:
        self.db.execute("INSERT INTO fingerprints VALUES (?,?,?,?,?,?)", (day, city, title, wp_id, source_id, uid))
        self.db.commit()

    # --- cache id WordPress
    def cache_get(self, kind: str, key: str) -> int | None:
        r = self.db.execute("SELECT wp_id FROM cache WHERE kind=? AND key=?", (kind, key)).fetchone()
        return r["wp_id"] if r else None

    def cache_set(self, kind: str, key: str, wp_id: int) -> None:
        self.db.execute("INSERT OR REPLACE INTO cache VALUES (?,?,?)", (kind, key, wp_id))
        self.db.commit()
