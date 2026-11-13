from dataclasses import asdict
from pathlib import Path
import tempfile
import threading
import unittest

from sagekit.application import Application, Principal
from sagekit.decisions import DecisionRequest, ProviderUnavailable, Router
from sagekit.gates import pin, signed
from sagekit.model import Record, Source, digest
from sagekit.repository import LocalRepository
from sagekit.retrieval import Search
from sagekit.service import Remote, service


class Judgment:
    def __init__(self):
        self.calls = []
        self.values = {"noul": 0.9, "choice": "pass"}

    def decide(self, request, evidence):
        self.calls.append((request.kind, [hit["record"]["id"] for hit in evidence]))
        value = self.values.get(request.kind)
        if value is None:
            raise ProviderUnavailable("offline")
        return {"provider": "jev", "value": value, "confidence": 0.8}


class ContextualGates(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name)
        self.repo = LocalRepository(self.path)
        self.search = Search(self.repo)
        self.fallback = Judgment()
        self.app = Application(self.repo, self.search, Router(self.search, fallback=self.fallback))
        self.reviewer = Principal(scopes=frozenset({"write", "approve", "decide"}))
        self.scope = {"product": "storefront", "repository": "example/store", "component": "checkout"}
        self.request = {"kind": "noul", "instructions": "Checkout has approval", "state": {"ready": True}}
        self.policy = {
            "mode": "required", "stage": "release", "query": "Checkout has approval",
            "minimum_evidence": 0,
            "context": {"scope": self.scope, "as_of": "2026-11-13"},
            "questions": {"approval": {"request": self.request, "accept": {"op": "min", "value": 0.8}}},
        }

    def record(self, authority, value=None, scope=None, **options):
        knowledge = {"authority": authority, "scope": self.scope if scope is None else scope}
        if value is not None:
            knowledge["answer"] = {"request_id": digest(asdict(DecisionRequest(**self.request))), "value": value}
        knowledge.update(options.pop("knowledge", {}))
        return {
            "kind": "adr", "title": "Checkout has approval", "body": "Checkout approved",
            "source": {"uri": "git:policy", "revision": "a" * 40},
            "knowledge": knowledge, **options,
        }

    def add(self, authority, value=None, **options):
        return self.app.add(self.reviewer, self.record(authority, value, **options))["id"]

    def evaluate(self, policy=None, revision=None):
        pinned = pin(revision or self.repo.snapshot(), {"policy": digest("reviewed")},
                     self.search.embedder.profile.key)
        return self.app.gate_check(self.reviewer, policy or self.policy, pinned)

    def test_reuses_an_exact_approved_answer_and_persists_its_provenance(self):
        identifier = self.add("authoritative", 1, scope={"product": "storefront"})
        revision = self.repo.snapshot()
        result = self.evaluate()
        self.assertEqual("pass", result["disposition"])
        self.assertEqual([identifier], result["judgments"]["approval"]["evidence_ids"])
        self.assertEqual("authority", result["judgments"]["approval"]["provider"])
        self.assertEqual([], self.fallback.calls)
        reopened = LocalRepository(self.path).records(revision)
        self.assertEqual(identifier, reopened[0].id)
        self.assertEqual("authoritative", reopened[0].as_dict()["knowledge"]["authority"])
        legacy = Record("adr", "Legacy decision", "Text", Source("git:legacy", "1"))
        self.assertEqual("796f473908a682e6d77c1aaa7f6b31b40c7fc2e59845fb79e1d12e58cf4fcaaa",
                         legacy.id)

    def test_filters_out_of_scope_expired_superseded_and_candidate_records(self):
        expired = self.add("authoritative", 0, knowledge={"valid_until": "2026-11-13"})
        self.add("authoritative", 0, scope={**self.scope, "component": "billing"})
        self.add("candidate")
        old = self.add("precedent", knowledge={"valid_from": "2026-01-01"})
        current = self.add("precedent", supersedes=old, knowledge={"valid_from": "2026-02-01"})
        result = self.evaluate()
        self.assertEqual("pass", result["disposition"])
        self.assertEqual([("noul", [current])], self.fallback.calls)
        self.assertEqual({current}, {entry["id"] for entry in result["evidence"]})
        self.assertFalse(self.evaluate({**self.policy, "exact_ids": [expired]})["allowed"])

    def test_rejects_an_authoritative_write_or_supersession_without_approval(self):
        with self.assertRaises(PermissionError):
            self.app.add(Principal(scopes=frozenset({"write"})), self.record("authoritative", 1))
        identifier = self.add("authoritative", 1)
        with self.assertRaises(ValueError):
            self.add("candidate", supersedes=identifier)
        with self.assertRaises(ValueError):
            self.add("authoritative", 0, supersedes=identifier, scope={"product": "storefront"})
        with self.assertRaises(ValueError):
            self.add("candidate", 1)

    def test_conflict_and_failed_deterministic_constraints_cannot_reach_jev(self):
        first = self.add("authoritative", 1)
        earlier = self.repo.snapshot()
        self.add("authoritative", 0, scope={"product": "storefront"})
        conflict = self.evaluate()
        self.assertEqual("conflict", conflict["judgments"]["approval"]["status"])
        self.assertEqual("block", conflict["disposition"])
        self.assertTrue(self.evaluate(revision=earlier)["allowed"])
        denied_request = {**self.request, "constraints": [{"field": "ready", "op": "eq", "value": False}]}
        denied = self.evaluate({**self.policy, "questions": {
            "approval": {"request": denied_request, "accept": {"op": "min", "value": 0.8}},
        }})
        self.assertEqual("denied", denied["judgments"]["approval"]["status"])
        self.assertEqual("block", denied["disposition"])
        self.assertEqual([], self.fallback.calls)
        self.assertIn(first, conflict["judgments"]["approval"]["evidence_ids"])

    def test_multiple_questions_reject_jev_outage_and_a_negative_answer(self):
        policy = {**self.policy, "questions": {
            **self.policy["questions"],
            "release": {"request": {"kind": "choice", "instructions": "Recommend next step",
                                    "state": {}, "criteria": {"pass": "Continue", "hold": "Stop"}},
                        "accept": {"op": "eq", "value": "pass"}},
        }}
        self.fallback.values.clear()
        self.assertEqual("unavailable", self.evaluate(policy)["status"])
        self.fallback.values = {"noul": 0.9, "choice": "hold"}
        rejected = self.evaluate(policy)
        self.assertEqual("block", rejected["disposition"])
        self.assertEqual("accepted", rejected["judgments"]["approval"]["status"])
        self.assertEqual("rejected", rejected["judgments"]["release"]["status"])

    def test_scoped_venn_cases_come_from_verified_operational_outcomes(self):
        class Venn:
            def decide(self, request, cases, search):
                return {"provider": "venn", "value": "pass", "evidence_ids": [case.id for case in cases]}

        self.app.router.precedent = Venn()
        principal = Principal(scopes=frozenset({"approve", "observe"}))
        source = Source("git:operations", "2")
        case_ids = []
        for repository in ("example/store", "example/different"):
            choice = self.app.approve(principal, "checkout", "pass", "checkout behavior", "human",
                                      source.as_dict(), knowledge={
                                          "authority": "precedent",
                                          "scope": {"repository": repository},
                                      })
            verification = Record("verified-change", "Release verified", "Checks passed", source,
                                  links=(choice["id"],))
            self.app.append(verification)
            case = self.app.observe(principal, choice["id"], verification.id, "uptime", 0.9,
                                    source.as_dict())
            case_ids.append(case["id"])
        result = self.evaluate({**self.policy, "questions": {
            "release": {"request": {"kind": "choice", "instructions": "Recommend next step",
                                    "state": {}, "criteria": {"pass": "Continue", "hold": "Stop"},
                                    "family": "checkout", "metric": "uptime"},
                        "accept": {"op": "eq", "value": "pass"}},
        }})
        self.assertEqual("pass", result["disposition"])
        self.assertEqual("venn", result["judgments"]["release"]["provider"])
        self.assertEqual([case_ids[0]], result["judgments"]["release"]["evidence_ids"])
        self.assertEqual([], self.fallback.calls)

    def test_signed_promotion_publishes_scoped_precedent_only(self):
        key = b"protected-test-key-of-at-least-32-bytes"
        self.app.receipt_key = key
        principal = Principal(scopes=frozenset({"promote"}))
        payload = {
            "schema": 1, "pipeline": "example/store", "run": "42",
            "pin": pin(self.repo.snapshot(), {"policy": digest("reviewed")}, self.search.embedder.profile.key),
            "status": "success", "approved": True, "independently_verified": True,
            "verification": {"uri": "git:receipt", "sha256": digest("receipt")},
            "change": {"kind": "architecture", "title": "Checkout has approval", "summary": "Verified",
                       "knowledge": {"authority": "authoritative", "scope": self.scope}},
        }
        with self.assertRaises(ValueError):
            self.app.promote(principal, signed(payload, key))
        payload["change"]["knowledge"]["authority"] = "precedent"
        receipt = signed(payload, key)
        result = self.app.promote(principal, receipt)
        self.assertEqual(result, self.app.promote(principal, receipt))
        self.assertEqual("pass", self.evaluate({**self.policy, "exact_ids": [result["id"]]})["disposition"])
        self.assertEqual([("noul", [result["id"]])], self.fallback.calls)

    def test_http_gate_matches_the_local_result(self):
        self.add("authoritative", 1)
        self.app.add(Principal(frozenset({"restricted"}), self.reviewer.scopes),
                     self.record("authoritative", 0, acl=["restricted"]))
        pinned = pin(self.repo.snapshot(), {"policy": digest("reviewed")}, self.search.embedder.profile.key)
        with service(self.app, {"reader": {"scopes": ["decide"]}}, port=0) as server:
            worker = threading.Thread(target=server.serve_forever)
            worker.start()
            try:
                remote = Remote(f"http://127.0.0.1:{server.server_port}", "reader")
                self.assertEqual(self.evaluate(), remote.dispatch("gate-check", {
                    "policy": self.policy, "pin": pinned,
                }))
            finally:
                server.shutdown()
                worker.join()
