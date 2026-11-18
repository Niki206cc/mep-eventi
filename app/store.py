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
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started TEXT,
    finished TEXT,
    trigger TEXT,
    status TEXT,
    created INTEGER DEFAULT 0,
    updated INTEGER DEFAULT 0,
    skipped INTEGER DEFAULT 0,
    errors INTEGER DEFAULT 0,
    per_source TEXT DEFAULT '{}',
    report TEXT
);
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
        self.db = sqlite3.connect(data_dir / "state.db", check_same_thread=False, timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(SCHEMA)
        cols = {r["name"] for r in self.db.execute("PRAGMA table_info(items)")}
        for col in ("event_date", "city", "source_name", "image_url"):
            if col not in cols:
                self.db.execute(f"ALTER TABLE items ADD COLUMN {col} TEXT")
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

    # --- giri (per la dashboard)
    def start_run(self, trigger: str) -> int:
        cur = self.db.execute("INSERT INTO runs (started, trigger, status) VALUES (?,?,?)",
                              (datetime.now().isoformat(timespec="seconds"), trigger, "running"))
        self.db.commit()
        return cur.lastrowid

    def finish_run(self, run_id: int, status: str, created=0, updated=0, skipped=0, errors=0,
                   per_source: dict | None = None, report: str = "") -> None:
        self.db.execute(
            "UPDATE runs SET finished=?, status=?, created=?, updated=?, skipped=?, errors=?, per_source=?, report=? WHERE id=?",
            (datetime.now().isoformat(timespec="seconds"), status, created, updated, skipped, errors,
             json.dumps(per_source or {}, ensure_ascii=False), report, run_id),
        )
        self.db.commit()

    def runs(self, limit: int = 30) -> list[dict]:
        rows = self.db.execute("SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            try:
                d["per_source"] = json.loads(d.get("per_source") or "{}")
            except json.JSONDecodeError:
                d["per_source"] = {}
            out.append(d)
        return out

    def mark_interrupted_runs(self) -> None:
        self.db.execute("UPDATE runs SET status='interrotto' WHERE status='running'")
        self.db.commit()

    def items(self, status: str | None = None, source: str | None = None, q: str | None = None,
              limit: int = 300) -> list[dict]:
        sql, args = "SELECT * FROM items WHERE 1=1", []
        if status:
            sql += " AND status=?"
            args.append(status)
        if source:
            sql += " AND source_id=?"
            args.append(source)
        if q:
            sql += " AND (title LIKE ? OR url LIKE ? OR note LIKE ?)"
            args += [f"%{q}%"] * 3
        sql += " ORDER BY last_seen DESC LIMIT ?"
        args.append(limit)
        out = []
        for r in self.db.execute(sql, args).fetchall():
            d = dict(r)
            d["wp_ids"] = self.wp_ids(r)
            out.append(d)
        return out

    def counts(self) -> dict:
        by_status = {r["status"]: r["n"] for r in self.db.execute("SELECT status, COUNT(*) n FROM items GROUP BY status")}
        by_source = {}
        for r in self.db.execute("SELECT source_id, status, COUNT(*) n FROM items GROUP BY source_id, status"):
            by_source.setdefault(r["source_id"], {})[r["status"]] = r["n"]
        return {"by_status": by_status, "by_source": by_source}

    def reset_item(self, source_id: str, uid: str) -> None:
        """Fa rielaborare l'elemento al prossimo giro (non cancella gli eventi già creati)."""
        self.db.execute("UPDATE items SET content_hash=NULL, attempts=0, status=CASE WHEN status IN ('created','updated') "
                        "THEN status ELSE 'retry' END WHERE source_id=? AND uid=?", (source_id, uid))
        self.db.commit()
