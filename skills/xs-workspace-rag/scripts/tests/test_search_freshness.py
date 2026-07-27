import sqlite3
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPTS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS_DIR))

import workspace_rag_server as server


class SearchFreshnessTest(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.execute(
            """
            CREATE TABLE chunks (
                id INTEGER PRIMARY KEY,
                file_path TEXT,
                chunk_index INTEGER,
                content TEXT,
                access_count INTEGER,
                last_accessed TEXT
            )
            """
        )
        self.conn.execute(
            "INSERT INTO chunks VALUES (1, 'archive/old.md', 0, 'old content', 0, NULL)"
        )
        server._conn = self.conn
        server._workspace = "/workspace"
        server._workspace_name = "workspace"
        server._embedding_ids = None
        server._embedding_matrix = None

    def tearDown(self):
        self.conn.close()
        server._conn = None

    def search(self, forgetting):
        with (
            patch.object(server, "search_fts", return_value={1: 1.0}),
            patch.object(server, "memory_decay", return_value=1.0),
            patch("workspace_rag.get_path_weight", return_value=1.0),
            patch("workspace_rag.get_freshness_score", return_value=0.25),
        ):
            results, _query_embedding, _degraded_reason = server.do_search(
                "old content", mode="keyword", forgetting=forgetting
            )
            return results[0]

    def test_forgetting_off_ignores_freshness(self):
        result = self.search(forgetting=False)

        self.assertEqual(result["freshness"], 1.0)
        self.assertEqual(result["score"], 1.0)

    def test_forgetting_on_applies_freshness(self):
        result = self.search(forgetting=True)

        self.assertEqual(result["freshness"], 0.25)
        self.assertEqual(result["score"], 0.25)


if __name__ == "__main__":
    unittest.main()
