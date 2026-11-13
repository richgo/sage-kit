from .decisions import number, text
from .knowledge import Knowledge, applicable
from .model import Record, Source
from .repository import Repository

LEDGER_KINDS = frozenset({"approved-choice", "verified-change", "observed-outcome"})


def approve(repo: Repository, family: str, option: str, context: str, origin: str,
            source: Source, acl: tuple[str, ...] = (), *, append=None,
            knowledge: Knowledge | None = None) -> Record:
    if not text(family) or not text(option) or option == "none" or origin not in (
        "human", "venn", "jev", "jev-oss"
    ):
        raise ValueError("approval requires family, chosen option and decision origin")
    if knowledge and knowledge.authority != "precedent":
        raise ValueError("approved choices carry precedent knowledge")
    record = Record("approved-choice", f"{family}: {option}", context, source, acl=acl, knowledge=knowledge,
                    metadata={"family": family, "option": option, "origin": origin})
    (append or repo.append)(record)
    return record


def observe(repo: Repository, choice_id: str, verification_id: str, metric: str, utility: float,
            source: Source, acl: tuple[str, ...] = (), *, append=None) -> Record:
    records = {record.id: record for record in repo.records(groups=set(acl))}
    choice = records.get(choice_id)
    verified = records.get(verification_id)
    if (not choice or choice.kind != "approved-choice" or not verified
            or verified.kind != "verified-change" or choice_id not in verified.links):
        raise ValueError("observation requires a visible approval linked to verified success")
    if not text(metric) or not number(utility):
        raise ValueError("observation requires a metric and finite utility")
    record = Record("observed-outcome", f"{choice.title}: {metric}", choice.body, source, acl=acl,
                    knowledge=choice.knowledge,
                    links=(choice.id, verified.id), metadata={
                        "family": choice.metadata["family"], "option": choice.metadata["option"],
                        "metric": metric, "utility": utility, "choice": choice.id,
                        "verification": verified.id,
                    })
    (append or repo.append)(record)
    return record


def eligible_cases(repo, revision, groups, family, metric, criteria, *, context=None):
    visible = {record.id: record for record in repo.records(revision, groups)}
    eligible = {}
    for record in visible.values():
        data = record.metadata
        if (record.kind != "observed-outcome" or not applicable(record, context) or data.get("family") != family
                or data.get("metric") != metric or data.get("option") not in criteria
                or not number(data.get("utility"))):
            continue
        choice = visible.get(data.get("choice"))
        verified = visible.get(data.get("verification"))
        if (choice and choice.kind == "approved-choice" and verified
                and verified.kind == "verified-change" and choice.id in verified.links
                and choice.id in record.links and verified.id in record.links
                and choice.metadata.get("family") == family
                and choice.metadata.get("option") == data["option"]):
            # One observed measurement per verified change and metric prevents replay inflation.
            eligible[(choice.id, verified.id)] = record
    return list(eligible.values())
