import math

from .decisions import DecisionRequest, ProviderUnavailable, number
from .http import check_endpoint, post_json


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
        question = {"type": request.kind, "instructions": request.instructions}
        if request.criteria is not None:
            question["criteria"] = request.criteria
        records = [item["record"] for item in evidence if self.allow_restricted_evidence or not item["record"]["acl"]]
        payload = {"state": {"context": request.state, "evidence": records},
                   "questions": {"sagekit": question}}
        if self.model:
            payload["model"] = self.model
        try:
            response = self.call(payload)
            answer = parse_answer(request, response["answers"]["sagekit"])
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise ProviderUnavailable("Jev request failed or returned an invalid answer") from exc
        if answer["confidence"] < request.minimum_confidence:
            return None
        return {**answer, "provider": "jev-oss" if self.local else "jev",
                "model": response.get("model", self.model),
                "evidence_ids": [record["id"] for record in records]}


class VennProvider:
    """Use upstream OutcomeService over eligible, profile-matched observed cases."""

    def __init__(self, minimum_support: int = 2, minimum_similarity: float = 0.35, k: int = 11):
        if not 1 <= minimum_support <= k <= 100 or not 0 <= minimum_similarity <= 1:
            raise ValueError("invalid precedent thresholds")
        self.minimum_support = minimum_support
        self.minimum_similarity = minimum_similarity
        self.k = k

    def decide(self, request, cases, embedder):
        from .model import encode

        profile = embedder.profile
        query = embedder.embed(request.state if isinstance(request.state, str) else encode(request.state))
        partitions = {}
        for case in cases:
            vector = embedder.embed(case.body)
            if vector.profile != profile or query.profile != profile:
                raise ValueError("incompatible Venn embedding profile")
            similarity = sum(a * b for a, b in zip(vector.values, query.values))
            if similarity >= self.minimum_similarity:
                partitions.setdefault(case.metadata["option"], []).append((case, vector))
        supported = {key: rows for key, rows in partitions.items() if len(rows) >= self.minimum_support}
        # An unsupported alternative cannot be compared with a measured utility.
        if set(supported) != set(request.criteria):
            return None
        try:
            import faiss
            import numpy as np
            from venn import OutcomeService
            from venn.adapters import FaissOutcomeAdapter
            from venn.profiles import VectorTag

            tag = VectorTag(profile.name, profile.revision, profile.representation,
                            profile.dimensions, profile.fields)
            parts = {}
            for key, rows in supported.items():
                index = faiss.IndexFlatL2(profile.dimensions)
                index.add(np.asarray([vector.values for _, vector in rows], dtype="float32"))
                parts[key] = {"index": index, "ids": [case.id for case, _ in rows],
                              "outcomes": [case.metadata["utility"] for case, _ in rows]}
            service = OutcomeService()
            store = service.register_store(FaissOutcomeAdapter(parts, tag=tag))
            result = service.decide_batch(
                [{"vector": np.asarray(query.values, dtype="float32"), "tag": tag.to_dict()}],
                {"sagekit": {"type": "nearest_outcome", "store": store,
                             "options": list(request.criteria), "k": self.k,
                             "min_support": self.minimum_support, "goal": request.goal}},
            )["results"][0]["answers"]["sagekit"]
        except (ImportError, OSError, ValueError, KeyError, RuntimeError) as exc:
            raise ProviderUnavailable("Venn outcome route unavailable") from exc
        if result["answer"] not in request.criteria:
            return None
        support = result["options"]
        means = [stats["mean"] for stats in support.values() if stats["supported"]]
        if len(set(means)) == 1 or means.count(support[result["answer"]]["mean"]) > 1:
            return None
        return {"provider": "venn", "value": result["answer"], "confidence": None,
                "support": support, "evidence_ids": sorted({
                    identifier for stats in support.values() for identifier in stats["evidence_ids"]
                })}
