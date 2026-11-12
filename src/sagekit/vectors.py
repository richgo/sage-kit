from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Protocol

from .model import digest, encode
from .repository import atomic_text


def words(text: str) -> list[str]:
    return re.findall(r"[^\W_]+", text.casefold())


@dataclass(frozen=True)
class EmbeddingProfile:
    name: str
    revision: str
    representation: str
    dimensions: int
    fields: tuple[str, ...] = ("text",)

    def __post_init__(self):
        if (not all(isinstance(value, str) and value for value in
                    (self.name, self.revision, self.representation, *self.fields))
                or type(self.dimensions) is not int or not 1 <= self.dimensions <= 4096
                or not self.fields or len(set(self.fields)) != len(self.fields)):
            raise ValueError("invalid embedding profile")

    @property
    def key(self) -> str:
        return digest(asdict(self))


@dataclass(frozen=True)
class Vector:
    profile: EmbeddingProfile
    values: tuple[float, ...]

    def __post_init__(self):
        if (len(self.values) != self.profile.dimensions
                or any(not math.isfinite(x) for x in self.values)
                or not math.isclose(math.hypot(*self.values), 1, abs_tol=1e-5)):
            raise ValueError("expected a finite unit vector with the profile dimension")


class Embedder(Protocol):
    profile: EmbeddingProfile

    def embed(self, text: str) -> Vector: ...


class HashEmbedder:
    """Portable lexical embeddings for offline similarity and tests."""

    profile = EmbeddingProfile("experimental:sagekit-hash", "f" * 40, "text", 512)

    def embed(self, text: str) -> Vector:
        values = [0.0] * self.profile.dimensions
        tokens = words(text)
        for token in tokens or [""]:
            hashed = hashlib.sha256(token.encode()).digest()
            index = int.from_bytes(hashed[:4], "big") % len(values)
            values[index] += 1.0
        norm = math.hypot(*values)
        return Vector(self.profile, tuple(value / norm for value in values))


class SentenceEmbedder:
    def __init__(self, model: str, revision: str, dimensions: int):
        from sentence_transformers import SentenceTransformer

        if not re.fullmatch(r"[0-9a-f]{40}", revision):
            raise ValueError("sentence model requires a pinned 40-character revision")
        self.profile = EmbeddingProfile("experimental:" + model, revision, "text", dimensions)
        self.model = SentenceTransformer(model, revision=revision, trust_remote_code=False)

    def embed(self, text: str) -> Vector:
        values = self.model.encode(text, normalize_embeddings=True)
        return Vector(self.profile, tuple(map(float, values)))


class VectorStore(Protocol):
    profile: EmbeddingProfile

    def existing(self, keys: set[str]) -> set[str]: ...

    def upsert(self, vectors: dict[str, Vector]) -> None: ...
    def search(self, vector: Vector, allowed: set[str], limit: int) -> list[tuple[str, float]]: ...


def compatible(profile: EmbeddingProfile, vectors) -> None:
    if any(vector.profile != profile for vector in vectors):
        raise ValueError("incompatible embedding profile")


class FlatVectors:
    """Exact cosine search over normalized, profile-tagged vectors."""

    profile: EmbeddingProfile

    def load(self, allowed: set[str]) -> dict[str, tuple[float, ...]]:
        raise NotImplementedError

    def search(self, vector: Vector, allowed: set[str], limit: int) -> list[tuple[str, float]]:
        compatible(self.profile, [vector])
        rows = ((key, sum(a * b for a, b in zip(vector.values, values)))
                for key, values in self.load(allowed).items())
        return sorted(rows, key=lambda row: (-row[1], row[0]))[:limit]


class MemoryVectors(FlatVectors):
    def __init__(self, profile: EmbeddingProfile):
        self.profile = profile
        self.vectors: dict[str, Vector] = {}

    def existing(self, keys: set[str]) -> set[str]:
        return keys.intersection(self.vectors)

    def upsert(self, vectors: dict[str, Vector]) -> None:
        compatible(self.profile, vectors.values())
        self.vectors.update(vectors)

    def load(self, allowed: set[str]) -> dict[str, tuple[float, ...]]:
        return {key: self.vectors[key].values for key in self.existing(allowed)}


class FileVectors(FlatVectors):
    """Local vector storage shared across CLI processes, isolated by profile."""

    def __init__(self, root: Path, profile: EmbeddingProfile):
        self.profile = profile
        self.directory = root / profile.key
        self.directory.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        return self.directory / (digest(key) + ".json")

    def existing(self, keys: set[str]) -> set[str]:
        return {key for key in keys if self._path(key).is_file()}

    def upsert(self, vectors: dict[str, Vector]) -> None:
        compatible(self.profile, vectors.values())
        for key, vector in vectors.items():
            atomic_text(self._path(key), encode(vector.values))

    def load(self, allowed: set[str]) -> dict[str, tuple[float, ...]]:
        return {key: Vector(self.profile, tuple(json.loads(
            self._path(key).read_text(encoding="utf-8")))).values
                for key in self.existing(allowed)}


class FaissVectors(FlatVectors):
    def __init__(self, profile: EmbeddingProfile, root: Path | None = None):
        self.profile = profile
        self.storage = MemoryVectors(profile) if root is None else FileVectors(root, profile)

    def existing(self, keys: set[str]) -> set[str]:
        return self.storage.existing(keys)

    def upsert(self, vectors: dict[str, Vector]) -> None:
        self.storage.upsert(vectors)

    def load(self, allowed: set[str]) -> dict[str, tuple[float, ...]]:
        return self.storage.load(allowed)

    def search(self, vector: Vector, allowed: set[str], limit: int) -> list[tuple[str, float]]:
        import faiss
        import numpy as np

        compatible(self.profile, [vector])
        vectors = self.load(allowed)
        keys = sorted(vectors)
        if not keys:
            return []
        index = faiss.IndexFlatIP(self.profile.dimensions)
        index.add(np.asarray([vectors[key] for key in keys], dtype="float32"))
        scores, positions = index.search(np.asarray([vector.values], dtype="float32"), len(keys))
        rows = [(keys[position], float(score)) for score, position in zip(scores[0], positions[0])]
        return sorted(rows, key=lambda row: (-row[1], row[0]))[:limit]
