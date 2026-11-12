from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from sagekit.application import Application, Principal
from sagekit.gates import pin, signed
from sagekit.model import digest
from sagekit.repository import LocalRepository
from test_foundation import record


class GateTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.repo = LocalRepository(Path(temp.name))
        self.key = b"fixture-receipt-key-at-least-32-bytes"
        self.app = Application(self.repo, receipt_key=self.key)
        self.identity = Principal(scopes=frozenset({"promote"}))
        self.evidence = record()
        revision = self.repo.append(self.evidence)
        self.pin = pin(revision, {"requirements": digest("requirements"), "architecture": digest("design")},
                       self.app.search.embedder.profile.key)
        self.payload = {
            "schema": 1, "pipeline": "forgekit", "run": "run-42", "pin": self.pin,
            "status": "success", "approved": True, "independently_verified": True,
            "verification": {"uri": "forge:receipt.json", "sha256": digest("forge evidence")},
            "change": {"kind": "architecture", "title": "Checkout decision",
                       "summary": "Verified idempotent checkout", "links": [self.evidence.id]},
        }

    def test_off_and_snapshot_pinning(self):
        self.assertEqual("skipped", self.app.gate_check(self.identity, {"mode": "off"})["status"])
        self.repo.append(record("later"))
        policy = {"mode": "required", "stage": "architecture", "query": self.evidence.id,
                  "exact_ids": [self.evidence.id]}
        result = self.app.gate_check(self.identity, policy, self.pin)
        self.assertTrue(result["allowed"])
        self.assertEqual(self.pin["revision"], result["snapshot"])
        bad = {**self.pin, "revision": self.repo.snapshot()}
        self.assertFalse(self.app.gate_check(self.identity, policy, bad)["allowed"])
        self.assertTrue(self.app.gate_check(self.identity, {**policy, "mode": "advisory"}, bad)["allowed"])
        different_profile = pin(self.pin["revision"], self.pin["inputs"], digest("different-profile"))
        self.assertFalse(self.app.gate_check(self.identity, policy, different_profile)["allowed"])

    def test_promotion_is_signed_idempotent_and_rejects_conflicting_run(self):
        with self.assertRaises(ValueError):
            self.app.promote(self.identity, {"payload": self.payload, "signature": "fake"})
        first = self.app.promote(self.identity, signed(self.payload, self.key))
        self.assertEqual(first, self.app.promote(self.identity, signed(self.payload, self.key)))
        changed = deepcopy(self.payload)
        changed["change"]["summary"] = "different content"
        with self.assertRaises(ValueError):
            self.app.promote(self.identity, signed(changed, self.key))
        self.assertEqual(2, len(self.repo.records()))
        self.assertEqual(1, len(self.repo.records(self.pin["revision"])))

    def test_signed_failure_cannot_publish(self):
        for field, value in (("status", "failure"), ("approved", False), ("independently_verified", False)):
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.app.promote(self.identity, signed({**self.payload, field: value}, self.key))
