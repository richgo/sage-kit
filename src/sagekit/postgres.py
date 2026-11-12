import json

from .model import Record, encode
from .repository import EMPTY_REVISION, make_event, validate_append, visible_records


class PostgresRepository:
    """Transactional remote repository. All instances share the same event log."""

    def __init__(self, dsn: str):
        import psycopg

        self.connect = psycopg.connect
        self.dsn = dsn
        with self.connect(dsn) as db:
            self._lock(db)
            db.execute("""CREATE TABLE IF NOT EXISTS sagekit_events (
                position BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                revision TEXT UNIQUE NOT NULL, record_id TEXT UNIQUE NOT NULL,
                payload TEXT NOT NULL)""")

    @staticmethod
    def _lock(db):
        db.execute("SELECT pg_advisory_xact_lock(794477912)")

    def append(self, record: Record) -> str:
        with self.connect(self.dsn) as db:
            self._lock(db)
            rows = list(db.execute("SELECT revision, payload FROM sagekit_events ORDER BY position"))
            previous = {}
            for revision, payload in rows:
                item = Record.from_dict(json.loads(payload))
                if item.id == record.id:
                    return revision
                previous[item.id] = item
            validate_append(record, previous, {item.supersedes for item in previous.values()})
            event = make_event(record, rows[-1][0] if rows else EMPTY_REVISION)
            db.execute("INSERT INTO sagekit_events (revision, record_id, payload) VALUES (%s, %s, %s)",
                       (event["revision"], record.id, encode(record.as_dict())))
            return event["revision"]

    def snapshot(self) -> str:
        with self.connect(self.dsn) as db:
            row = db.execute("SELECT revision FROM sagekit_events ORDER BY position DESC LIMIT 1").fetchone()
            return row[0] if row else EMPTY_REVISION

    def records(self, revision=None, groups=None, *, history=False) -> list[Record]:
        if revision == EMPTY_REVISION:
            return []
        with self.connect(self.dsn) as db:
            if revision is None:
                rows = db.execute("SELECT payload FROM sagekit_events ORDER BY position")
            else:
                rows = db.execute("""
                    SELECT payload FROM sagekit_events
                    WHERE position <= (SELECT position FROM sagekit_events WHERE revision = %s)
                    ORDER BY position""", (revision,))
            records = [Record.from_dict(json.loads(row[0])) for row in rows]
        if revision is not None and not records:
            raise ValueError("unknown corpus snapshot")
        return visible_records(records, groups, history)
