"""Transactional append-only events and content-addressed artifacts.

Hash chaining detects edits; it is NOT tamper-proof against the machine owner.
Back up the database and retain published head hashes outside this directory.
"""
from __future__ import annotations

import json
import sqlite3
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path

from .common import canonical, digest, now, require, read_json


class Store:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "objects").mkdir(exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    time TEXT NOT NULL, kind TEXT NOT NULL, entity TEXT NOT NULL,
                    payload TEXT NOT NULL, previous TEXT NOT NULL, hash TEXT NOT NULL UNIQUE);
                CREATE TRIGGER IF NOT EXISTS no_event_update BEFORE UPDATE ON events
                BEGIN SELECT RAISE(ABORT, 'events are append-only'); END;
                CREATE TRIGGER IF NOT EXISTS no_event_delete BEFORE DELETE ON events
                BEGIN SELECT RAISE(ABORT, 'events are append-only'); END;
                CREATE TABLE IF NOT EXISTS claims (key TEXT PRIMARY KEY, time TEXT NOT NULL);
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.root / "ledger.sqlite", timeout=20)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def put(self, obj):
        key = digest(obj)
        p = self.root / "objects" / f"{key}.json"
        if p.exists():
            require(digest(read_json(p)) == key, "Artifact corruption detected")
        else:
            # Publish an entire object atomically; readers never observe a partial write.
            handle, temporary = tempfile.mkstemp(dir=p.parent, suffix=".pending")
            try:
                with os.fdopen(handle,"w",encoding="utf-8") as f:
                    f.write(canonical(obj))
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(temporary,p)
            finally:
                Path(temporary).unlink(missing_ok=True)
        return key

    def get(self, key):
        require(len(key) == 64 and all(c in "0123456789abcdef" for c in key), "Invalid artifact reference")
        value = read_json(self.root / "objects" / f"{key}.json")
        require(digest(value) == key, f"Artifact hash mismatch: {key}")
        return value

    def append(self, kind, entity, payload, claim=None, expected=None):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            for expected_kind,expected_entity,expected_hash in expected or []:
                current=db.execute("SELECT hash FROM events WHERE kind=? AND entity=? ORDER BY seq DESC LIMIT 1",(expected_kind,expected_entity)).fetchone()
                require((current[0] if current else None)==expected_hash,"Concurrent state change; refresh before retrying")
            if claim:
                try:
                    db.execute("INSERT INTO claims VALUES (?, ?)", (claim, now()))
                except sqlite3.IntegrityError:
                    raise ValueError(f"Already consumed: {claim}") from None
            last = db.execute("SELECT hash FROM events ORDER BY seq DESC LIMIT 1").fetchone()
            event = dict(time=now(), kind=kind, entity=entity, payload=payload, previous=last[0] if last else "0" * 64)
            event["hash"] = digest(event)
            cur = db.execute("INSERT INTO events(time,kind,entity,payload,previous,hash) VALUES(?,?,?,?,?,?)",
                             (event["time"], kind, entity, canonical(payload), event["previous"], event["hash"]))
            event["seq"] = cur.lastrowid
        return event

    def events(self, kind=None, entity=None):
        with self.connect() as db:
            clauses=[]
            args=[]
            for field,value in (("kind",kind),("entity",entity)):
                if value is not None:
                    clauses.append(field+"=?")
                    args.append(value)
            rows=db.execute("SELECT * FROM events"+(" WHERE "+" AND ".join(clauses) if clauses else "")+" ORDER BY seq",args).fetchall()
        return [{**dict(r), "payload": json.loads(r["payload"])} for r in rows]

    def latest(self, kind, entity):
        events = self.events(kind, entity)
        return events[-1] if events else None

    def verify(self):
        previous = "0" * 64
        events = self.events()
        for e in events:
            content = {k: e[k] for k in ("time", "kind", "entity", "payload", "previous")}
            require(e["previous"] == previous and digest(content) == e["hash"], f"Ledger broken at event {e['seq']}")
            previous = e["hash"]
        objects = list((self.root / "objects").glob("*.json"))
        for p in objects:
            self.get(p.stem)
        return {"events": len(events), "objects": len(objects), "head": previous, "valid": True}
