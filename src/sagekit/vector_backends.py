from uuid import NAMESPACE_URL, uuid5

from .vectors import EmbeddingProfile, Vector, compatible


class QdrantVectors:
    def __init__(self, client, profile: EmbeddingProfile):
        from qdrant_client import models

        self.client = client
        self.profile = profile
        self.models = models
        self.collection = "sagekit_" + profile.key
        if not client.collection_exists(self.collection):
            try:
                client.create_collection(self.collection, vectors_config=models.VectorParams(
                    size=profile.dimensions, distance=models.Distance.COSINE))
            except Exception:
                if not client.collection_exists(self.collection):
                    raise
        config = client.get_collection(self.collection).config.params.vectors
        if not isinstance(config, models.VectorParams) or (
            config.size != profile.dimensions or config.distance != models.Distance.COSINE
        ):
            raise ValueError("incompatible Qdrant collection")

    def _point_id(self, key: str) -> str:
        return str(uuid5(NAMESPACE_URL, self.profile.key + ":" + key))

    def upsert(self, vectors: dict[str, Vector]) -> None:
        compatible(self.profile, vectors.values())
        if vectors:
            self.client.upsert(self.collection, wait=True, points=[
                self.models.PointStruct(id=self._point_id(key), vector=list(vector.values),
                                        payload={"record": key})
                for key, vector in vectors.items()
            ])

    def search(self, vector: Vector, allowed: set[str], limit: int) -> list[tuple[str, float]]:
        compatible(self.profile, [vector])
        if not allowed or limit <= 0:
            return []
        points = self.client.query_points(
            self.collection, query=list(vector.values), limit=limit, with_payload=True,
            query_filter=self.models.Filter(must=[
                self.models.HasIdCondition(has_id=[self._point_id(key) for key in sorted(allowed)])
            ]),
            search_params=self.models.SearchParams(exact=True),
        ).points
        return sorted([(p.payload["record"], p.score) for p in points
                       if p.payload and p.payload["record"] in allowed],
                      key=lambda row: (-row[1], row[0]))


class PgVectorStore:
    def __init__(self, dsn: str, profile: EmbeddingProfile):
        import psycopg

        self.profile = profile
        self.connect = psycopg.connect
        self.dsn = dsn
        with self.connect(dsn) as db:
            db.execute("SELECT pg_advisory_xact_lock(794477913)")
            db.execute("CREATE EXTENSION IF NOT EXISTS vector")
            db.execute("""CREATE TABLE IF NOT EXISTS sagekit_vectors (
                profile TEXT NOT NULL, record_id TEXT NOT NULL, embedding vector NOT NULL,
                PRIMARY KEY (profile, record_id))""")

    @staticmethod
    def _literal(vector: Vector) -> str:
        return "[" + ",".join(map(str, vector.values)) + "]"

    def upsert(self, vectors: dict[str, Vector]) -> None:
        compatible(self.profile, vectors.values())
        with self.connect(self.dsn) as db:
            with db.cursor() as cursor:
                cursor.executemany("""
                    INSERT INTO sagekit_vectors VALUES (%s, %s, %s::vector)
                    ON CONFLICT (profile, record_id) DO UPDATE SET embedding = EXCLUDED.embedding
                    """, [(self.profile.key, key, self._literal(vector))
                          for key, vector in sorted(vectors.items())])

    def search(self, vector: Vector, allowed: set[str], limit: int) -> list[tuple[str, float]]:
        compatible(self.profile, [vector])
        if not allowed or limit <= 0:
            return []
        with self.connect(self.dsn) as db:
            return list(db.execute("""
                SELECT record_id, 1 - (embedding <=> %s::vector) AS score
                FROM sagekit_vectors WHERE profile = %s AND record_id = ANY(%s)
                ORDER BY score DESC, record_id LIMIT %s""",
                (self._literal(vector), self.profile.key, sorted(allowed), limit)))
