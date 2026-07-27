import http.client
import json
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

import workspace_rag
import workspace_rag_server as server_module


class _Cursor:
    def __init__(self, value):
        self.value = value

    def fetchone(self):
        return (self.value,)


class _Connection:
    def execute(self, sql, _params=()):
        return _Cursor(0)


class WorkspaceRAGServerConcurrencyTest(unittest.TestCase):
    def setUp(self):
        server_module._workspace = "/tmp/test-workspace"
        server_module._workspace_name = "test-workspace"
        server_module._db_path = Path("/tmp/nonexistent-workspace-rag.db")
        server_module._conn = _Connection()
        server_module._embedding_ids = np.array([], dtype=np.int64)
        server_module._embedding_matrix = np.empty((0, 384), dtype=np.float32)
        server_module._vector_index = None
        server_module._vector_backend = "numpy"
        server_module._fact_embeddings = []
        server_module._reindex_lock = threading.Lock()
        server_module._reindex_state_lock = threading.Lock()
        server_module._reindex_in_progress = False
        server_module._reindex_source = None
        server_module._reindex_started_at = 0
        server_module._last_reindex_duration_ms = None
        server_module._last_reindex_error = None
        server_module._query_encode_lock = threading.Lock()
        server_module._query_cache_lock = threading.Lock()
        server_module._query_embedding_cache.clear()

        self.server = server_module.WorkspaceRAGHTTPServer(
            ("127.0.0.1", 0), server_module.WorkspaceRAGHandler
        )
        self.server_thread = threading.Thread(
            target=self.server.serve_forever, daemon=True
        )
        self.server_thread.start()
        self.host, self.port = self.server.server_address

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.server_thread.join(timeout=1)

    def _request(self, method, path):
        connection = http.client.HTTPConnection(self.host, self.port, timeout=2)
        connection.request(method, path)
        response = connection.getresponse()
        body = response.read()
        connection.close()
        return response.status, body

    def test_health_responds_while_manual_reindex_runs(self):
        reindex_started = threading.Event()
        allow_reindex_to_finish = threading.Event()

        def slow_index(_workspace, force=False):
            reindex_started.set()
            self.assertTrue(allow_reindex_to_finish.wait(timeout=2))

        with (
            mock.patch.object(workspace_rag, "index_workspace", side_effect=slow_index),
            mock.patch.object(server_module, "_reload_db_and_caches"),
        ):
            started = time.monotonic()
            reindex_status, reindex_body = self._request("POST", "/reindex")
            accepted_elapsed = time.monotonic() - started
            self.assertTrue(reindex_started.wait(timeout=1))

            started = time.monotonic()
            health_status, health_body = self._request("GET", "/health")
            health_elapsed = time.monotonic() - started

            busy_status, _ = self._request("POST", "/reindex")
            allow_reindex_to_finish.set()
            deadline = time.monotonic() + 2
            while server_module._reindex_lock.locked() and time.monotonic() < deadline:
                time.sleep(0.01)

        self.assertEqual(reindex_status, 202)
        self.assertLess(accepted_elapsed, 0.3)
        self.assertEqual(json.loads(reindex_body)["status"], "accepted")
        self.assertEqual(health_status, 200)
        self.assertLess(health_elapsed, 0.3)
        health = json.loads(health_body)
        self.assertEqual(health["service"], "workspace-rag")
        self.assertEqual(health["api_version"], 1)
        self.assertTrue(health["reindex_in_progress"])
        self.assertEqual(busy_status, 409)
        self.assertFalse(server_module._reindex_lock.locked())

    def test_manual_reindex_error_is_visible_in_health(self):
        with mock.patch.object(
            workspace_rag, "index_workspace", side_effect=RuntimeError("index failed")
        ):
            reindex_status, _ = self._request("POST", "/reindex")
            deadline = time.monotonic() + 2
            while server_module._reindex_lock.locked() and time.monotonic() < deadline:
                time.sleep(0.01)
            health_status, health_body = self._request("GET", "/health")

        health = json.loads(health_body)
        self.assertEqual(reindex_status, 202)
        self.assertEqual(health_status, 200)
        self.assertFalse(health["reindex_in_progress"])
        self.assertEqual(health["last_reindex_error"], "index failed")

    def test_duplicate_query_does_not_start_concurrent_model_encode(self):
        encode_started = threading.Event()
        allow_encode_to_finish = threading.Event()

        class SlowModel:
            calls = 0

            def encode(self, _query, normalize_embeddings=True):
                self.calls += 1
                encode_started.set()
                self_test.assertTrue(allow_encode_to_finish.wait(timeout=2))
                return np.ones(384, dtype=np.float32)

        self_test = self
        model = SlowModel()
        server_module._model = model
        first_result = []

        first = threading.Thread(
            target=lambda: first_result.append(
                server_module._encode_query("same query", wait_seconds=1)
            )
        )
        first.start()
        self.assertTrue(encode_started.wait(timeout=1))

        started = time.monotonic()
        duplicate_result = server_module._encode_query(
            "same query", wait_seconds=0.02
        )
        duplicate_elapsed = time.monotonic() - started

        self.assertIsNone(duplicate_result)
        self.assertLess(duplicate_elapsed, 0.2)
        self.assertEqual(model.calls, 1)

        allow_encode_to_finish.set()
        first.join(timeout=1)
        self.assertEqual(len(first_result), 1)

        cached_result = server_module._encode_query(
            "same query", wait_seconds=0.02
        )
        self.assertIsNotNone(cached_result)
        self.assertEqual(model.calls, 1)

    def test_search_reports_keyword_fallback_when_encoder_is_busy(self):
        with (
            mock.patch.object(
                server_module,
                "do_search",
                return_value=([], None, "query_encoder_busy"),
            ),
            mock.patch.object(server_module, "grep_search", return_value=[]),
        ):
            status, body = self._request("GET", "/search?q=test")

        response = json.loads(body)
        self.assertEqual(status, 200)
        self.assertTrue(response["degraded"])
        self.assertEqual(response["degraded_reason"], "query_encoder_busy")

    def test_do_search_uses_keyword_results_when_encoder_is_busy(self):
        server_module._embedding_ids = np.array([1], dtype=np.int64)
        server_module._embedding_matrix = np.ones((1, 3), dtype=np.float32)
        with (
            mock.patch.object(server_module, "_encode_query", return_value=None),
            mock.patch.object(server_module, "search_fts", return_value={1: 1.0}),
            mock.patch.object(
                server_module,
                "load_chunk_rows",
                return_value={1: ("notes/example.md", 0, "keyword match", 0, None)},
            ),
            mock.patch.object(workspace_rag, "get_path_weight", return_value=1.0),
        ):
            results, query_embedding, degraded_reason = server_module.do_search(
                "keyword match", mode="hybrid"
            )

        self.assertIsNone(query_embedding)
        self.assertEqual(degraded_reason, "query_encoder_busy")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["file_path"], "notes/example.md")
        self.assertEqual(results[0]["fts_score"], 1.0)

    def test_faiss_top_candidates_match_numpy_reference(self):
        rng = np.random.default_rng(7)
        matrix = rng.normal(size=(200, 16)).astype(np.float32)
        matrix /= np.linalg.norm(matrix, axis=1, keepdims=True)
        ids = np.arange(1000, 1200, dtype=np.int64)
        query = rng.normal(size=16).astype(np.float32)
        query /= np.linalg.norm(query)
        index, backend = server_module.build_vector_index(matrix)

        actual = server_module.vector_top_candidates(
            query, 20, -1.0, ids, matrix, index
        )
        reference_scores = matrix @ query
        reference_positions = np.argsort(reference_scores)[-20:][::-1]
        reference = {
            int(ids[position]): float(reference_scores[position])
            for position in reference_positions
        }

        self.assertIn(backend, {"faiss", "numpy"})
        self.assertEqual(list(actual), list(reference))
        for chunk_id in reference:
            self.assertAlmostEqual(actual[chunk_id], reference[chunk_id], places=5)

    def test_fts_candidates_receive_exact_vector_scores(self):
        ids = np.array([10, 20, 30], dtype=np.int64)
        matrix = np.eye(3, dtype=np.float32)
        query = np.array([0.0, 0.8, 0.6], dtype=np.float32)
        vector_scores = {30: 0.6}

        server_module.add_exact_scores_for_fts(
            vector_scores,
            {10: 1.0, 20: 0.5},
            query,
            ids,
            matrix,
        )

        self.assertEqual(vector_scores[10], 0.0)
        self.assertAlmostEqual(vector_scores[20], 0.8)
        self.assertAlmostEqual(vector_scores[30], 0.6)

    def test_chunk_candidates_are_loaded_in_one_query(self):
        connection = mock.Mock()
        connection.execute.return_value.fetchall.return_value = [
            (20, "b.md", 1, "second", 2, "2026-07-26"),
            (10, "a.md", 0, "first", 1, None),
        ]

        rows = server_module.load_chunk_rows(connection, [10, 20])

        connection.execute.assert_called_once()
        self.assertEqual(rows[10], ("a.md", 0, "first", 1, None))
        self.assertEqual(rows[20], ("b.md", 1, "second", 2, "2026-07-26"))


if __name__ == "__main__":
    unittest.main()
