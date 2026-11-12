from contextlib import contextmanager
from pathlib import Path
import json
import os
import sqlite3
import tempfile
from typing import Protocol

from .model import Record, digest, encode

EMPTY_REVISION = "0" * 64


class Repository(Protocol):
    def append(self, record: Record) -> str: ...
    def snapshot(self) -> str: ...
    def records(self, revision: str | None = None, groups: set[str] | None = None,
                *, history: bool = False) -> list[Record]: ...


def validate_append(record: Record, previous: dict[str, Record], replaced: set[str]) -> None:
    for identifier in record.links:
        target = previous.get(identifier)
        if target is None or (target.acl and not (record.acl and set(record.acl) <= set(target.acl))):
            raise ValueError("unknown or less visible linked record")
    if record.supersedes:
        target = previous.get(record.supersedes)
        if target is None or target.kind != record.kind or target.acl != record.acl:
            raise ValueError("supersession requires a record with the same kind and ACL")
        if target.id in replaced:
            raise ValueError("record already superseded")


def visible_records(records: list[Record], groups: set[str] | None,
                    history: bool) -> list[Record]:
    active_groups = groups or set()
    replaced = {record.supersedes for record in records}
    return [
        record for record in records
        if (history or record.id not in replaced)
        and (not record.acl or active_groups.intersection(record.acl))
    ]


def make_event(record: Record, parent: str) -> dict:
    payload = {"parent": parent, "record": record.as_dict()}
    return {**payload, "revision": digest(payload)}


def parse_journal(contents: str) -> list[dict]:
    events = []
    parent = EMPTY_REVISION
    previous = {}
    replaced = set()
    for line in contents.splitlines():
        event = json.loads(line)
        record = Record.from_dict(event["record"])
        if event != make_event(record, parent) or record.id in previous:
            raise ValueError("invalid corpus event chain")
        validate_append(record, previous, replaced)
        events.append(event)
        parent = event["revision"]
        previous[record.id] = record
        replaced.add(record.supersedes)
    return events


def atomic_text(path: Path, contents: str) -> None:
    fd, name = tempfile.mkstemp(prefix=".sagekit-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as file:
            file.write(contents)
            file.flush()
            os.fsync(file.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


class LocalRepository:
    """Git-track the journal. SQLite serializes local writers and projects its events."""

    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.journal = self.root / "knowledge.jsonl"
        cache = self.root / ".sagekit"
        cache.mkdir(exist_ok=True)
        self.database = cache / "projection.sqlite3"

    @contextmanager
    def _transaction(self):
        db = sqlite3.connect(self.database, timeout=30)
        try:
            with db:
                db.execute("BEGIN IMMEDIATE")
                db.execute("""CREATE TABLE IF NOT EXISTS events (
                    position INTEGER PRIMARY KEY, revision TEXT UNIQUE NOT NULL,
                    record_id TEXT UNIQUE NOT NULL, payload TEXT NOT NULL)""")
                contents = self.journal.read_text(encoding="utf-8") if self.journal.exists() else ""
                events = parse_journal(contents)
                revisions = [row[0] for row in db.execute(
                    "SELECT revision FROM events ORDER BY position")]
                if revisions != [event["revision"] for event in events]:
                    db.execute("DELETE FROM events")
                    for index, event in enumerate(events, 1):
                        self._insert(db, index, event)
                yield db, events
        finally:
            db.close()

    @staticmethod
    def _insert(db, index, event):
        db.execute("INSERT INTO events VALUES (?, ?, ?, ?)",
                   (index, event["revision"], event["record"]["id"], encode(event["record"])))

    def append(self, record: Record) -> str:
        with self._transaction() as (db, events):
            prior = db.execute("SELECT revision FROM events WHERE record_id = ?",
                               (record.id,)).fetchone()
            if prior:
                return prior[0]
            previous = {event["record"]["id"]: Record.from_dict(event["record"]) for event in events}
            validate_append(record, previous, {item.supersedes for item in previous.values()})
            parent = events[-1]["revision"] if events else EMPTY_REVISION
            event = make_event(record, parent)
            self._insert(db, len(events) + 1, event)
            atomic_text(self.journal, "".join(encode(item) + "\n" for item in [*events, event]))
            return event["revision"]

    def snapshot(self) -> str:
        with self._transaction() as (_, events):
            return events[-1]["revision"] if events else EMPTY_REVISION

    def records(self, revision=None, groups=None, *, history=False) -> list[Record]:
        with self._transaction() as (db, events):
            position = len(events)
            if revision == EMPTY_REVISION:
                return []
            if revision is not None:
                row = db.execute("SELECT position FROM events WHERE revision = ?", (revision,)).fetchone()
                if row is None:
                    raise ValueError("unknown corpus snapshot")
                position = row[0]
            rows = db.execute("SELECT payload FROM events WHERE position <= ? ORDER BY position",
                              (position,))
            records = [Record.from_dict(json.loads(row[0])) for row in rows]
            return visible_records(records, groups, history)
