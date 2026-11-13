from dataclasses import asdict, dataclass
import math
from typing import Protocol

from .model import Record, digest
from .retrieval import Search


def text(value):
    return isinstance(value, str) and bool(value.strip())


def number(value):
    return type(value) in (int, float) and math.isfinite(value)


@dataclass(frozen=True)
class DecisionRequest:
    kind: str
    instructions: str
    state: str | dict | list
    criteria: dict[str, str] | list[str] | None = None
    family: str | None = None
    metric: str | None = None
    goal: str = "maximize"
    constraints: tuple[dict, ...] = ()
    minimum_confidence: float = 0.0

    def __post_init__(self):
        if self.kind not in ("choice", "score", "noul") or not text(self.instructions):
            raise ValueError("typed decision requires instructions")
        if not isinstance(self.state, (str, dict, list)):
            raise ValueError("state must be text, an object, or a list")
        if self.kind == "choice" and (
            not isinstance(self.criteria, dict) or not 2 <= len(self.criteria) <= 100
            or "none" in self.criteria or not all(text(k) and text(v) for k, v in self.criteria.items())
        ):
            raise ValueError("choice requires 2–100 named options, excluding 'none'")
        if self.kind == "score" and (not isinstance(self.criteria, list)
                                      or not 2 <= len(self.criteria) <= 100
                                      or not all(map(text, self.criteria))):
            raise ValueError("score requires 2–100 ordered levels")
        if self.kind == "noul" and self.criteria is not None:
            raise ValueError("noul uses instructions without a rubric")
        if self.family is not None or self.metric is not None:
            if self.kind != "choice" or not text(self.family) or not text(self.metric):
                raise ValueError("precedent decisions require a choice, family and metric")
        if self.goal not in ("maximize", "minimize"):
            raise ValueError("invalid outcome goal")
        if not number(self.minimum_confidence) or not 0 <= self.minimum_confidence <= 1:
            raise ValueError("invalid confidence threshold")
        if not isinstance(self.constraints, (list, tuple)):
            raise ValueError("constraints must be a list")
        for constraint in self.constraints:
            if (not isinstance(constraint, dict) or set(constraint) != {"field", "op", "value"}
                    or not text(constraint["field"]) or constraint["op"] not in ("eq", "min", "max")
                    or (constraint["op"] != "eq" and not number(constraint["value"]))):
                raise ValueError("invalid deterministic constraint")
        digest(asdict(self))

    def policy_failures(self) -> list[str]:
        failures = []
        for rule in self.constraints:
            key = rule["field"]
            op = rule["op"]
            expected = rule["value"]
            if not isinstance(self.state, dict) or key not in self.state:
                failures.append(key)
                continue
            actual = self.state[key]
            if op == "eq":
                accepted = type(actual) is type(expected) and actual == expected
            else:
                accepted = number(actual) and (actual >= expected if op == "min" else actual <= expected)
            if not accepted:
                failures.append(key)
        return failures


class ProviderUnavailable(Exception):
    """A configured provider could not give a valid answer."""


class Provider(Protocol):
    def decide(self, request: DecisionRequest, evidence: list[dict]) -> dict | None: ...


class PrecedentProvider(Protocol):
    def decide(self, request: DecisionRequest, cases: list[Record], search: Search) -> dict | None: ...


class Router:
    def __init__(self, search: Search, *, precedent: PrecedentProvider | None = None,
                 fallback: Provider | None = None):
        self.search = search
        self.precedent = precedent
        self.fallback = fallback

    def decide(self, request: DecisionRequest, *, revision=None, groups=None) -> dict:
        return self.decide_many({"sagekit": request}, revision=revision, groups=groups)["sagekit"]

    def decide_many(self, requests: dict[str, DecisionRequest], *, revision=None, groups=None,
                    context=None) -> dict[str, dict]:
        revision = revision if revision is not None else self.search.repo.snapshot()
        decisions = {}
        pending = {}
        for key, request in requests.items():
            envelope, evidence = self._resolve(request, revision, groups, context)
            decisions[key] = envelope
            if evidence is not None:
                pending[key] = (request, evidence)
        if pending and self.fallback:
            batch = getattr(self.fallback, "decide_many", None)
            if batch:
                try:
                    answers = batch(pending)
                except ProviderUnavailable:
                    answers = dict.fromkeys(pending, "unavailable")
            else:
                answers = {}
                for key, (request, evidence) in pending.items():
                    try:
                        answers[key] = self.fallback.decide(request, evidence)
                    except ProviderUnavailable:
                        answers[key] = "unavailable"
            for key in pending:
                result = answers.get(key)
                if result == "unavailable":
                    decisions[key]["attempts"].append({"provider": "jev", "status": "unavailable"})
                elif result:
                    decisions[key].update(result, status="answered")
                else:
                    decisions[key]["attempts"].append({"provider": "jev", "status": "abstained"})
        return decisions

    def _resolve(self, request: DecisionRequest, revision, groups, context) -> tuple[dict, list | None]:
        from .ledger import eligible_cases

        repo = self.search.repo
        envelope = {"schema": 1, "snapshot": revision, "request_id": digest(asdict(request)),
                    "kind": request.kind, "embedding_profile": self.search.embedder.profile.key,
                    "attempts": [], "evidence": []}
        failures = request.policy_failures()
        if failures:
            return {**envelope, "status": "denied", "provider": "policy", "failed_fields": failures}, None
        if self.precedent and request.family and request.minimum_confidence > 0:
            envelope["attempts"].append({"provider": "venn", "status": "uncalibrated"})
        elif self.precedent and request.family:
            cases = eligible_cases(repo, revision, groups, request.family, request.metric,
                                   request.criteria, context=context)
            try:
                result = self.precedent.decide(request, cases, self.search) if cases else None
            except ProviderUnavailable:
                envelope["attempts"].append({"provider": "venn", "status": "unavailable"})
            else:
                if result:
                    sources = {case.id: case.source.as_dict() for case in cases}
                    envelope["evidence"].extend({"id": key, "source": sources[key]}
                                                for key in result["evidence_ids"] if key in sources)
                    return {**envelope, **result, "status": "answered"}, None
                envelope["attempts"].append({"provider": "venn", "status": "insufficient"})
        evidence = self.search.query(request.instructions, revision=revision, groups=groups, context=context)
        envelope["evidence"] = [{"id": hit["record"]["id"], "source": hit["record"]["source"]}
                                for hit in evidence]
        return {**envelope, "status": "abstained", "provider": None}, evidence
