from dataclasses import dataclass
from html import escape
from pathlib import Path

from .decisions import DecisionRequest, Router
from .ledger import LEDGER_KINDS, approve, observe
from .model import Record, Source, encode
from .repository import Repository, atomic_text
from .retrieval import Search


@dataclass(frozen=True)
class Principal:
    groups: frozenset[str] = frozenset()
    scopes: frozenset[str] = frozenset()

    def require(self, scope):
        if scope not in self.scopes:
            raise PermissionError("insufficient permission")

    def allow_acl(self, acl):
        if not set(acl) <= self.groups:
            raise PermissionError("insufficient permission")


class Application:
    def __init__(self, repo: Repository, search: Search | None = None, router: Router | None = None,
                 receipt_key: bytes | None = None):
        self.repo = repo
        self.search = search or Search(repo)
        self.router = router or Router(self.search)
        self.receipt_key = receipt_key

    def dispatch(self, operation: str, params: dict, principal: Principal):
        handlers = {
            "snapshot": self.snapshot, "list": self.list, "add": self.add,
            "query": self.query, "decide": self.decide, "approve": self.approve,
            "observe": self.observe, "gate-check": self.gate_check, "promote": self.promote,
        }
        if operation not in handlers:
            raise LookupError("unknown operation")
        return handlers[operation](principal, **params)

    def snapshot(self, principal):
        return {"revision": self.repo.snapshot()}

    def list(self, principal, revision=None, history=False):
        if type(history) is not bool:
            raise ValueError("history must be a boolean")
        return [record.as_dict() for record in self.repo.records(revision, principal.groups, history=history)]

    def add(self, principal, record):
        principal.require("write")
        entry = Record.from_dict(record)
        principal.allow_acl(entry.acl)
        if entry.kind in LEDGER_KINDS:
            raise ValueError("use the dedicated outcome ledger commands")
        return {"id": entry.id, "revision": self.repo.append(entry)}

    def query(self, principal, query, revision=None, limit=10):
        return self.search.query(query, revision=revision, groups=principal.groups, limit=limit)

    def decide(self, principal, request, revision=None):
        principal.require("decide")
        return self.router.decide(DecisionRequest(**request), revision=revision, groups=principal.groups)

    def approve(self, principal, family, option, context, origin, source, acl=()):
        principal.require("approve")
        principal.allow_acl(acl)
        return approve(self.repo, family, option, context, origin, Source(**source), acl).as_dict()

    def observe(self, principal, choice_id, verification_id, metric, utility, source, acl=()):
        principal.require("observe")
        principal.allow_acl(acl)
        return observe(self.repo, choice_id, verification_id, metric, utility, Source(**source), acl).as_dict()

    def gate_check(self, principal, policy, pin=None):
        from .gates import check_gate

        if isinstance(policy, dict) and policy.get("decision") and policy.get("mode") != "off":
            principal.require("decide")
        return check_gate(self, principal, policy, pin)

    def promote(self, principal, receipt):
        from .gates import promote

        principal.require("promote")
        return promote(self, principal, receipt)

    def export_public(self, destination: Path, revision=None):
        pinned = self.repo.snapshot() if revision is None else revision
        records = [record.as_dict() for record in self.repo.records(pinned)]
        destination.mkdir(parents=True, exist_ok=True)
        atomic_text(destination / "corpus.json", encode({"schema": 1, "records": records}) + "\n")
        entries = "\n".join(f"<article><h2>{escape(record['title'])}</h2>"
                            f"<pre>{escape(record['body'])}</pre></article>" for record in records)
        atomic_text(destination / "index.html",
                    '<!doctype html><html lang="en"><meta charset="utf-8">'
                    '<title>SageKit corpus</title><h1>SageKit public corpus</h1>'
                    '<p><a href="corpus.json">Download JSON</a></p>' + entries + "</html>\n")
