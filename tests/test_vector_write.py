from pathlib import Path
import tempfile
import unittest

from sagekit.application import Principal
from sagekit.config import create_application
from sagekit.repository import LocalRepository
from test_foundation import record


class VectorWriteTests(unittest.TestCase):
    def test_add_indexes_before_any_query_and_survives_restart(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            identity = Principal(scopes=frozenset({"write"}))
            app = create_application(root)
            entry = record("Stable checkout request identifiers")
            first = app.add(identity, entry.as_dict())
            reopened = create_application(root)
            query = reopened.search.embedder.embed(entry.title + "\n" + entry.body)
            self.assertEqual([entry.id], [key for key, _ in
                             reopened.search.vectors.search(query, {entry.id}, 1)])
            self.assertEqual(first, reopened.add(identity, entry.as_dict()))
            self.assertEqual([entry], LocalRepository(root).records())

    def test_query_only_backfills_missing_vectors(self):
        with tempfile.TemporaryDirectory() as temp:
            app = create_application(Path(temp))
            entry = record("Stable checkout request identifiers")
            app.repo.append(entry)
            self.assertEqual(set(), app.search.vectors.existing({entry.id}))
            app.query(Principal(), "checkout identifiers")
            self.assertEqual({entry.id}, app.search.vectors.existing({entry.id}))
            embed = app.search.embedder.embed

            def query_only(text):
                self.assertEqual("checkout identifiers", text)
                return embed(text)

            app.search.embedder.embed = query_only
            self.assertEqual(entry.id, app.query(Principal(), "checkout identifiers")[0]["record"]["id"])

    def test_failed_vector_write_is_repaired_by_retry_without_a_second_event(self):
        with tempfile.TemporaryDirectory() as temp:
            app = create_application(Path(temp))
            identity = Principal(scopes=frozenset({"write"}))
            entry = record("Retry safely")
            upsert = app.search.vectors.upsert

            def unavailable(vectors):
                raise OSError("vector store unavailable")

            app.search.vectors.upsert = unavailable
            with self.assertRaises(OSError):
                app.add(identity, entry.as_dict())
            self.assertEqual([entry], app.repo.records())
            revision = app.repo.snapshot()
            app.search.vectors.upsert = upsert
            self.assertEqual(revision, app.add(identity, entry.as_dict())["revision"])
            self.assertEqual({entry.id}, app.search.vectors.existing({entry.id}))
