import os
from pathlib import Path

from .application import Application
from .decisions import Router
from .providers import JevProvider, VennProvider
from .repository import LocalRepository
from .retrieval import Search
from .vectors import FaissVectors, HashEmbedder, MemoryVectors, SentenceEmbedder


def create_application(root: Path) -> Application:
    dsn = os.getenv("SAGEKIT_POSTGRES_DSN")
    if dsn:
        from .postgres import PostgresRepository

        repo = PostgresRepository(dsn)
    else:
        repo = LocalRepository(root)
    model = os.getenv("SAGEKIT_EMBEDDING_MODEL")
    if model:
        embedder = SentenceEmbedder(model, os.environ["SAGEKIT_EMBEDDING_REVISION"],
                                    int(os.environ["SAGEKIT_EMBEDDING_DIMENSIONS"]))
    else:
        embedder = HashEmbedder()

    backend = os.getenv("SAGEKIT_VECTORS", "memory")
    if backend == "qdrant":
        from qdrant_client import QdrantClient

        from .vector_backends import QdrantVectors

        vectors = QdrantVectors(QdrantClient(url=os.environ["SAGEKIT_QDRANT_URL"],
                                             api_key=os.getenv("SAGEKIT_QDRANT_API_KEY")),
                                 embedder.profile)
    elif backend == "pgvector":
        from .vector_backends import PgVectorStore

        if not dsn:
            raise ValueError("pgvector requires SAGEKIT_POSTGRES_DSN")
        vectors = PgVectorStore(dsn, embedder.profile)
    elif backend == "faiss":
        vectors = FaissVectors(embedder.profile)
    elif backend == "memory":
        vectors = MemoryVectors(embedder.profile)
    else:
        raise ValueError("unknown vector backend")

    fallback = None
    endpoint = os.getenv("SAGEKIT_JEV_URL")
    if endpoint:
        fallback = JevProvider(endpoint, os.getenv("TYPESAFE_API_KEY"), os.getenv("SAGEKIT_JEV_MODEL"))
    precedent = VennProvider() if os.getenv("SAGEKIT_VENN") == "1" else None
    search = Search(repo, embedder, vectors)
    secret = os.getenv("SAGEKIT_RECEIPT_KEY")
    return Application(repo, search, Router(search, precedent=precedent, fallback=fallback),
                       secret.encode() if secret else None)
