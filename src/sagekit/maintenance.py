from pathlib import Path
from time import perf_counter

from .model import encode
from .repository import EMPTY_REVISION, LocalRepository, atomic_text, parse_journal


def backup(repo: LocalRepository, destination: Path) -> dict:
    if not isinstance(repo, LocalRepository):
        raise ValueError("use database backups for PostgreSQL")
    if destination.resolve() == repo.journal.resolve() or destination.resolve().is_relative_to(repo.database.parent):
        raise ValueError("backup destination must be outside live corpus state")
    with repo._transaction() as (_, events):
        atomic_text(destination, "".join(encode(event) + "\n" for event in events))
    return {"revision": events[-1]["revision"] if events else EMPTY_REVISION, "events": len(events)}


def restore(repo: LocalRepository, source: Path) -> dict:
    if not isinstance(repo, LocalRepository):
        raise ValueError("use database restores for PostgreSQL")
    contents = source.read_text(encoding="utf-8")
    events = parse_journal(contents)
    with repo._transaction() as (_, existing):
        if existing:
            raise ValueError("restore requires an empty corpus")
        atomic_text(repo.journal, contents)
    return {"revision": repo.snapshot(), "events": len(events)}


def reindex(app, groups, revision=None) -> dict:
    pinned = app.repo.snapshot() if revision is None else revision
    records = app.repo.records(pinned, groups)
    vectors = app.search.vectors
    embedder = app.search.embedder
    started = perf_counter()
    for offset in range(0, len(records), 100):
        vectors.upsert({item.id: embedder.embed(item.title + "\n" + item.body)
                        for item in records[offset:offset + 100]})
    return {"revision": pinned, "records": len(records), "embedding_profile": embedder.profile.key,
            "seconds": perf_counter() - started}


def benchmark(app, groups, queries: list[str]) -> dict:
    if not isinstance(queries, list) or not queries:
        raise ValueError("benchmark requires a list of queries")
    revision = app.repo.snapshot()
    timings = []
    for query in queries:
        start = perf_counter()
        app.search.query(query, revision=revision, groups=groups)
        timings.append((perf_counter() - start) * 1000)
    timings.sort()
    return {"revision": revision, "queries": len(queries), "median_ms": timings[len(timings) // 2],
            "max_ms": timings[-1], "embedding_profile": app.search.embedder.profile.key}
