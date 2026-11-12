from pathlib import Path
import tempfile
import unittest

from sagekit.decisions import DecisionRequest, Router
from sagekit.ledger import approve, observe
from sagekit.model import Record, Source
from sagekit.providers import JevProvider, parse_answer
from sagekit.repository import LocalRepository
from sagekit.retrieval import Search


class DecisionTests(unittest.TestCase):
    def test_jev_response_types(self):
        for kind, criteria, answer, expected in (
            ("choice", {"a": "first", "b": "second"},
             {"choice": "a", "probabilities": {"a": .8, "b": .2}, "confidence": .6}, "a"),
            ("score", ["low", "high"],
             {"score": .8, "probabilities": {"0": .2, "1": .8}, "confidence": .6}, .8),
            ("noul", None, {"noul": .7}, .7),
        ):
            with self.subTest(kind=kind):
                request = DecisionRequest(kind, "Question", "Context", criteria)
                self.assertEqual(expected, parse_answer(request, {"type": kind, **answer})["value"])
        request = DecisionRequest("noul", "Question", "Context")
        with self.assertRaises(ValueError):
            parse_answer(request, {"type": "noul", "noul": float("nan")})

    def test_deterministic_policy_denies_before_calling_provider(self):
        with tempfile.TemporaryDirectory() as temp:
            request = DecisionRequest("noul", "release", {"failures": 2},
                                      constraints=({"field": "failures", "op": "max", "value": 0},))
            class Never:
                def decide(self, *args):
                    raise AssertionError("policy must run first")
            result = Router(Search(LocalRepository(Path(temp))), fallback=Never()).decide(request)
            self.assertEqual("denied", result["status"])
            self.assertEqual("policy", result["provider"])

    def test_only_linked_observed_outcomes_reach_precedent_provider(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = LocalRepository(Path(temp))
            source = Source("repo:run", "commit")
            choice = approve(repo, "checkout", "a", "checkout retry", "human", source)
            verified = Record("verified-change", "Verified checkout", "Success", source,
                              links=(choice.id,))
            repo.append(verified)
            request = DecisionRequest("choice", "checkout retry", "checkout retry",
                                      {"a": "retry", "b": "queue"}, family="checkout", metric="reliability")
            calls = []

            class Venn:
                def decide(self, request, cases, embedder):
                    calls.extend(cases)
                    return {"value": "a", "evidence_ids": [cases[0].id], "provider": "venn"}

            router = Router(Search(repo), precedent=Venn())
            self.assertEqual("abstained", router.decide(request)["status"])
            outcome = observe(repo, choice.id, verified.id, "reliability", 0.95, source)
            self.assertEqual("venn", router.decide(request)["provider"])
            self.assertEqual([outcome], calls)

    def test_private_evidence_is_excluded_from_hosted_jev(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = LocalRepository(Path(temp))
            repo.append(Record("incident", "checkout", "private checkout", Source("repo:incident", "c"),
                               acl=("sre",)))
            request = DecisionRequest("noul", "checkout", "public context")
            class Hosted(JevProvider):
                def call(self, payload):
                    self.payload = payload
                    return {"answers": {"sagekit": {"type": "noul", "noul": .8}}}
            provider = Hosted("https://api.typesafe.ai/v1/systemone", "key", "jev-test")
            result = Router(Search(repo), fallback=provider).decide(request, groups={"sre"})
            self.assertEqual("answered", result["status"])
            self.assertEqual([], provider.payload["state"]["evidence"])
