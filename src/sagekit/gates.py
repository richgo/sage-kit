from dataclasses import asdict
import hashlib
import hmac

from .decisions import DecisionRequest, text
from .model import Record, Source, digest, encode, is_digest


def pin(revision: str, inputs: dict) -> dict:
    if (not is_digest(revision) or not isinstance(inputs, dict) or not inputs
            or not all(text(name) and is_digest(value) for name, value in inputs.items())):
        raise ValueError("pin requires a corpus revision and SHA-256 digests of approved inputs")
    payload = {"schema": 1, "revision": revision, "inputs": inputs}
    return {**payload, "id": digest(payload)}


def validate_pin(value: dict) -> str:
    if not isinstance(value, dict) or value != pin(value.get("revision"), value.get("inputs")):
        raise ValueError("invalid corpus pin")
    return value["revision"]


def check_gate(app, principal, policy: dict, pinned: dict | None) -> dict:
    if not isinstance(policy, dict):
        raise ValueError("gate policy must be an object")
    mode = policy.get("mode", "off")
    stage = policy.get("stage")
    if mode == "off":
        return {"schema": 1, "stage": stage, "mode": mode, "status": "skipped", "allowed": True}
    if mode not in ("advisory", "required") or not text(stage) or not text(policy.get("query")):
        raise ValueError("enabled gate requires a stage and contextual query")
    count = policy.get("minimum_evidence", 1)
    exact_ids = policy.get("exact_ids", [])
    if (type(count) is not int or not 0 <= count <= 100 or not isinstance(exact_ids, list)
            or not all(map(is_digest, exact_ids))):
        raise ValueError("invalid gate evidence requirements")
    request = DecisionRequest(**policy["decision"]) if policy.get("decision") is not None else None
    if not count and not exact_ids and request is None:
        raise ValueError("enabled gate requires evidence or a decision")
    envelope = {"schema": 1, "stage": stage, "mode": mode, "policy_id": digest(policy),
                "snapshot": None, "evidence": [], "decision": None}
    try:
        revision = validate_pin(pinned)
        if "inputs" in policy and policy["inputs"] != pinned["inputs"]:
            raise ValueError("approved inputs differ")
        records = {record.id: record for record in app.repo.records(revision, principal.groups)}
    except ValueError:
        return {**envelope, "status": "unavailable", "reason": "invalid or unavailable pin",
                "allowed": mode == "advisory"}
    envelope["snapshot"] = revision
    evidence = app.search.query(policy["query"], revision=revision, groups=principal.groups,
                                limit=max(count, 10))
    exact = set(exact_ids)
    found = set(records).intersection(exact)
    ids = found.union(hit["record"]["id"] for hit in evidence)
    envelope["evidence"] = [{"id": key, "source": records[key].source.as_dict()} for key in sorted(ids)]
    if request:
        envelope["decision"] = app.decide(principal, asdict(request), revision)
    ready = (len(ids) >= count and exact <= found and (
        envelope["decision"] is None or envelope["decision"]["status"] == "answered"))
    return {**envelope, "status": "available" if ready else "insufficient",
            "allowed": ready or mode == "advisory"}


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
    entry = Record("verified-change", change["title"], change["summary"],
                   Source(verification["uri"], verification["sha256"]),
                   acl=change.get("acl", ()), links=change.get("links", ()),
                   metadata={"pipeline": payload["pipeline"], "run": payload["run"],
                             "change_kind": change["kind"], "pin": payload["pin"],
                             "receipt_sha256": digest(receipt)})
    principal.allow_acl(entry.acl)
    pinned = {item.id for item in app.repo.records(revision, principal.groups)}
    if not set(entry.links) <= pinned:
        raise ValueError("change references knowledge outside the approved snapshot")
    return {"id": entry.id, "revision": app.repo.append(entry)}
