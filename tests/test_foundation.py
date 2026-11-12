import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from sagekit.model import Record, Source
from sagekit.repository import LocalRepository


def record(body="first decision", acl=(), supersedes=None, kind="adr", **metadata):
    return Record(kind, "checkout", body, Source("repo:docs/checkout.md", "abc123"),
                  acl=acl, supersedes=supersedes, metadata=metadata)


class FoundationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = LocalRepository(self.root)

    def test_idempotent_append_and_rebuild(self):
        entry = record()
        revision = self.repo.append(entry)
        self.assertEqual(revision, self.repo.append(entry))
        self.assertEqual([entry], self.repo.records())
        self.repo.database.unlink()
        self.assertEqual([entry], self.repo.records())

    def test_acl_supersession_and_pinned_snapshot(self):
        first = record(acl=("payments",))
        old = self.repo.append(first)
        updated = record("new decision", ("payments",), first.id)
        self.repo.append(updated)
        self.assertEqual([], self.repo.records())
        self.assertEqual([first], self.repo.records(old, {"payments"}))
        self.assertEqual([updated], self.repo.records(groups={"payments"}))
        with self.assertRaises(ValueError):
            self.repo.append(record("other", (), updated.id))
        with self.assertRaises(ValueError):
            self.repo.append(record("fork", ("payments",), first.id))

    def test_journal_corruption_is_detected(self):
        self.repo.append(record())
        self.repo.journal.write_text(self.repo.journal.read_text().replace("first", "fake"))
        with self.assertRaises(ValueError):
            self.repo.records()

    def test_cli_can_write_and_read(self):
        source = self.root / "record.json"
        source.write_text(json.dumps(record().as_dict()))
        base = [sys.executable, "-m", "sagekit", "--root", str(self.root)]
        subprocess.run(base + ["add", str(source)], check=True, capture_output=True)
        result = subprocess.check_output(base + ["list"], text=True)
        self.assertEqual(json.loads(result), [record().as_dict()])
