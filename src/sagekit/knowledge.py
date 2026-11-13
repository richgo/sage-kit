from dataclasses import dataclass
from datetime import date


AUTHORITIES = frozenset({"authoritative", "precedent", "candidate"})
SCOPE_FIELDS = frozenset({"product", "repository", "component"})


def scope_fields(scope):
    if (not isinstance(scope, dict) or not scope or set(scope) - SCOPE_FIELDS
            or any(not isinstance(value, str) or not value or value.strip() != value
                   for value in scope.values())):
        raise ValueError("knowledge scope requires named product, repository or component fields")
    return dict(scope)


def day(value):
    if not isinstance(value, str):
        raise ValueError("knowledge validity requires a YYYY-MM-DD date")
    parsed = date.fromisoformat(value)
    if parsed.isoformat() != value:
        raise ValueError("knowledge validity requires a YYYY-MM-DD date")
    return parsed


@dataclass(frozen=True)
class Context:
    scope: dict[str, str]
    as_of: str

    def __post_init__(self):
        object.__setattr__(self, "scope", scope_fields(self.scope))
        day(self.as_of)


@dataclass(frozen=True)
class Knowledge:
    authority: str
    scope: dict[str, str]
    valid_from: str | None = None
    valid_until: str | None = None
    answer: dict | None = None

    def __post_init__(self):
        from .model import encode, is_digest

        if not isinstance(self.authority, str) or self.authority not in AUTHORITIES:
            raise ValueError("unsupported knowledge authority")
        object.__setattr__(self, "scope", scope_fields(self.scope))
        start = day(self.valid_from) if self.valid_from is not None else None
        end = day(self.valid_until) if self.valid_until is not None else None
        if start is not None and end is not None and start >= end:
            raise ValueError("knowledge validity must be a nonempty date range")
        if self.answer is not None:
            if (self.authority != "authoritative" or not isinstance(self.answer, dict)
                    or set(self.answer) != {"request_id", "value"}
                    or not is_digest(self.answer["request_id"])
                    or type(self.answer["value"]) not in (int, float, str)):
                raise ValueError("only authoritative knowledge can carry an exact typed answer")
            encode(self.answer)
            object.__setattr__(self, "answer", dict(self.answer))

    def as_dict(self):
        payload = {"authority": self.authority, "scope": dict(self.scope)}
        for field in ("valid_from", "valid_until", "answer"):
            value = getattr(self, field)
            if value is not None:
                payload[field] = dict(value) if field == "answer" else value
        return payload

    def authority_scope(self):
        return self.authority, self.scope

    def applies(self, context: Context) -> bool:
        return (
            all(context.scope.get(field) == value for field, value in self.scope.items())
            and (self.valid_from is None or self.valid_from <= context.as_of)
            and (self.valid_until is None or context.as_of < self.valid_until)
        )


def applicable(record, context: Context | None) -> bool:
    knowledge = record.knowledge
    if context is None:
        return knowledge is None
    return knowledge is not None and knowledge.authority != "candidate" and knowledge.applies(context)
