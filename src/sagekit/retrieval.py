from .model import is_digest
from .repository import Repository
from .vectors import Embedder, HashEmbedder, MemoryVectors, VectorStore, words


class Search:
    def __init__(self, repo: Repository, embedder: Embedder | None = None,
                 vectors: VectorStore | None = None):
        self.repo = repo
        self.embedder = embedder or HashEmbedder()
        self.vectors = vectors or MemoryVectors(self.embedder.profile)
        if self.vectors.profile != self.embedder.profile:
            raise ValueError("incompatible embedding profile")

    def query(self, query: str, *, revision: str | None = None, groups: set[str] | None = None,
              limit: int = 10, minimum: float = 0.15) -> list[dict]:
        if not isinstance(query, str) or not query.strip() or type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("query requires text and a limit from 1 to 100")
        if not 0 <= minimum <= 1:
            raise ValueError("invalid similarity threshold")
        records = {record.id: record for record in self.repo.records(revision, groups)}
        folded = query.strip().casefold()
        exact = sorted(record.id for record in records.values() if folded in {
            record.id, record.title.casefold(), record.source.uri.casefold(),
            str(record.metadata.get("external_id", "")).casefold(),
        })
        ids = set() if is_digest(folded) else set(records) - set(exact)
        tokens = set(words(query))
        if self.embedder.profile == HashEmbedder.profile:
            # A hash collision alone is insufficient evidence.
            ids = {key for key in ids if tokens.intersection(words(
                records[key].title + " " + records[key].body))}
        hits = [{"record": records[key].as_dict(), "score": 1.0, "exact": True} for key in exact]
        if ids and len(hits) < limit:
            self.vectors.upsert({key: self.embedder.embed(records[key].title + "\n" + records[key].body)
                                 for key in sorted(ids)})
            matches = self.vectors.search(self.embedder.embed(query), ids, limit - len(hits))
            hits.extend({"record": records[key].as_dict(), "score": score, "exact": False}
                        for key, score in matches if key in ids and score >= minimum)
        return hits[:limit]
