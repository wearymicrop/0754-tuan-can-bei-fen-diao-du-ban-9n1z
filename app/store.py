from contextlib import contextmanager
import json
import sqlite3

from .codec import canonical
from .errors import DomainError


class Ledger:
    def __init__(self, path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY, source TEXT NOT NULL, snapshot TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS signatures (
                    run_id TEXT PRIMARY KEY REFERENCES runs(id), receipt TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS amendments (
                    amendment_id TEXT PRIMARY KEY,
                    base_run TEXT NOT NULL REFERENCES runs(id),
                    run_id TEXT REFERENCES runs(id),
                    request TEXT NOT NULL, record TEXT NOT NULL
                );
            """)

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def save(self, ident, source, snapshot):
        with self.connect() as connection:
            inserted = connection.execute(
                "INSERT INTO runs VALUES (?, ?, ?) ON CONFLICT(id) DO NOTHING",
                (ident, canonical(source), canonical(snapshot)),
            )
            row = connection.execute("SELECT snapshot FROM runs WHERE id = ?", (ident,)).fetchone()
            return json.loads(row[0]), inserted.rowcount == 0

    def read(self, ident):
        with self.connect() as connection:
            row = connection.execute("SELECT source, snapshot FROM runs WHERE id = ?", (ident,)).fetchone()
            if row is None:
                raise DomainError("RUN_NOT_FOUND", "找不到此运行", 404)
            sign = connection.execute("SELECT receipt FROM signatures WHERE run_id = ?", (ident,)).fetchone()
            produced = connection.execute(
                "SELECT amendment_id, base_run FROM amendments WHERE run_id = ? AND run_id != base_run"
                " ORDER BY rowid LIMIT 1", (ident,)).fetchone()
            children = connection.execute(
                "SELECT amendment_id, run_id FROM amendments WHERE base_run = ? ORDER BY rowid", (ident,)).fetchall()
            snapshot = json.loads(row[1])
            lineage = {"amendment": produced[0] if produced else None,
                       "supersedes": produced[1] if produced else None,
                       "superseded_by": [{"amendment": key, "run": run} for key, run in children]}
            return json.loads(row[0]), {**snapshot, "lineage": lineage,
                                        "signature": json.loads(sign[0]) if sign else None}

    def recent(self):
        with self.connect() as connection:
            rows = connection.execute("SELECT snapshot FROM runs ORDER BY rowid DESC LIMIT 30").fetchall()
            return [json.loads(row[0])["manifest"] for row in rows]

    def sign(self, ident, receipt):
        data = canonical(receipt)
        with self.connect() as connection:
            inserted = connection.execute(
                "INSERT INTO signatures VALUES (?, ?) ON CONFLICT(run_id) DO NOTHING", (ident, data))
            saved = connection.execute("SELECT receipt FROM signatures WHERE run_id = ?", (ident,)).fetchone()[0]
            if saved != data:
                raise DomainError("ALREADY_SIGNED", "此运行已由他人签收", 409)
            return {**json.loads(saved), "reused": inserted.rowcount == 0}

    def get_amendment(self, amendment_id):
        with self.connect() as connection:
            row = connection.execute(
                "SELECT request, record FROM amendments WHERE amendment_id = ?", (amendment_id,)).fetchone()
            return None if row is None else {"request": row[0], "record": json.loads(row[1])}

    def record_amendment(self, amendment_id, base_run, run_id, request, source, snapshot, record):
        with self.connect() as connection:
            if run_id is not None:
                connection.execute(
                    "INSERT INTO runs VALUES (?, ?, ?) ON CONFLICT(id) DO NOTHING",
                    (run_id, canonical(source), canonical(snapshot)))
                saved = connection.execute("SELECT snapshot FROM runs WHERE id = ?", (run_id,)).fetchone()[0]
                if json.loads(saved)["manifest"]["digest"] != snapshot["manifest"]["digest"]:
                    raise DomainError("REPLAY_MISMATCH", "重算摘要不一致，请复核规则版本", 409)
            inserted = connection.execute(
                "INSERT INTO amendments VALUES (?, ?, ?, ?, ?) ON CONFLICT(amendment_id) DO NOTHING",
                (amendment_id, base_run, run_id, request, canonical(record)))
            row = connection.execute(
                "SELECT request, record FROM amendments WHERE amendment_id = ?", (amendment_id,)).fetchone()
            if row[0] != request:
                raise DomainError("AMENDMENT_CONFLICT", "补录单号已被不同内容占用", 409)
            return json.loads(row[1]), inserted.rowcount == 0

    def amendments_for(self, ident):
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT record FROM amendments WHERE base_run = ? ORDER BY rowid", (ident,)).fetchall()
            return [json.loads(row[0]) for row in rows]

    def amendment_of(self, ident):
        with self.connect() as connection:
            row = connection.execute(
                "SELECT record FROM amendments WHERE run_id = ? AND run_id != base_run"
                " ORDER BY rowid LIMIT 1", (ident,)).fetchone()
            return None if row is None else json.loads(row[0])
