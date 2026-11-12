from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from sagekit.repository import LocalRepository
from test_foundation import record


class EdgeCases(unittest.TestCase):
    def test_unicode_line_separators_do_not_split_journal_events(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = LocalRepository(Path(temp))
            entry = record("line\u2028paragraph\u2029next\u0085last")
            repo.append(entry)
            self.assertEqual([entry], repo.records())

    def test_projection_can_be_rebuilt_if_payload_is_modified(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = LocalRepository(Path(temp))
            entry = record("confidential", acl=("sre",))
            repo.append(entry)
            with closing(sqlite3.connect(repo.database)) as db, db:
                db.execute("UPDATE events SET payload = ?", (json.dumps(record("altered").as_dict()),))
            self.assertEqual([], repo.records())
            self.assertEqual([entry], repo.records(groups={"sre"}))

    def test_concurrent_local_writers_do_not_drop_events(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = LocalRepository(Path(temp))
            records = [record(str(index)) for index in range(12)]
            with ThreadPoolExecutor(max_workers=4) as pool:
                revisions = list(pool.map(repo.append, records))
            self.assertEqual(12, len(set(revisions)))
            self.assertEqual({item.id for item in records}, {item.id for item in repo.records()})

    def test_off_gate_does_not_contact_the_remote(self):
        with tempfile.TemporaryDirectory() as temp:
            policy = Path(temp) / "policy.json"
            policy.write_text('{"mode":"off"}')
            result = subprocess.run([sys.executable, "-m", "sagekit", "--remote",
                                     "http://127.0.0.1:1", "gate-check", str(policy)],
                                    capture_output=True, text=True, env={**os.environ, "SAGEKIT_TOKEN": ""})
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual("skipped", json.loads(result.stdout)["status"])

    def test_advisory_remote_outage_returns_auditable_result(self):
        with tempfile.TemporaryDirectory() as temp:
            policy = Path(temp) / "policy.json"
            policy.write_text('{"mode":"advisory","stage":"test","query":"test evidence"}')
            command = [sys.executable, "-m", "sagekit", "--remote", "http://127.0.0.1:1",
                       "gate-check", str(policy)]
            env = {**os.environ, "SAGEKIT_TOKEN": "fixture-token"}
            result = subprocess.run(command, capture_output=True, text=True, env=env)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual("unavailable", json.loads(result.stdout)["status"])
            policy.write_text('{"mode":"required","stage":"test","query":"test evidence"}')
            blocked = subprocess.run(command, capture_output=True, text=True, env=env)
            self.assertEqual(2, blocked.returncode, blocked.stderr)
            self.assertFalse(json.loads(blocked.stdout)["allowed"])
