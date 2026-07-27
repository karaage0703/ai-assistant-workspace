import tempfile
import unittest
from pathlib import Path

from workspace_rag import get_file_hash, init_db, update_file_chunks


class IncrementalChunkUpdateTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "index.db"
        self.conn = init_db(self.db_path)
        self.workspace = "workspace"
        self.file_path = "logs/sessions/current.jsonl"

    def tearDown(self):
        self.conn.close()
        self.temp_dir.cleanup()

    def _update(self, content):
        return update_file_chunks(
            self.conn,
            self.workspace,
            self.file_path,
            content,
            get_file_hash(content),
        )

    def _rows(self):
        return self.conn.execute(
            """SELECT id, chunk_index, content, embedding, file_hash
               FROM chunks
               WHERE workspace = ? AND file_path = ?
               ORDER BY chunk_index""",
            (self.workspace, self.file_path),
        ).fetchall()

    def test_append_reuses_unchanged_prefix_embeddings(self):
        original = "a" * 1600
        initial_count = self._update(original)
        self.conn.execute(
            """UPDATE chunks SET embedding = X'0102'
               WHERE workspace = ? AND file_path = ?""",
            (self.workspace, self.file_path),
        )
        self.conn.commit()
        original_rows = self._rows()

        appended = original + "b" * 300
        inserted_count = self._update(appended)
        updated_rows = self._rows()

        self.assertEqual(initial_count, len(original_rows))
        self.assertLess(inserted_count, len(updated_rows))
        reused_count = len(updated_rows) - inserted_count
        self.assertGreater(reused_count, 0)
        self.assertEqual(
            [row[0] for row in updated_rows[:reused_count]],
            [row[0] for row in original_rows[:reused_count]],
        )
        self.assertTrue(
            all(row[3] == b"\x01\x02" for row in updated_rows[:reused_count])
        )
        self.assertTrue(all(row[4] == get_file_hash(appended) for row in updated_rows))

    def test_edit_at_start_replaces_all_chunks(self):
        original = "a" * 1600
        self._update(original)
        original_ids = [row[0] for row in self._rows()]

        changed = "z" + original[1:]
        inserted_count = self._update(changed)
        changed_rows = self._rows()

        self.assertEqual(inserted_count, len(changed_rows))
        self.assertTrue(set(original_ids).isdisjoint(row[0] for row in changed_rows))


if __name__ == "__main__":
    unittest.main()
