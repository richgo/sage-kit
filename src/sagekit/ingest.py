import json
from pathlib import Path

from .model import Record, Source


def ingest(path: Path, kind: str, revision: str, *, uri: str | None = None,
           acl: tuple[str, ...] = (), supersedes: str | None = None) -> Record:
    if kind not in {"requirement", "calm", "likec4", "adr", "incident"}:
        raise ValueError("unsupported ingestion format")
    body = path.read_text(encoding="utf-8")
    title = path.stem
    metadata = {}
    if kind in {"calm", "incident"} or path.suffix.casefold() == ".json":
        artifact = json.loads(body)
        if not isinstance(artifact, dict):
            raise ValueError("expected a JSON object")
        if kind == "calm" and not all(isinstance(artifact.get(field), list)
                                     for field in ("nodes", "relationships")):
            raise ValueError("CALM requires nodes and relationships arrays")
        if kind == "incident" and not all(isinstance(artifact.get(field), str)
                                         and artifact[field].strip()
                                         for field in ("id", "title", "impact")):
            raise ValueError("incident requires id, title, and impact")
        title = artifact.get("title", title)
        if isinstance(artifact.get("id"), str):
            metadata["external_id"] = artifact["id"]
    elif kind == "likec4":
        if "model" not in body or "{" not in body or "}" not in body:
            raise ValueError("expected a LikeC4 model block")
    else:
        heading = next((line[2:].strip() for line in body.splitlines() if line.startswith("# ")), "")
        title = heading or title
    return Record(kind, title, body, Source(uri or path.as_posix(), revision),
                  acl=acl, supersedes=supersedes, metadata=metadata)
