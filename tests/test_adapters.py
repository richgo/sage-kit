import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

from sagekit.application import Application
from sagekit.decisions import DecisionRequest
from sagekit.maintenance import backup, restore
from sagekit.model import Record, Source
from sagekit.providers import VennProvider
from sagekit.repository import LocalRepository
from sagekit.vector_backends import PgVectorStore, QdrantVectors
from sagekit.vectors import EmbeddingProfile, FaissVectors, HashEmbedder, Vector
from test_foundation import record


def has(package):
    return importlib.util.find_spec(package) is not None


def vector_contract(test, store, embedder):
    vector = embedder.embed("checkout")
    ids = {str(uuid4()) for _ in range(3)}
    first, second, hidden = sorted(ids)
    store.upsert({first: vector, second: embedder.embed("architecture"), hidden: vector})
    test.assertEqual([first], [key for key, _ in store.search(vector, {first, second}, 1)])
    test.assertEqual([], store.search(vector, set(), 10))
    wrong = EmbeddingProfile("different", "v1", "text", embedder.profile.dimensions)
    with test.assertRaises(ValueError):
        store.search(Vector(wrong, vector.values), ids, 1)


class Adapters(unittest.TestCase):
    @unittest.skipUnless(has("faiss"), "requires faiss-cpu")
    def test_faiss(self):
        embedder = HashEmbedder()
        vector_contract(self, FaissVectors(embedder.profile), embedder)

    @unittest.skipUnless(has("qdrant_client"), "requires qdrant-client")
    def test_qdrant(self):
        from qdrant_client import QdrantClient

        embedder = HashEmbedder()
        with tempfile.TemporaryDirectory() as temp:
            client = QdrantClient(path=temp)
            try:
                vector_contract(self, QdrantVectors(client, embedder.profile), embedder)
            finally:
                client.close()

    @unittest.skipUnless(os.getenv("SAGEKIT_TEST_POSTGRES"), "requires PostgreSQL with pgvector")
    def test_postgres_and_pgvector(self):
        from sagekit.postgres import PostgresRepository

        dsn = os.environ["SAGEKIT_TEST_POSTGRES"]
        repo = PostgresRepository(dsn)
        item = record(str(uuid4()), acl=("sre",))
        revision = repo.append(item)
        self.assertEqual(revision, repo.append(item))
        self.assertIn(item, repo.records(revision, {"sre"}))
        self.assertNotIn(item, repo.records(revision))
        self.assertEqual(revision, repo.snapshot())
        embedder = HashEmbedder()
        vector_contract(self, PgVectorStore(dsn, embedder.profile), embedder)

    @unittest.skipUnless(has("venn"), "requires pinned Venn")
    def test_real_venn_outcome_service(self):
        request = DecisionRequest("choice", "checkout retry", "checkout retry",
                                  {"a": "retry", "b": "queue"}, family="checkout", metric="uptime")
        cases = [Record("observed-outcome", str(index), "checkout retry", Source("repo:ops", str(index)),
                        metadata={"option": option, "utility": utility})
                 for index, (option, utility) in enumerate([("a", 1), ("a", .9), ("b", .4), ("b", .3)])]
        result = VennProvider().decide(request, cases, HashEmbedder())
        self.assertEqual("a", result["value"])
        self.assertEqual(4, len(result["evidence_ids"]))
        self.assertIsNone(VennProvider().decide(request, cases[:2], HashEmbedder()))

    def test_backup_restore_preserves_original_revision(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            original = LocalRepository(root / "original")
            item = record()
            revision = original.append(item)
            snapshot = root / "backup.jsonl"
            backup(original, snapshot)
            recovered = LocalRepository(root / "recovered")
            self.assertEqual(revision, restore(recovered, snapshot)["revision"])
            self.assertEqual([item], recovered.records(revision))
            with self.assertRaises(ValueError):
                restore(recovered, snapshot)
            snapshot.write_text("damaged")
            fresh = LocalRepository(root / "fresh")
            with self.assertRaises(ValueError):
                restore(fresh, snapshot)
            self.assertEqual([], fresh.records())

    @unittest.skipUnless(has("mcp"), "requires MCP")
    def test_mcp_scope_and_registered_tools(self):
        import asyncio
        from sagekit.mcp_server import create_mcp

        with tempfile.TemporaryDirectory() as temp:
            app = Application(LocalRepository(Path(temp)))
            credentials = {"reader": {}}
            with self.assertRaises(PermissionError):
                create_mcp(app, credentials, "unknown")
            mcp = create_mcp(app, credentials, "reader")
            tools = asyncio.run(mcp.list_tools())
            self.assertTrue({"add_knowledge", "check_gate", "record_approval", "record_outcome",
                             "promote_verified_change"} <= {tool.name for tool in tools})
            result = asyncio.run(mcp.call_tool("snapshot", {}))
            self.assertIsNotNone(result)
