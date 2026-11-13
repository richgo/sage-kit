from dataclasses import asdict
import hashlib
import hmac

from .decisions import DecisionRequest, number, text
from .knowledge import Context, Knowledge, applicable
from .model import Record, Source, digest, encode, is_digest


def pin(revision: str, inputs: dict, embedding_profile: str) -> dict:
    if (not is_digest(revision) or not is_digest(embedding_profile)
            or not isinstance(inputs, dict) or not inputs
            or not all(text(name) and is_digest(value) for name, value in inputs.items())):
        raise ValueError("pin requires a corpus revision, embedding profile and SHA-256 digests of approved inputs")
    payload = {"schema": 1, "revision": revision, "inputs": inputs,
               "embedding_profile": embedding_profile}
    return {**payload, "id": digest(payload)}


def validate_pin(value: dict) -> str:
    if not isinstance(value, dict) or value != pin(value.get("revision"), value.get("inputs"), value.get("embedding_profile")):
        raise ValueError("invalid corpus pin")
    return value["revision"]


def skipped_gate(stage=None):
    return {"schema": 1, "stage": stage, "mode": "off", "status": "skipped", "allowed": True}


def gate_envelope(policy: dict) -> dict:
    return {"schema": 1, "stage": policy["stage"], "mode": policy["mode"],
            "policy_id": digest(policy), "snapshot": None, "evidence": [], "decision": None}


def gate_unavailable(policy: dict, reason: str) -> dict:
    if (not isinstance(policy, dict) or policy.get("mode") not in ("required", "advisory")
            or not text(policy.get("stage")) or not text(policy.get("query"))):
        raise ValueError("enabled gate requires a stage and contextual query")
    return {**gate_envelope(policy), **gate_disposition(policy["mode"], "unavailable"), "reason": reason}


def gate_disposition(mode, status):
    if status == "available":
        disposition = "pass"
    else:
        disposition = "advisory" if mode == "advisory" else "block"
    return {"status": status, "disposition": disposition, "allowed": disposition != "block"}


def value_is_valid(request, value):
    if request.kind == "choice":
        return isinstance(value, str) and value in request.criteria
    maximum = 1 if request.kind == "noul" else len(request.criteria) - 1
    return number(value) and 0 <= value <= maximum


def parse_questions(value):
    if (not isinstance(value, dict) or not 1 <= len(value) <= 20
            or not all(text(key) for key in value)):
        raise ValueError("questions must contain between one and twenty named entries")
    questions = {}
    for key, entry in value.items():
        if (not isinstance(entry, dict) or set(entry) != {"request", "accept"}
                or not isinstance(entry["request"], dict) or not isinstance(entry["accept"], dict)):
            raise ValueError("each question requires a typed request and acceptance rule")
        request = DecisionRequest(**entry["request"])
        accept = entry["accept"]
        if (set(accept) != {"op", "value"} or accept["op"] not in ("eq", "min", "max")
                or not value_is_valid(request, accept["value"])
                or (request.kind == "choice" and accept["op"] != "eq")):
            raise ValueError("invalid acceptance rule for question " + key)
        questions[key] = (request, accept)
    return questions


def accepted(request, rule, value):
    if not value_is_valid(request, value):
        return False
    expected = rule["value"]
    if rule["op"] == "eq":
        return value == expected
    return value >= expected if rule["op"] == "min" else value <= expected


def evaluate_questions(app, principal, questions, context, pinned, records):
    judgments = {}
    pending = {}
    request_ids = {key: digest({"request": asdict(request), "inputs": pinned["inputs"]})
                   for key, (request, _) in questions.items()}
    for key, (request, _) in questions.items():
        failures = request.policy_failures()
        if failures:
            judgments[key] = {"status": "denied", "provider": "policy", "failed_fields": failures}
            continue
        answers = {record.id: record.knowledge.answer["value"] for record in records.values()
                   if record.knowledge.answer and record.knowledge.answer["request_id"] == request_ids[key]}
        if not answers:
            pending[key] = request
            continue
        value = next(iter(answers.values()))
        valid = all(value_is_valid(request, answer) for answer in answers.values())
        outcome = {"status": "answered", "value": value}
        if not valid or any(answer != value for answer in answers.values()):
            outcome = {"status": "conflict"}
        judgments[key] = {**outcome, "provider": "authority", "evidence_ids": sorted(answers)}
    judgments.update(app.router.decide_many(pending, revision=pinned["revision"], groups=principal.groups,
                                            context=context))
    for key, judgment in judgments.items():
        request, rule = questions[key]
        judgment["request_id"] = request_ids[key]
        judgment["kind"] = request.kind
        if judgment["status"] == "answered":
            judgment["status"] = "accepted" if accepted(request, rule, judgment.get("value")) else "rejected"
        if judgment["status"] == "abstained" and any(
                attempt["status"] == "unavailable" for attempt in judgment.get("attempts", [])):
            judgment["status"] = "unavailable"
    return judgments


def check_gate(app, principal, policy: dict, pinned: dict | None) -> dict:
    if not isinstance(policy, dict):
        raise ValueError("gate policy must be an object")
    mode = policy.get("mode", "off")
    stage = policy.get("stage")
    if mode == "off":
        return skipped_gate(stage)
    if mode not in ("advisory", "required") or not text(stage) or not text(policy.get("query")):
        raise ValueError("enabled gate requires a stage and contextual query")
    count = policy.get("minimum_evidence", 1)
    exact_ids = policy.get("exact_ids", [])
    if (type(count) is not int or not 0 <= count <= 100 or not isinstance(exact_ids, list)
            or not all(map(is_digest, exact_ids))):
        raise ValueError("invalid gate evidence requirements")
    request = DecisionRequest(**policy["decision"]) if policy.get("decision") is not None else None
    context = Context(**policy["context"]) if "context" in policy else None
    questions = parse_questions(policy["questions"]) if "questions" in policy else None
    if (questions and context is None) or (context and request is not None):
        raise ValueError("scoped gates use context and questions instead of a legacy decision")
    if not count and not exact_ids and request is None and not questions:
        raise ValueError("enabled gate requires evidence or a decision")
    envelope = gate_envelope(policy)
    if context:
        envelope["context"] = asdict(context)
    try:
        revision = validate_pin(pinned)
        if pinned["embedding_profile"] != app.search.embedder.profile.key:
            raise ValueError("embedding profile differs from the pinned profile")
        if "inputs" in policy and policy["inputs"] != pinned["inputs"]:
            raise ValueError("approved inputs differ")
        records = {record.id: record for record in app.repo.records(revision, principal.groups)
                   if applicable(record, context)}
    except ValueError:
        return gate_unavailable(policy, "invalid or unavailable pin")
    envelope["snapshot"] = revision
    evidence = app.search.query(policy["query"], revision=revision, groups=principal.groups,
                                limit=max(count, 10), context=context)
    exact = set(exact_ids)
    found = set(records).intersection(exact)
    ids = found.union(hit["record"]["id"] for hit in evidence)
    judgments = {}
    if questions:
        judgments = evaluate_questions(app, principal, questions, context, pinned, records)
        envelope["judgments"] = judgments
    evidence_ids = ids.union(*(set(item.get("evidence_ids", ())) for item in judgments.values()))
    evidence_ids.intersection_update(records)
    envelope["evidence"] = [
        {"id": key, "source": records[key].source.as_dict(), **(
            {"knowledge": records[key].knowledge.as_dict()} if records[key].knowledge else {}
        )} for key in sorted(evidence_ids)
    ]
    if request:
        envelope["decision"] = app.decide(principal, asdict(request), revision)
    statuses = {item["status"] for item in judgments.values()}
    ready = (len(evidence_ids) >= count and exact <= found and statuses <= {"accepted"} and (
        envelope["decision"] is None or envelope["decision"]["status"] == "answered"))
    status = "available" if ready else "insufficient"
    if statuses.intersection({"denied", "rejected", "conflict"}):
        status = "rejected"
    elif "unavailable" in statuses:
        status = "unavailable"
    return {**envelope, **gate_disposition(mode, status)}


def signed(payload: dict, key: bytes) -> dict:
    if not key or len(key) < 32:
        raise ValueError("a receipt signing key of at least 32 bytes is required")
    signature = hmac.new(key, encode(payload).encode("utf-8"), hashlib.sha256).hexdigest()
    return {"payload": payload, "signature": signature}


def promote(app, principal, receipt: dict) -> dict:
    if not isinstance(receipt, dict) or set(receipt) != {"payload", "signature"}:
        raise ValueError("invalid verification receipt")
    payload = receipt["payload"]
    signature = receipt["signature"]
    if not is_digest(signature) or not hmac.compare_digest(
        signature, signed(payload, app.receipt_key)["signature"]
    ):
        raise ValueError("invalid verification signature")
    if (not isinstance(payload, dict) or payload.get("schema") != 1
            or not text(payload.get("pipeline")) or not text(payload.get("run"))
            or payload.get("status") != "success" or payload.get("approved") is not True
            or payload.get("independently_verified") is not True):
        raise ValueError("promotion requires completed, approved and independently verified success")
    revision = validate_pin(payload["pin"])
    verification = payload["verification"]
    if not isinstance(verification, dict) or not is_digest(verification.get("sha256")):
        raise ValueError("verification requires the evidence artifact digest")
    change = payload["change"]
    if change["kind"] not in ("architecture", "product"):
        raise ValueError("unsupported change kind")
    knowledge = Knowledge(**change["knowledge"]) if "knowledge" in change else None
    if knowledge and knowledge.authority != "precedent":
        raise ValueError("verified promotion can only publish precedent knowledge")
    entry = Record("verified-change", change["title"], change["summary"],
                   Source(verification["uri"], verification["sha256"]),
                   acl=change.get("acl", ()), links=change.get("links", ()), knowledge=knowledge,
                   metadata={"pipeline": payload["pipeline"], "run": payload["run"],
                             "change_kind": change["kind"], "pin": payload["pin"],
                             "receipt_sha256": digest(receipt)})
    principal.allow_acl(entry.acl)
    pinned = {item.id for item in app.repo.records(revision, principal.groups)}
    if not set(entry.links) <= pinned:
        raise ValueError("change references knowledge outside the approved snapshot")
    return {"id": entry.id, "revision": app.append(entry)}
