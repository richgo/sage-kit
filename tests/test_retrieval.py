import os
from pathlib import Path
import tempfile
import unittest

from sagekit.ingest import ingest
from sagekit.repository import LocalRepository
from sagekit.retrieval import Search
from sagekit.vectors import EmbeddingProfile, HashEmbedder, MemoryVectors, Vector


class RetrievalTests(unittest.TestCase):
    def test_exact_and_ranked_evidence_are_acl_filtered(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            public = root / "checkout.md"
            public.write_text("# Checkout\nUse idempotency keys for checkout retries.")
            secret = root / "incident.json"
            secret.write_text('{"id":"INC-1","title":"Checkout incident","impact":"checkout retries"}')
            repo = LocalRepository(root / "corpus")
            item = ingest(public, "adr", "commit1")
            repo.append(item)
            incident = ingest(secret, "incident", "commit2", acl=("sre",))
            repo.append(incident)
            search = Search(repo)
            self.assertEqual([], search.query(incident.id))
            self.assertEqual(item.id, search.query("checkout retries")[0]["record"]["id"])
            exact = search.query(incident.id, groups={"sre"})
            self.assertTrue(exact[0]["exact"])
            self.assertEqual("commit2", exact[0]["record"]["source"]["revision"])
            self.assertEqual([], search.query("unrelated_xyz"))

    def test_architecture_and_requirements_ingestion(self):
        with tempfile.TemporaryDirectory() as temp:
            file = Path(temp) / "artifact"
            for kind, content in (
                ("calm", '{"nodes":[{"unique-id":"checkout"}],"relationships":[]}'),
                ("likec4", 'model { checkout = system "Checkout" }'),
                ("requirement", '{"id":"REQ-1","title":"Checkout","text":"Retry safely"}'),
            ):
                with self.subTest(kind=kind):
                    file.write_text(content)
                    self.assertEqual(kind, ingest(file, kind, "commit1").kind)
            file.write_text('{"nodes":[]}')
            with self.assertRaises(ValueError):
                ingest(file, "calm", "commit1")

    def test_store_rejects_incompatible_profiles_and_prefilters(self):
        embed = HashEmbedder()
        vectors = MemoryVectors(embed.profile)
        vector = embed.embed("idempotency")
        vectors.upsert({"private": vector, "public": vector})
        self.assertEqual(["public"], [hit[0] for hit in vectors.search(vector, {"public"}, 1)])
        profile = EmbeddingProfile("other", "v1", "text", vector.profile.dimensions)
        with self.assertRaises(ValueError):
            vectors.search(Vector(profile, vector.values), {"public"}, 1)
