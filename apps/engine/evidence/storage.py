from __future__ import annotations

import hashlib
from contextlib import contextmanager
import json
import os
from pathlib import Path
import sqlite3
from datetime import datetime, timezone
from uuid import uuid4


def now():
    return datetime.now(timezone.utc).isoformat()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False, default=str)


def digest(value):
    return hashlib.sha256(value if isinstance(value, bytes) else canonical(value).encode()).hexdigest()


def atomic_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    temp.write_text(canonical(value), encoding="utf-8")
    os.replace(temp, path)


class Store:
    def __init__(self, root="data"):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        with self.db() as con:
            con.executescript('''
                CREATE TABLE IF NOT EXISTS artifacts(id TEXT PRIMARY KEY, kind TEXT, body TEXT, created TEXT);
                CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT, artifact TEXT, action TEXT, body TEXT, created TEXT);
                CREATE TABLE IF NOT EXISTS holdouts(family TEXT PRIMARY KEY, strategy TEXT, run TEXT, created TEXT);
                CREATE TABLE IF NOT EXISTS requests(account TEXT, ts REAL);
                CREATE INDEX IF NOT EXISTS requests_account ON requests(account, ts);
                CREATE TRIGGER IF NOT EXISTS immutable_artifact_update BEFORE UPDATE ON artifacts BEGIN SELECT RAISE(ABORT, 'immutable'); END;
                CREATE TRIGGER IF NOT EXISTS immutable_artifact_delete BEFORE DELETE ON artifacts BEGIN SELECT RAISE(ABORT, 'immutable'); END;
                CREATE TRIGGER IF NOT EXISTS immutable_event_update BEFORE UPDATE ON events BEGIN SELECT RAISE(ABORT, 'immutable'); END;
                CREATE TRIGGER IF NOT EXISTS immutable_event_delete BEFORE DELETE ON events BEGIN SELECT RAISE(ABORT, 'immutable'); END;
            ''')

    @contextmanager
    def db(self):
        con = sqlite3.connect(self.root / "registry.sqlite", timeout=30)
        try:
            con.execute("PRAGMA journal_mode=WAL")
            with con:
                yield con
        finally:
            con.close()

    def put(self, kind, body):
        key = digest({"kind": kind, "body": body})
        with self.db() as con:
            con.execute("INSERT OR IGNORE INTO artifacts VALUES(?,?,?,?)", (key, kind, canonical(body), now()))
        return key

    def get(self, key, kind=None):
        with self.db() as con:
            row = con.execute("SELECT kind,body FROM artifacts WHERE id=?", (key,)).fetchone()
        if not row or (kind and row[0] != kind):
            raise ValueError("Artifact unavailable or wrong type")
        body = json.loads(row[1])
        if digest({"kind": row[0], "body": body}) != key:
            raise ValueError("Artifact integrity failure")
        return body

    def list(self, kind):
        with self.db() as con:
            return [{"id": r[0], "created": r[2], **json.loads(r[1])} for r in con.execute("SELECT id,body,created FROM artifacts WHERE kind=? ORDER BY created DESC", (kind,))]

    def event(self, key, action, body):
        with self.db() as con:
            con.execute("INSERT INTO events(artifact,action,body,created) VALUES(?,?,?,?)", (key, action, canonical(body), now()))

    def events(self, key):
        with self.db() as con:
            return [{"action": r[0], "body": json.loads(r[1]), "created": r[2]} for r in con.execute("SELECT action,body,created FROM events WHERE artifact=? ORDER BY seq", (key,))]

    def consume_holdout(self, family, strategy, run):
        with self.db() as con:
            try:
                con.execute("INSERT INTO holdouts VALUES(?,?,?,?)", (family, strategy, run, now()))
                con.execute("INSERT INTO events(artifact,action,body,created) VALUES(?,?,?,?)", (strategy, "holdout_access", canonical({"family": family, "run": run}), now()))
            except sqlite3.IntegrityError:
                raise ValueError("Holdout already consumed for this research family") from None

    def transition(self, key, state, reason):
        from .models import Hypothesis
        hypothesis = Hypothesis.model_validate(self.get(key, "hypothesis"))
        states = {"draft", "specified", "testing", "rejected", "inconclusive", "candidate for forward testing"}
        if state not in states or len(reason.strip()) < 5:
            raise ValueError("Valid state and substantive transition reason required")
        if state != "draft" and hypothesis.missing():
            raise ValueError("Hypothesis incomplete: " + ", ".join(hypothesis.missing()))
        self.event(key, "hypothesis_state", {"state": state, "reason": reason})
