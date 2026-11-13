from dataclasses import dataclass, field
import hashlib
import json
from typing import Any

from .knowledge import Knowledge


def encode(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False)


def digest(value: Any) -> str:
    return hashlib.sha256(encode(value).encode("utf-8")).hexdigest()


KINDS = frozenset({
    "requirement", "calm", "likec4", "adr", "incident", "verified-change",
    "approved-choice", "observed-outcome",
})


def is_digest(value: object) -> bool:
    return (isinstance(value, str) and len(value) == 64
            and all(character in "0123456789abcdef" for character in value))


@dataclass(frozen=True)
class Source:
    uri: str
    revision: str
    locator: str = ""

    def __post_init__(self):
        if not all(isinstance(value, str) and value.strip()
                   for value in (self.uri, self.revision)):
            raise ValueError("source URI and revision are required")
        if not isinstance(self.locator, str):
            raise ValueError("source locator must be text")

    def as_dict(self) -> dict:
        return {"uri": self.uri, "revision": self.revision, "locator": self.locator}


@dataclass(frozen=True)
class Record:
    kind: str
    title: str
    body: str
    source: Source
    acl: tuple[str, ...] = ()
    supersedes: str | None = None
    links: tuple[str, ...] = ()
    metadata: dict = field(default_factory=dict)
    knowledge: Knowledge | None = None

    def __post_init__(self):
        if not isinstance(self.kind, str) or self.kind not in KINDS:
            raise ValueError("unsupported record kind")
        if not all(isinstance(value, str) and value.strip()
                   for value in (self.title, self.body)):
            raise ValueError("record title and body are required")
        if not isinstance(self.source, Source) or not isinstance(self.metadata, dict):
            raise ValueError("invalid source or metadata")
        if not isinstance(self.acl, (list, tuple)) or not all(
            isinstance(group, str) and group.strip() for group in self.acl
        ):
            raise ValueError("invalid ACL")
        if not isinstance(self.links, (list, tuple)) or not all(map(is_digest, self.links)):
            raise ValueError("invalid record links")
        if self.supersedes is not None and not is_digest(self.supersedes):
            raise ValueError("invalid superseded record ID")
        if self.knowledge is not None and not isinstance(self.knowledge, Knowledge):
            raise ValueError("invalid typed knowledge")
        object.__setattr__(self, "acl", tuple(sorted(set(self.acl))))
        object.__setattr__(self, "links", tuple(sorted(set(self.links))))
        object.__setattr__(self, "metadata", json.loads(encode(self.metadata)))

    @property
    def id(self) -> str:
        return digest(self._payload())

    def _payload(self) -> dict:
        payload = {
            "schema": 1, "kind": self.kind, "title": self.title, "body": self.body,
            "source": self.source.as_dict(), "acl": list(self.acl),
            "supersedes": self.supersedes, "links": list(self.links),
            "metadata": self.metadata,
        }
        if self.knowledge is not None:
            payload["knowledge"] = self.knowledge.as_dict()
        return payload

    def as_dict(self) -> dict:
        return {**self._payload(), "id": self.id}

    @classmethod
    def from_dict(cls, data: dict) -> "Record":
        fields = dict(data)
        if fields.pop("schema", 1) != 1:
            raise ValueError("unsupported record schema")
        identifier = fields.pop("id", None)
        fields["source"] = Source(**fields["source"])
        if "knowledge" in fields:
            fields["knowledge"] = Knowledge(**fields["knowledge"])
        record = cls(**fields)
        if identifier is not None and identifier != record.id:
            raise ValueError("record ID does not match its contents")
        return record
