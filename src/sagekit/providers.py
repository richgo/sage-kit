import math

from .decisions import DecisionRequest, ProviderUnavailable, number
from .http import check_endpoint, post_json
from .model import encode
from .vectors import Vector


def probability(value):
    return number(value) and 0 <= value <= 1


def parse_answer(request: DecisionRequest, raw: dict) -> dict:
    kind = request.kind
    if not isinstance(raw, dict) or raw.get("type") != kind:
        raise ValueError("provider returned the wrong answer type")
    value = raw[kind]
    if kind == "noul":
        if not probability(value):
            raise ValueError("invalid Noul probability")
        return {"value": value, "confidence": abs(2 * value - 1)}
    labels = set(request.criteria) if kind == "choice" else set(map(str, range(len(request.criteria))))
    distribution = raw["probabilities"]
    confidence = raw["confidence"]
    if (not isinstance(distribution, dict) or set(distribution) != labels
            or not all(map(probability, distribution.values()))
            or not math.isclose(sum(distribution.values()), 1.0, abs_tol=1e-4)
            or not probability(confidence)):
        raise ValueError("invalid probability distribution")
    if kind == "choice":
        if not isinstance(value, str) or value not in labels or distribution[value] != max(distribution.values()):
            raise ValueError("invalid Choice selection")
    elif not number(value) or not 0 <= value <= len(labels) - 1:
        raise ValueError("invalid Score")
    return {"value": value, "confidence": confidence, "probabilities": distribution}


class JevProvider:
    """TypeSafe System One protocol, shared with local Jev-compatible endpoints."""

    def __init__(self, endpoint: str, api_key: str | None, model: str | None = None,
                 *, allow_restricted_evidence: bool = False):
        self.local = check_endpoint(endpoint)
        if not self.local and not api_key:
            raise ValueError("hosted Jev requires an API key")
        self.allow_restricted_evidence = self.local and allow_restricted_evidence
        self.endpoint = endpoint
        self.api_key = api_key
        self.model = model

    def call(self, payload: dict) -> dict:
        return post_json(self.endpoint, payload, self.api_key)

    def decide(self, request: DecisionRequest, evidence: list[dict]) -> dict | None:
        result = self.decide_many({"sagekit": (request, evidence)})["sagekit"]
        if result == "unavailable":
            raise ProviderUnavailable("Jev request failed or returned an invalid answer")
        return result

    def decide_many(self, requests: dict[str, tuple[DecisionRequest, list[dict]]]) -> dict:
        batches = {}
        for key, (request, evidence) in requests.items():
            records = [item["record"] for item in evidence
                       if self.allow_restricted_evidence or not item["record"]["acl"]]
            state = {"context": request.state, "evidence": records}
            _, batch = batches.setdefault(encode(state), (state, {}))
            batch[key] = request
        answers = {}
        for state, batch in batches.values():
            answers.update(self._call_batch(state, batch))
        return answers

    def _call_batch(self, state, requests):
        questions = {}
        for key, request in requests.items():
            question = {"type": request.kind, "instructions": request.instructions}
            if request.criteria is not None:
                question["criteria"] = request.criteria
            questions[key] = question
        payload = {"state": state, "questions": questions}
        if self.model:
            payload["model"] = self.model
        try:
            response = self.call(payload)
        except (OSError, ValueError, KeyError, TypeError):
            return dict.fromkeys(requests, "unavailable")
        results = {}
        for key, request in requests.items():
            try:
                answer = parse_answer(request, response["answers"][key])
            except (ValueError, KeyError, TypeError):
                results[key] = "unavailable"
                continue
            results[key] = None
            if answer["confidence"] >= request.minimum_confidence:
                results[key] = {**answer, "provider": "jev-oss" if self.local else "jev",
                                "model": response.get("model", self.model),
                                "evidence_ids": [record["id"] for record in state["evidence"]]}
        return results


class VennOutcomeStore:
    """Expose authorized, pinned outcome rows through Venn's store contract."""

    distance = "squared_l2"
    read_after_write = True

    def __init__(self, search, cases, tag, minimum_similarity):
        self.vectors = search.vectors
        self.tag = tag
        self.minimum_similarity = minimum_similarity
        self.partitions = {}
        for case in cases:
            self.partitions.setdefault(case.metadata["option"], {})[search.outcome_key(case)] = case

    def search(self, values, options, k, *, filters=None, exact_match=False):
        if filters or exact_match:
            raise ValueError("this store uses SageKit's snapshot and authorization filters")
        queries = [Vector(self.vectors.profile, tuple(map(float, row))) for row in values]
        neighbors = {}
        for option in options:
            cases = self.partitions.get(option, {})
            neighbors[option] = [
                [{"id": cases[key].id, "outcome": cases[key].metadata["utility"],
                  "distance": max(0.0, 2.0 * (1.0 - similarity))}
                 for key, similarity in self.vectors.search(query, set(cases), k)
                 if key in cases and similarity >= self.minimum_similarity]
                for query in queries
            ]
        return neighbors


class VennProvider:
    """Wrap upstream OutcomeService over SageKit's live vector store."""

    def __init__(self, minimum_support: int = 2, minimum_similarity: float = 0.35, k: int = 11):
        if not 1 <= minimum_support <= k <= 100 or not 0 <= minimum_similarity <= 1:
            raise ValueError("invalid precedent thresholds")
        self.minimum_support = minimum_support
        self.minimum_similarity = minimum_similarity
        self.k = k

    def decide(self, request, cases, search):
        profile = search.embedder.profile
        if {case.metadata["option"] for case in cases} != set(request.criteria):
            return None
        try:
            from venn import OutcomeService
            from venn.profiles import VectorTag

            search.ensure_vectors(cases, for_outcomes=True)
            state = request.state if isinstance(request.state, str) else encode(request.state)
            query = search.embedder.embed(state)
            if query.profile != profile:
                raise ValueError("incompatible Venn embedding profile")
            tag = VectorTag(profile.name, profile.revision, profile.representation,
                            profile.dimensions, profile.fields)
            service = OutcomeService()
            adapter = VennOutcomeStore(search, cases, tag, self.minimum_similarity)
            store = service.register_store(adapter)
            result = service.decide_batch(
                [{"vector": list(query.values), "tag": tag.to_dict()}],
                {"sagekit": {"type": "nearest_outcome", "store": store,
                             "options": list(request.criteria), "k": self.k,
                             "min_support": self.minimum_support, "goal": request.goal}},
            )["results"][0]["answers"]["sagekit"]
        except (ImportError, OSError, ValueError, KeyError, RuntimeError) as exc:
            raise ProviderUnavailable("Venn outcome route unavailable") from exc
        support = result["options"]
        if result["answer"] not in request.criteria or not all(stats["supported"] for stats in support.values()):
            return None
        means = [stats["mean"] for stats in support.values()]
        if means.count(support[result["answer"]]["mean"]) > 1:
            return None
        return {"provider": "venn", "value": result["answer"], "confidence": None,
                "support": support, "evidence_ids": sorted({
                    identifier for stats in support.values() for identifier in stats["evidence_ids"]
                })}
