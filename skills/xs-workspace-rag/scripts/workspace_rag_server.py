#!/usr/bin/env python3
"""
Workspace RAG Server - 常駐HTTPサーバー版（facts CRUD + 忘却曲線オプション統合）

Features:
- facts CRUD: GET/POST /facts, GET /facts/similar, PUT/DELETE /facts/{id}
- 忘却曲線: ?forgetting=on のときのみ memory/notes/knowledge 配下に decay 適用 (default OFF)

Usage:
  cd scripts && uv run python workspace_rag_server.py -w /path/to/workspace -p 7890
  curl http://127.0.0.1:7890/search?q=サウナ&k=5
  curl http://127.0.0.1:7890/search?q=サウナ&forgetting=on
  curl http://127.0.0.1:7890/health
  curl -X POST http://127.0.0.1:7890/reindex
  curl -X POST http://127.0.0.1:7890/facts -d '{"facts":[{"text":"..."}]}'
"""

import argparse
from collections import OrderedDict
import hashlib
import json
import math
import os
import re
import signal
import sqlite3
import subprocess
import sys
import threading
import time
from datetime import datetime, date
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse, parse_qs

import torch
import numpy as np
from sentence_transformers import SentenceTransformer

try:
    import faiss
except ImportError:
    faiss = None

# ----------------------------------------------------------------------------
# Rotating log (stderr -> server.log にローテーション付きで永続化)
# ----------------------------------------------------------------------------

class _RotatingFile:
    """サイズ超過で server.log.1, .2, ... にローテートするシンプルなファイル。"""

    def __init__(self, path: str, max_bytes: int = 20 * 1024 * 1024, backup_count: int = 5):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.max_bytes = max_bytes
        self.backup_count = backup_count
        self._lock = threading.Lock()
        self._open()

    def _open(self):
        self.f = open(self.path, "a", buffering=1, encoding="utf-8")

    def write(self, data):
        with self._lock:
            try:
                self.f.write(data)
                if self.f.tell() > self.max_bytes:
                    self._rotate()
            except Exception:
                pass
        return len(data) if isinstance(data, (str, bytes)) else 0

    def flush(self):
        with self._lock:
            try:
                self.f.flush()
            except Exception:
                pass

    def _rotate(self):
        try:
            self.f.close()
        except Exception:
            pass
        for i in range(self.backup_count - 1, 0, -1):
            src = Path(str(self.path) + f".{i}")
            dst = Path(str(self.path) + f".{i + 1}")
            if src.exists():
                try:
                    src.rename(dst)
                except Exception:
                    pass
        if self.path.exists():
            try:
                self.path.rename(Path(str(self.path) + ".1"))
            except Exception:
                pass
        self._open()

    def isatty(self):
        return False


class _Tee:
    """複数ストリームへ並列書き込み。"""

    def __init__(self, *streams):
        self.streams = list(streams)

    def write(self, data):
        for s in self.streams:
            try:
                s.write(data)
                s.flush()
            except Exception:
                pass
        return len(data) if isinstance(data, (str, bytes)) else 0

    def flush(self):
        for s in self.streams:
            try:
                s.flush()
            except Exception:
                pass

    def isatty(self):
        return False

# 設定
DEFAULT_MODEL = "intfloat/multilingual-e5-small"
DEFAULT_PORT = 7890
VECTOR_WEIGHT = 0.7
FTS_WEIGHT = 0.3

# 忘却曲線（MemoryBank式をワークスペース検索向けに調整）
# R = 2^(-t / S) where S = BASE_HALF_LIFE * (1 + access_count * STRENGTH_PER_ACCESS)
BASE_HALF_LIFE = 30
STRENGTH_PER_ACCESS = 0.5
NO_DECAY_FILES = {"MEMORY.md", "AGENTS.md", "CLAUDE.md"}
NO_DECAY_DIRS = {"knowledge"}
# forgetting=on のとき NO_DECAY_FILES/NO_DECAY_DIRS 以外は全フォルダ対象に減衰

DATE_PATTERN = re.compile(r"(\d{4})[-_]?(\d{2})[-_]?(\d{2})")

# 自動reindex状態（グローバル）
_auto_reindex_enabled = True
_last_reindex_time = 0
_reindex_count = 0
_reindex_in_progress = False
_reindex_source = None
_reindex_started_at = 0
_last_reindex_duration_ms = None
_last_reindex_error = None

# グローバル（サーバー内で共有）
_model = None
_conn = None
_workspace = None
_workspace_name = None
_db_path = None
_embedding_ids = None       # np.ndarray (N,) int64
_embedding_matrix = None    # np.ndarray (N, 384) float32
_vector_index = None        # faiss.IndexFlatIP or None
_vector_backend = "numpy"
_fact_embeddings = None     # list[(id, np.ndarray)]

# SentenceTransformer.encode() を複数HTTPスレッドから同時実行すると、CPU推論が
# 競合して全リクエストがタイムアウトすることがある。同一クエリの再試行は
# キャッシュで吸収し、推論中に来た別リクエストは短時間だけ待ってから
# keyword-only に縮退させる。
_query_encode_lock = threading.Lock()
_query_cache_lock = threading.Lock()
_fact_embeddings_lock = threading.RLock()
_query_embedding_cache: OrderedDict[str, np.ndarray] = OrderedDict()
QUERY_EMBEDDING_CACHE_SIZE = 128
QUERY_ENCODE_WAIT_SECONDS = 2.0

# auto-reindex スレッドと HTTP リクエスト処理の間で _conn を保護する。
# RLock なので同一スレッドからのネスト acquire は OK。
_conn_lock = threading.RLock()
# 手動 /reindex と auto-reindex の多重実行を防ぐ。HTTP 自体は並行応答し、
# reindex 中も /health と既存キャッシュへの /search を利用可能にする。
_reindex_lock = threading.Lock()
_reindex_state_lock = threading.Lock()


def _encode_query(
    query: str,
    wait_seconds: float = QUERY_ENCODE_WAIT_SECONDS,
) -> Optional[np.ndarray]:
    """クエリ埋め込みを直列生成する。busy時はNoneを返して呼び出し側を縮退させる。"""
    with _query_cache_lock:
        cached = _query_embedding_cache.get(query)
        if cached is not None:
            _query_embedding_cache.move_to_end(query)
            return cached

    if not _query_encode_lock.acquire(timeout=wait_seconds):
        return None

    try:
        # ロック待ち中に先行リクエストが生成済みか再確認する。
        with _query_cache_lock:
            cached = _query_embedding_cache.get(query)
            if cached is not None:
                _query_embedding_cache.move_to_end(query)
                return cached

        with torch.no_grad():
            query_emb = _model.encode(
                f"query: {query}", normalize_embeddings=True
            ).astype(np.float32)

        with _query_cache_lock:
            _query_embedding_cache[query] = query_emb
            _query_embedding_cache.move_to_end(query)
            while len(_query_embedding_cache) > QUERY_EMBEDDING_CACHE_SIZE:
                _query_embedding_cache.popitem(last=False)
        return query_emb
    finally:
        _query_encode_lock.release()


def _encode_passage(text: str) -> np.ndarray:
    """fact更新用の埋め込みを、検索クエリと同じモデルロックで直列生成する。"""
    with _query_encode_lock:
        with torch.no_grad():
            return _model.encode(
                f"passage: {text}", normalize_embeddings=True
            ).astype(np.float32)


def _reload_db_and_caches():
    """新しい接続でキャッシュを構築し、完成後に短いロックで一括交換する。"""
    global _conn, _embedding_ids, _embedding_matrix, _vector_index
    global _vector_backend, _fact_embeddings

    new_conn = init_db(_db_path)
    try:
        new_embedding_ids, new_embedding_matrix = load_embeddings_cache(
            new_conn, _workspace_name
        )
        new_vector_index, new_vector_backend = build_vector_index(
            new_embedding_matrix
        )
        new_fact_embeddings = load_fact_embeddings(new_conn, _workspace_name)
    except Exception:
        new_conn.close()
        raise

    with _conn_lock:
        old_conn = _conn
        _conn = new_conn
        _embedding_ids = new_embedding_ids
        _embedding_matrix = new_embedding_matrix
        _vector_index = new_vector_index
        _vector_backend = new_vector_backend
    with _fact_embeddings_lock:
        _fact_embeddings = new_fact_embeddings

    if old_conn is not None:
        try:
            old_conn.close()
        except Exception:
            pass


def _run_reindex(
    source: str,
    lock_already_acquired: bool = False,
    started_event: Optional[threading.Event] = None,
) -> bool:
    """reindexを1本だけ実行する。実行中は既存キャッシュを提供し続ける。"""
    global _last_reindex_time, _reindex_count
    global _reindex_in_progress, _reindex_source, _reindex_started_at
    global _last_reindex_duration_ms, _last_reindex_error

    if not lock_already_acquired and not _reindex_lock.acquire(blocking=False):
        return False

    started_at = time.time()
    with _reindex_state_lock:
        _reindex_in_progress = True
        _reindex_source = source
        _reindex_started_at = started_at
        _last_reindex_error = None
    if started_event is not None:
        started_event.set()

    try:
        from workspace_rag import index_workspace

        print(f"[{source}-reindex] Starting...", file=sys.stderr, flush=True)
        index_workspace(_workspace, force=False)
        _reload_db_and_caches()

        duration_ms = round((time.time() - started_at) * 1000, 1)
        with _reindex_state_lock:
            _last_reindex_time = time.time()
            _reindex_count += 1
            _last_reindex_duration_ms = duration_ms
        print(
            f"[{source}-reindex] Done in {duration_ms}ms. "
            f"{len(_embedding_ids)} chunks / {len(_fact_embeddings)} facts cached. "
            f"(count={_reindex_count})",
            file=sys.stderr,
            flush=True,
        )
        return True
    except Exception as exc:
        with _reindex_state_lock:
            _last_reindex_error = str(exc)
        print(f"[{source}-reindex] Error: {exc}", file=sys.stderr, flush=True)
        return True
    finally:
        with _reindex_state_lock:
            _reindex_in_progress = False
            _reindex_source = None
            _reindex_started_at = 0
        _reindex_lock.release()


# ----------------------------------------------------------------------------
# DB / Index helpers
# ----------------------------------------------------------------------------

def get_db_path(workspace: str) -> Path:
    workspace_hash = hashlib.md5(workspace.encode()).hexdigest()[:8]
    return Path(workspace) / ".workspace_rag" / f"index_{workspace_hash}.db"


def init_db(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA cache_size = -2000")

    # 忘却曲線用カラム追加（既存DBとの後方互換）
    for col_def in (
        "ALTER TABLE chunks ADD COLUMN access_count INTEGER DEFAULT 0",
        "ALTER TABLE chunks ADD COLUMN last_accessed TEXT",
    ):
        try:
            conn.execute(col_def)
        except sqlite3.OperationalError:
            pass

    # facts テーブル（memory-rag から移植 + workspace カラム追加）
    conn.execute("""
        CREATE TABLE IF NOT EXISTS facts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            workspace TEXT NOT NULL,
            text TEXT NOT NULL,
            embedding BLOB,
            source_file TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            old_values TEXT,
            access_count INTEGER DEFAULT 0,
            last_accessed TEXT,
            is_active INTEGER DEFAULT 1,
            fact_date TEXT
        )
    """)
    try:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_facts_workspace ON facts(workspace, is_active)")
    except sqlite3.OperationalError:
        pass

    conn.commit()
    return conn


def ensure_fts(conn: sqlite3.Connection):
    conn.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
            content,
            content='chunks',
            content_rowid='id',
            tokenize='trigram'
        )
    """)
    conn.execute("""
        CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
            INSERT INTO chunks_fts(rowid, content) VALUES (new.id, new.content);
        END
    """)
    conn.execute("""
        CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
            INSERT INTO chunks_fts(chunks_fts, rowid, content) VALUES('delete', old.id, old.content);
        END
    """)
    conn.execute("""
        CREATE TRIGGER IF NOT EXISTS chunks_au AFTER UPDATE ON chunks BEGIN
            INSERT INTO chunks_fts(chunks_fts, rowid, content) VALUES('delete', old.id, old.content);
            INSERT INTO chunks_fts(rowid, content) VALUES (new.id, new.content);
        END
    """)
    conn.commit()


def populate_fts(conn: sqlite3.Connection, workspace_name: str):
    chunk_count = conn.execute(
        "SELECT COUNT(*) FROM chunks WHERE workspace = ?",
        (workspace_name,)
    ).fetchone()[0]
    try:
        fts_count = conn.execute("SELECT COUNT(*) FROM chunks_fts").fetchone()[0]
    except sqlite3.OperationalError:
        fts_count = 0

    if chunk_count > 0 and fts_count == chunk_count:
        print(f"FTS5 index already populated ({fts_count} chunks); skipping rebuild", file=sys.stderr, flush=True)
        return

    print("Building FTS5 index (rebuild)...", file=sys.stderr, flush=True)
    t0 = time.time()
    conn.execute("INSERT INTO chunks_fts(chunks_fts) VALUES('rebuild')")
    conn.commit()
    count = conn.execute("SELECT COUNT(*) FROM chunks_fts").fetchone()[0]
    print(f"FTS5 indexed {count} chunks in {time.time() - t0:.1f}s", file=sys.stderr, flush=True)


def load_embeddings_cache(conn: sqlite3.Connection, workspace_name: str):
    rows = conn.execute(
        "SELECT id, embedding FROM chunks "
        "WHERE workspace = ? AND embedding IS NOT NULL ORDER BY id",
        (workspace_name,)
    ).fetchall()

    if not rows:
        return np.array([], dtype=np.int64), np.empty((0, 384), dtype=np.float32)

    ids = np.array([r[0] for r in rows], dtype=np.int64)
    vecs = np.vstack([
        np.frombuffer(r[1], dtype=np.float16).astype(np.float32)
        for r in rows
    ])
    return ids, vecs


def build_vector_index(matrix: np.ndarray):
    """完全一致のFaiss IP indexを構築。利用不能ならNumPyへ戻す。"""
    requested = os.environ.get("RAG_VECTOR_BACKEND", "faiss").lower()
    if requested != "faiss" or faiss is None or len(matrix) == 0:
        return None, "numpy"
    try:
        index = faiss.IndexFlatIP(matrix.shape[1])
        index.add(np.ascontiguousarray(matrix, dtype=np.float32))
        return index, "faiss"
    except Exception as exc:
        print(f"[vector] Faiss unavailable; using NumPy: {exc}", file=sys.stderr)
        return None, "numpy"


def vector_top_candidates(
    query_emb: np.ndarray,
    top_n: int,
    min_score: float,
    ids: np.ndarray,
    matrix: np.ndarray,
    index,
) -> dict[int, float]:
    """完全一致の上位候補だけをPythonへ戻す。全42万件のdict化を避ける。"""
    count = min(top_n, len(ids))
    if count <= 0:
        return {}

    if index is not None:
        distances, positions = index.search(
            np.ascontiguousarray(query_emb.reshape(1, -1), dtype=np.float32),
            count,
        )
        positions = positions[0]
        distances = distances[0]
    else:
        scores = matrix @ query_emb
        if count == len(scores):
            positions = np.arange(len(scores))
        else:
            positions = np.argpartition(scores, -count)[-count:]
        distances = scores[positions]
        order = np.argsort(distances)[::-1]
        positions = positions[order]
        distances = distances[order]

    return {
        int(ids[position]): float(score)
        for position, score in zip(positions, distances)
        if position >= 0 and score >= min_score
    }


def add_exact_scores_for_fts(
    vector_scores: dict[int, float],
    fts_scores: dict[int, float],
    query_emb: np.ndarray,
    ids: np.ndarray,
    matrix: np.ndarray,
) -> None:
    """FTS候補のベクトル値を正確に補い、従来hybrid順位を維持する。"""
    missing = sorted(set(fts_scores) - set(vector_scores))
    if not missing or len(ids) == 0:
        return
    missing_ids = np.asarray(missing, dtype=np.int64)
    positions = np.searchsorted(ids, missing_ids)
    valid = positions < len(ids)
    valid &= ids[np.minimum(positions, len(ids) - 1)] == missing_ids
    if not np.any(valid):
        return
    valid_ids = missing_ids[valid]
    valid_positions = positions[valid]
    scores = matrix[valid_positions] @ query_emb
    for chunk_id, score in zip(valid_ids, scores):
        vector_scores[int(chunk_id)] = float(score)


def load_fact_embeddings(conn: sqlite3.Connection, workspace_name: str) -> list[tuple[int, np.ndarray]]:
    rows = conn.execute(
        "SELECT id, embedding FROM facts WHERE workspace = ? AND is_active = 1 AND embedding IS NOT NULL",
        (workspace_name,)
    ).fetchall()
    cached = []
    for row_id, blob in rows:
        vec = np.frombuffer(blob, dtype=np.float16).astype(np.float32)
        cached.append((row_id, vec))
    return cached


# ----------------------------------------------------------------------------
# 忘却曲線
# ----------------------------------------------------------------------------

def extract_file_date(file_path: str) -> Optional[date]:
    m = DATE_PATTERN.search(file_path)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    return None


def memory_decay(file_date: Optional[date], file_path: str,
                 access_count: int = 0, last_accessed: Optional[str] = None) -> float:
    """忘却曲線（MemoryBank式をワークスペース検索向けに調整）
    R = 2^(-t / S)
    NO_DECAY_FILES (MEMORY/AGENTS/CLAUDE.md) と NO_DECAY_DIRS (knowledge/) は
    1.0 を返す。それ以外は全フォルダ対象（memory/notes/information-hub/logs/skills 等）。
    """
    filename = Path(file_path).name
    if filename in NO_DECAY_FILES:
        return 1.0

    parts = Path(file_path).parts
    if any(d in NO_DECAY_DIRS for d in parts):
        return 1.0

    if last_accessed:
        try:
            last_date = date.fromisoformat(last_accessed[:10])
            t = (date.today() - last_date).days
        except (ValueError, TypeError):
            t = None
    else:
        t = None

    if t is None:
        if file_date is None:
            return 0.5
        t = (date.today() - file_date).days

    if t < 0:
        return 1.0

    S = BASE_HALF_LIFE * (1 + access_count * STRENGTH_PER_ACCESS)
    return math.exp(-math.log(2) * t / S)


# ----------------------------------------------------------------------------
# Facts CRUD
# ----------------------------------------------------------------------------

def add_facts(facts: list[dict]) -> list[dict]:
    global _model, _conn, _fact_embeddings, _workspace_name

    results = []
    now = datetime.now().isoformat()

    for fact in facts:
        text = fact.get("text", "").strip()
        if not text:
            continue
        source_file = fact.get("source_file")
        fact_date = fact.get("fact_date")

        emb = _encode_passage(text)
        emb_blob = emb.astype(np.float16).tobytes()

        nearest_id = None
        nearest_score = 0.0
        with _fact_embeddings_lock:
            fact_embeddings = list(_fact_embeddings)
        for fid, fvec in fact_embeddings:
            score = float(np.dot(fvec, emb))
            if score > nearest_score:
                nearest_score = score
                nearest_id = fid

        with _conn_lock:
            cursor = _conn.execute("""
                INSERT INTO facts (workspace, text, embedding, source_file, created_at, updated_at, fact_date)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (_workspace_name, text, emb_blob, source_file, now, now, fact_date))
            new_id = cursor.lastrowid

        with _fact_embeddings_lock:
            _fact_embeddings.append((new_id, emb))

        results.append({
            "action": "ADD",
            "id": new_id,
            "text": text,
            "nearest_id": nearest_id,
            "nearest_similarity": round(nearest_score, 4) if nearest_id else None,
        })

    with _conn_lock:
        _conn.commit()
    if results:
        export_facts_to_markdown()
    return results


def update_fact(fact_id: int, text: Optional[str] = None,
                source_file: Optional[str] = None, fact_date: Optional[str] = None) -> Optional[dict]:
    global _model, _conn, _fact_embeddings, _workspace_name

    with _conn_lock:
        row = _conn.execute(
            "SELECT text, source_file, old_values, fact_date FROM facts WHERE id = ? AND workspace = ? AND is_active = 1",
            (fact_id, _workspace_name)
        ).fetchone()
    if not row:
        return None

    old_text, old_source, old_values_str, old_fact_date = row
    now = datetime.now().isoformat()

    new_text = text if text is not None else old_text
    new_source = source_file if source_file is not None else old_source
    new_fact_date = fact_date if fact_date is not None else old_fact_date

    text_changed = text is not None and text.strip() != old_text
    if text_changed:
        new_text = text.strip()
        try:
            old_values = json.loads(old_values_str) if old_values_str else []
        except (json.JSONDecodeError, TypeError):
            old_values = []
        old_values.append({"text": old_text, "updated_at": now})
        old_values_json = json.dumps(old_values, ensure_ascii=False)

        emb = _encode_passage(new_text)
        emb_blob = emb.astype(np.float16).tobytes()

        with _conn_lock:
            _conn.execute("""
                UPDATE facts SET text = ?, embedding = ?, source_file = ?,
                    updated_at = ?, old_values = ?, fact_date = ?
                WHERE id = ?
            """, (new_text, emb_blob, new_source, now, old_values_json, new_fact_date, fact_id))

        with _fact_embeddings_lock:
            _fact_embeddings = [
                (fid, fvec) if fid != fact_id else (fid, emb)
                for fid, fvec in _fact_embeddings
            ]
    else:
        with _conn_lock:
            _conn.execute("""
                UPDATE facts SET source_file = ?, updated_at = ?, fact_date = ?
                WHERE id = ?
            """, (new_source, now, new_fact_date, fact_id))

    with _conn_lock:
        _conn.commit()
    export_facts_to_markdown()
    return {
        "action": "UPDATE",
        "id": fact_id,
        "text": new_text,
        "old_text": old_text if text_changed else None,
        "text_changed": text_changed,
    }


def delete_fact(fact_id: int) -> Optional[dict]:
    global _conn, _fact_embeddings, _workspace_name

    with _conn_lock:
        row = _conn.execute(
            "SELECT text FROM facts WHERE id = ? AND workspace = ?",
            (fact_id, _workspace_name)
        ).fetchone()
        if not row:
            return None
        deleted_text = row[0]

        _conn.execute("DELETE FROM facts WHERE id = ? AND workspace = ?", (fact_id, _workspace_name))
        _conn.commit()

    with _fact_embeddings_lock:
        _fact_embeddings = [
            (fid, fvec) for fid, fvec in _fact_embeddings if fid != fact_id
        ]

    export_facts_to_markdown()
    return {"action": "DELETE", "id": fact_id, "text": deleted_text}


# ----------------------------------------------------------------------------
# facts → git 追跡用 Markdown スナップショット書き出し
# ----------------------------------------------------------------------------
# 背景: facts は DELETE FROM facts で物理削除され、削除ログも履歴テーブルも無い。
# 「何が消えたか」を後から復元できないので、POST/PUT/DELETE のたびに全 active facts を
# id 昇順で knowledge/rag_facts.md に書き出して git で追跡可能にする。
# 正本はあくまで SQLite DB（.workspace_rag/）。この .md は検索・embedding には一切使わない
# （chunk index からは DEFAULT_EXCLUDE_PATTERNS で除外）。
RAG_FACTS_MD_REL = "knowledge/rag_facts.md"

RAG_FACTS_MD_HEADER = (
    "<!-- AUTO-GENERATED — DO NOT EDIT BY HAND -->\n"
    "<!-- workspace-RAG facts のスナップショット。正本は .workspace_rag/ の SQLite DB。 -->\n"
    "<!-- /facts API (POST/PUT/DELETE) のたびに workspace_rag_server.py の "
    "export_facts_to_markdown() が id 昇順で再生成する。手で編集しても次の更新で上書きされる。 -->\n"
    "<!-- 目的: facts は物理削除で履歴が残らないため、git diff で「何が消えたか」を追えるようにする。 -->\n"
)


def export_facts_to_markdown() -> Optional[str]:
    """全 active facts を id 昇順で knowledge/rag_facts.md に書き出す。

    - 並びを id 昇順で固定 → 1ファクト追加/削除でも diff が最小限になる
    - 失敗しても API レスポンスは壊さない（warning ログのみ）
    - 原子的に temp → rename で書き込む（書きかけファイルを残さない）
    戻り値: 書き出したパス（成功時）、None（失敗 or workspace 未設定時）。
    """
    global _conn, _workspace, _workspace_name
    if not _workspace:
        return None
    try:
        with _conn_lock:
            rows = _conn.execute(
                """
                SELECT id, text, source_file, created_at, updated_at, fact_date
                FROM facts
                WHERE workspace = ? AND is_active = 1
                ORDER BY id
                """,
                (_workspace_name,),
            ).fetchall()

        lines = [RAG_FACTS_MD_HEADER,
                 f"# workspace-RAG facts snapshot ({_workspace_name})\n",
                 f"facts: {len(rows)} 件\n"]
        for fid, text, source_file, created_at, updated_at, fact_date in rows:
            lines.append(f"## fact #{fid}\n")
            meta = [f"- created: {created_at}",
                    f"- updated: {updated_at}"]
            if fact_date:
                meta.append(f"- fact_date: {fact_date}")
            if source_file:
                meta.append(f"- source_file: {source_file}")
            lines.append("\n".join(meta) + "\n")
            lines.append((text or "").strip() + "\n")

        content = "\n".join(lines).rstrip() + "\n"

        out_path = Path(_workspace) / RAG_FACTS_MD_REL
        out_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = out_path.with_suffix(out_path.suffix + ".tmp")
        tmp_path.write_text(content, encoding="utf-8")
        tmp_path.replace(out_path)
        return str(out_path)
    except Exception as e:
        print(f"[rag_facts.md] export failed: {e}", file=sys.stderr)
        return None


def find_similar_facts(query: str, top_k: int = 3) -> list[dict]:
    global _model, _conn, _fact_embeddings

    with _fact_embeddings_lock:
        fact_embeddings = list(_fact_embeddings)
    if not fact_embeddings:
        return []

    query_emb = _encode_query(query)
    if query_emb is None:
        return []

    scored = []
    for fid, fvec in fact_embeddings:
        score = float(np.dot(fvec, query_emb))
        scored.append((score, fid))
    scored.sort(key=lambda x: x[0], reverse=True)
    scored = scored[:top_k]

    results = []
    for score, fid in scored:
        with _conn_lock:
            row = _conn.execute(
                "SELECT text, source_file, created_at, updated_at, access_count, fact_date FROM facts WHERE id = ?",
                (fid,)
            ).fetchone()
        if row:
            results.append({
                "id": fid,
                "text": row[0],
                "source_file": row[1],
                "score": round(score, 4),
                "created_at": row[2],
                "updated_at": row[3],
                "access_count": row[4] or 0,
                "fact_date": row[5],
            })
    return results


def search_facts(query_emb: np.ndarray, top_k: int = 3,
                 date_from: Optional[str] = None, date_to: Optional[str] = None) -> list[dict]:
    """ファクトをベクトル検索。/search で chunks 検索と並走する。"""
    global _fact_embeddings, _conn

    with _fact_embeddings_lock:
        fact_embeddings = list(_fact_embeddings)
    if not fact_embeddings:
        return []

    scored = []
    for fid, fvec in fact_embeddings:
        score = float(np.dot(fvec, query_emb))
        if score >= 0.5:
            scored.append((score, fid))

    scored.sort(key=lambda x: x[0], reverse=True)
    scored = scored[:top_k]

    results = []
    today = date.today().isoformat()
    for score, fid in scored:
        with _conn_lock:
            row = _conn.execute(
                "SELECT text, source_file, created_at, updated_at, access_count, fact_date FROM facts WHERE id = ?",
                (fid,)
            ).fetchone()
        if row:
            text, source_file, created_at, updated_at, access_count, fact_date = row
            if fact_date and (date_from or date_to):
                if date_from and fact_date < date_from:
                    continue
                if date_to and fact_date > date_to:
                    continue
            results.append({
                "type": "fact",
                "id": fid,
                "text": text,
                "source_file": source_file,
                "score": round(score, 4),
                "created_at": created_at,
                "updated_at": updated_at,
                "access_count": access_count or 0,
                "fact_date": fact_date,
            })
            with _conn_lock:
                _conn.execute(
                    "UPDATE facts SET access_count = COALESCE(access_count, 0) + 1, last_accessed = ? WHERE id = ?",
                    (today, fid)
                )
    if results:
        with _conn_lock:
            _conn.commit()

    return results


# ----------------------------------------------------------------------------
# Search
# ----------------------------------------------------------------------------

def search_fts(conn: sqlite3.Connection, query: str, workspace_name: str) -> dict[int, float]:
    scores = {}
    stripped_query = query.strip()
    use_like = len(stripped_query) < 3

    def like_rows():
        terms = [t for t in re.split(r"\s+", stripped_query) if t]
        if not terms:
            return []
        clauses = " AND ".join(["content LIKE ?"] * len(terms))
        params = [workspace_name] + [f"%{t}%" for t in terms]
        cursor = conn.execute(
            f"SELECT id FROM chunks WHERE workspace = ? AND {clauses} LIMIT 50",
            params
        )
        return [(r[0], 1.0) for r in cursor.fetchall()]

    try:
        if use_like:
            rows = like_rows()
        else:
            cursor = conn.execute(
                "SELECT rowid, rank FROM chunks_fts WHERE chunks_fts MATCH ? ORDER BY rank LIMIT 50",
                (query,)
            )
            rows = cursor.fetchall()
            if not rows:
                rows = like_rows()

        if not rows:
            return scores

        if use_like:
            for row_id, score in rows:
                scores[row_id] = 1.0
        else:
            max_abs_rank = max(abs(r[1]) for r in rows)
            if max_abs_rank == 0:
                return scores
            for row_id, rank in rows:
                scores[row_id] = abs(rank) / max_abs_rank
    except sqlite3.OperationalError:
        pass

    return scores


def load_chunk_rows(conn: sqlite3.Connection, chunk_ids: list[int]) -> dict[int, tuple]:
    """検索候補を1回のSELECTで取得し、候補数分のSQLite往復を避ける。"""
    if not chunk_ids:
        return {}
    placeholders = ",".join("?" for _ in chunk_ids)
    rows = conn.execute(
        "SELECT id, file_path, chunk_index, content, access_count, last_accessed "
        f"FROM chunks WHERE id IN ({placeholders})",
        chunk_ids,
    ).fetchall()
    return {row[0]: row[1:] for row in rows}


def do_search(query: str, top_k: int = 5, min_score: float = 0.3,
              mode: str = "hybrid", forgetting: bool = False
              ) -> tuple[list[dict], Optional[np.ndarray], Optional[str]]:
    """常駐サーバー用の検索。
    forgetting=True のときのみ memory/notes/knowledge 配下に decay を掛け、access_count を更新。
    """
    global _model, _conn, _workspace_name, _embedding_ids, _embedding_matrix
    global _vector_index, _workspace

    vector_scores = {}
    fts_scores = {}
    query_emb = None
    degraded_reason = None

    with _conn_lock:
        embedding_ids = _embedding_ids
        embedding_matrix = _embedding_matrix
        vector_index = _vector_index

    if mode in ("hybrid", "vector") and embedding_matrix is not None and len(embedding_matrix) > 0:
        query_emb = _encode_query(query)
        if query_emb is None:
            degraded_reason = "query_encoder_busy"
        else:
            vector_scores = vector_top_candidates(
                query_emb,
                max(top_k * 4, 20),
                min_score,
                embedding_ids,
                embedding_matrix,
                vector_index,
            )

    if mode in ("hybrid", "keyword"):
        with _conn_lock:
            fts_scores = search_fts(_conn, query, _workspace_name)
    if mode == "hybrid" and query_emb is not None:
        add_exact_scores_for_fts(
            vector_scores,
            fts_scores,
            query_emb,
            embedding_ids,
            embedding_matrix,
        )

    all_ids = set(vector_scores.keys()) | set(fts_scores.keys())
    if not all_ids:
        return [], query_emb, degraded_reason

    scored = []
    for chunk_id in all_ids:
        v = vector_scores.get(chunk_id, 0.0)
        f = fts_scores.get(chunk_id, 0.0)
        if mode == "vector":
            combined = v
        elif mode == "keyword":
            combined = f
        else:
            combined = VECTOR_WEIGHT * v + FTS_WEIGHT * f
        scored.append((combined, chunk_id, v, f))

    scored.sort(key=lambda x: x[0], reverse=True)
    # 後で path_weight と、forgetting=on 時だけ freshness/decay を掛けて
    # 再ソートするので少し多めに保持
    scored = scored[:max(top_k * 4, 20)]

    with _conn_lock:
        chunk_rows = load_chunk_rows(
            _conn,
            [chunk_id for _, chunk_id, _, _ in scored],
        )

    results = []
    decay_updates: list[int] = []
    for combined, chunk_id, v_score, f_score in scored:
        row = chunk_rows.get(chunk_id)
        if not row:
            continue
        file_path, chunk_index, content, access_count, last_accessed = row
        access_count = access_count or 0

        from workspace_rag import get_path_weight, get_freshness_score
        pw = get_path_weight(file_path)
        # forgetting=off は全期間を平等に扱う契約。古い発信アーカイブを
        # mtime だけで沈めない。時間減衰を明示した検索だけ freshness を使う。
        fr = get_freshness_score(file_path, _workspace) if forgetting else 1.0

        decay = 1.0
        if forgetting:
            file_date = extract_file_date(file_path)
            decay = memory_decay(file_date, file_path, access_count, last_accessed)
            # NO_DECAY 以外は access_count を更新（強化学習の対象）
            if decay < 1.0:
                decay_updates.append(chunk_id)

        final_score = combined * pw * fr * decay

        result = {
            "file_path": file_path,
            "chunk_index": chunk_index,
            "content": content,
            "score": round(final_score, 4),
            "base_score": round(combined, 4),
            "path_weight": pw,
            "freshness": round(fr, 2),
        }
        if forgetting:
            result["decay"] = round(decay, 4)
            result["access_count"] = access_count
        if mode == "hybrid":
            result["vector_score"] = round(v_score, 4)
            result["fts_score"] = round(f_score, 4)
        results.append(result)

    results.sort(key=lambda r: r["score"], reverse=True)
    results = results[:top_k]

    # forgetting=on のときだけ access_count を更新（強化学習）
    if forgetting and decay_updates:
        today = date.today().isoformat()
        returned_keys = {
            (result["file_path"], result["chunk_index"]) for result in results
        }
        returned_decay_ids = [
            chunk_id
            for chunk_id in decay_updates
            if (
                chunk_id in chunk_rows
                and (chunk_rows[chunk_id][0], chunk_rows[chunk_id][1])
                in returned_keys
            )
        ]
        with _conn_lock:
            for cid in returned_decay_ids:
                _conn.execute(
                    "UPDATE chunks SET access_count = COALESCE(access_count, 0) + 1, last_accessed = ? WHERE id = ?",
                    (today, cid)
                )
            _conn.commit()

    return results, query_emb, degraded_reason


def grep_search(query: str, workspace: str, max_results: int = 10) -> list[dict]:
    try:
        cmd = [
            "rg", "--json", "-i", "-l",
            "--max-count", "1",
            "--glob", "!.git",
            "--glob", "!node_modules",
            "--glob", "!__pycache__",
            "--glob", "!.venv",
            "--glob", "!*.js",
            "--glob", "!*.min.js",
            "--glob", "!*.bundle.js",
            "--glob", "!.workspace_rag",
            "--glob", "!.xangi",
            "--glob", "!.obsidian",
            "--glob", "!dist",
            "--glob", "!build",
            "--glob", "!tmp",
            "--glob", "!logs",
            "--glob", "!*.pyc",
            "--glob", "!*.png",
            "--glob", "!*.jpg",
            "--glob", "!*.jpeg",
            "--glob", "!*.gif",
            "--glob", "!*.mp3",
            "--glob", "!*.mp4",
            "--glob", "!*.pdf",
            "--glob", "!*.zip",
            "--glob", "!*.lock",
            query, workspace
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)

        files = []
        for line in result.stdout.strip().split("\n"):
            if not line:
                continue
            try:
                obj = json.loads(line)
                if obj.get("type") == "match":
                    path = obj["data"]["path"]["text"]
                    rel = os.path.relpath(path, workspace)
                    files.append(rel)
            except (json.JSONDecodeError, KeyError):
                continue

        if not files:
            return []

        grep_results = []
        for file_path in files[:max_results]:
            abs_path = os.path.join(workspace, file_path)
            try:
                cmd2 = ["rg", "-i", "-n", "-C", "2", "--max-count", "3", query, abs_path]
                r = subprocess.run(cmd2, capture_output=True, text=True, timeout=3)
                context = r.stdout.strip()[:500] if r.stdout else ""
                grep_results.append({
                    "file_path": file_path,
                    "context": context,
                    "source": "grep",
                })
            except Exception:
                grep_results.append({
                    "file_path": file_path,
                    "context": "",
                    "source": "grep",
                })

        return grep_results
    except FileNotFoundError:
        return []
    except subprocess.TimeoutExpired:
        return []
    except Exception:
        return []


# ----------------------------------------------------------------------------
# HTTP handler
# ----------------------------------------------------------------------------

class WorkspaceRAGHTTPServer(ThreadingHTTPServer):
    request_queue_size = 64
    daemon_threads = True


class WorkspaceRAGHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def _send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            # クライアント側timeout後の切断はサーバー障害ではない。
            return

    def _read_json_body(self) -> Optional[dict]:
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length == 0:
            return {}
        body = self.rfile.read(content_length).decode("utf-8")
        return json.loads(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        if parsed.path == "/health":
            file_count = 0
            db_size_mb = 0
            fact_count = 0
            try:
                with _conn_lock:
                    cur = _conn.execute(
                        "SELECT COUNT(DISTINCT file_path) FROM chunks WHERE workspace = ?",
                        (_workspace_name,)
                    )
                    file_count = cur.fetchone()[0]
                    fact_count = _conn.execute(
                        "SELECT COUNT(*) FROM facts WHERE workspace = ? AND is_active = 1",
                        (_workspace_name,)
                    ).fetchone()[0]
                db_size_mb = round(_db_path.stat().st_size / (1024 * 1024), 1) if _db_path.exists() else 0
            except Exception:
                pass
            from datetime import datetime as _dt, timezone
            self._send_json({
                "status": "ok",
                "service": "workspace-rag",
                "api_version": 1,
                "workspace": _workspace,
                "workspace_name": _workspace_name,
                "chunks_cached": len(_embedding_ids) if _embedding_ids is not None else 0,
                "files_indexed": file_count,
                "facts": fact_count,
                "facts_cached": len(_fact_embeddings) if _fact_embeddings else 0,
                "db_size_mb": db_size_mb,
                "port": DEFAULT_PORT,
                "model": DEFAULT_MODEL,
                "vector_backend": _vector_backend,
                "vector_index_size": (
                    int(_vector_index.ntotal) if _vector_index is not None else 0
                ),
                "auto_reindex": _auto_reindex_enabled,
                "reindex_count": _reindex_count,
                "last_reindex": _dt.fromtimestamp(_last_reindex_time, tz=timezone.utc).isoformat() if _last_reindex_time else None,
                "reindex_in_progress": _reindex_in_progress,
                "reindex_source": _reindex_source,
                "reindex_started_at": _dt.fromtimestamp(_reindex_started_at, tz=timezone.utc).isoformat() if _reindex_started_at else None,
                "last_reindex_duration_ms": _last_reindex_duration_ms,
                "last_reindex_error": _last_reindex_error,
            })

        elif parsed.path == "/search":
            query = params.get("q", [""])[0]
            if not query:
                self._send_json({"error": "Missing query parameter 'q'"}, 400)
                return

            top_k = int(params.get("k", ["5"])[0])
            min_score = float(params.get("s", ["0.3"])[0])
            mode = params.get("mode", ["hybrid"])[0]
            if mode not in ("hybrid", "vector", "keyword"):
                mode = "hybrid"
            r2ag = params.get("r2ag", [""])[0].lower() in ("1", "true", "yes")
            forgetting = params.get("forgetting", ["off"])[0].lower() in ("1", "true", "yes", "on")

            t0 = time.time()
            results, query_emb, degraded_reason = do_search(
                query, top_k, min_score, mode, forgetting
            )

            # ファクト検索を相乗り（memory-rag 互換）
            fact_results = []
            if _fact_embeddings and query_emb is not None:
                fact_results = search_facts(query_emb, top_k=3)

            elapsed_ms = (time.time() - t0) * 1000

            grep_results = grep_search(query, _workspace, max_results=5)
            rag_files = {r["file_path"] for r in results}
            grep_results = [g for g in grep_results if g["file_path"] not in rag_files]

            response = {
                "query": query,
                "mode": mode,
                "forgetting": forgetting,
                "elapsed_ms": round(elapsed_ms, 1),
                "count": len(results),
                "results": results,
                "facts": fact_results,
                "facts_count": len(fact_results),
                "grep_count": len(grep_results),
                "grep_results": grep_results,
            }
            if degraded_reason:
                response["degraded"] = True
                response["degraded_reason"] = degraded_reason

            if r2ag and results:
                r2ag_text = "以下の文書を参考に質問に答えてください。\n関連度が高いほど信頼できます。\n\n"
                for i, r in enumerate(results, 1):
                    score = r["score"]
                    label = "高" if score >= 0.7 else "中" if score >= 0.5 else "低"
                    r2ag_text += f"**文書{i}** [{r['file_path']}] [関連度: {score:.2f} ({label})]\n"
                    r2ag_text += f"{r['content'][:300]}...\n\n"
                response["r2ag"] = r2ag_text

            self._send_json(response)

        elif parsed.path == "/facts":
            with _conn_lock:
                facts = _conn.execute(
                    "SELECT id, text, source_file, created_at, updated_at, access_count, is_active, fact_date FROM facts WHERE workspace = ? ORDER BY updated_at DESC",
                    (_workspace_name,)
                ).fetchall()
            self._send_json({
                "count": len(facts),
                "facts": [
                    {"id": r[0], "text": r[1], "source_file": r[2],
                     "created_at": r[3], "updated_at": r[4], "access_count": r[5], "is_active": r[6],
                     "fact_date": r[7]}
                    for r in facts
                ],
            })

        elif parsed.path == "/facts/similar":
            query = params.get("q", [""])[0]
            if not query:
                self._send_json({"error": "Missing query parameter 'q'"}, 400)
                return
            top_k = int(params.get("k", ["3"])[0])
            t0 = time.time()
            results = find_similar_facts(query, top_k)
            elapsed_ms = (time.time() - t0) * 1000
            self._send_json({
                "query": query,
                "elapsed_ms": round(elapsed_ms, 1),
                "count": len(results),
                "results": results,
            })

        else:
            self._send_json({"error": "Not found. Use /search /health /facts /facts/similar"}, 404)

    def do_POST(self):
        global _embedding_ids, _embedding_matrix, _fact_embeddings
        parsed = urlparse(self.path)

        if parsed.path == "/reindex":
            if not _reindex_lock.acquire(blocking=False):
                self._send_json({
                    "status": "busy",
                    "message": "Reindex already in progress",
                }, 409)
                return

            started_event = threading.Event()
            reindex_thread = threading.Thread(
                target=_run_reindex,
                args=("manual", True, started_event),
                daemon=True,
            )
            try:
                reindex_thread.start()
            except Exception as exc:
                _reindex_lock.release()
                self._send_json({"error": f"Failed to start reindex: {exc}"}, 500)
                return
            started_event.wait(timeout=1)
            self._send_json({
                "status": "accepted",
                "message": "Reindex started",
            }, 202)

        elif parsed.path in ("/facts", "/extract"):
            try:
                data = self._read_json_body() or {}
                facts_input = data.get("facts", [])
                if not facts_input:
                    self._send_json({"error": "Missing 'facts' array in body"}, 400)
                    return
                t0 = time.time()
                results = add_facts(facts_input)
                elapsed_ms = (time.time() - t0) * 1000
                self._send_json({
                    "status": "ok",
                    "elapsed_ms": round(elapsed_ms, 1),
                    "results": results,
                    "total_facts": len(_fact_embeddings),
                })
            except json.JSONDecodeError:
                self._send_json({"error": "Invalid JSON"}, 400)
            except Exception as e:
                self._send_json({"error": str(e)}, 500)

        else:
            self._send_json({"error": "Not found"}, 404)

    def do_PUT(self):
        parsed = urlparse(self.path)
        m = re.match(r"^/facts/(\d+)$", parsed.path)
        if not m:
            self._send_json({"error": "Not found. Use PUT /facts/{id}"}, 404)
            return
        fact_id = int(m.group(1))
        try:
            data = self._read_json_body() or {}
            result = update_fact(
                fact_id,
                text=data.get("text"),
                source_file=data.get("source_file"),
                fact_date=data.get("fact_date"),
            )
            if result is None:
                self._send_json({"error": f"Fact #{fact_id} not found"}, 404)
                return
            self._send_json({"status": "ok", "result": result})
        except json.JSONDecodeError:
            self._send_json({"error": "Invalid JSON"}, 400)
        except Exception as e:
            self._send_json({"error": str(e)}, 500)

    def do_DELETE(self):
        parsed = urlparse(self.path)
        m = re.match(r"^/facts/(\d+)$", parsed.path)
        if not m:
            self._send_json({"error": "Not found. Use DELETE /facts/{id}"}, 404)
            return
        fact_id = int(m.group(1))
        try:
            result = delete_fact(fact_id)
            if result is None:
                self._send_json({"error": f"Fact #{fact_id} not found"}, 404)
                return
            self._send_json({"status": "ok", "result": result})
        except Exception as e:
            self._send_json({"error": str(e)}, 500)


# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------

def write_pid(workspace: str):
    pid_file = Path(workspace) / ".workspace_rag" / "server.pid"
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    pid_file.write_text(str(os.getpid()))


def remove_pid(workspace: str):
    pid_file = Path(workspace) / ".workspace_rag" / "server.pid"
    if pid_file.exists():
        pid_file.unlink()


def main():
    global _model, _conn, _workspace, _workspace_name, _db_path
    global _embedding_ids, _embedding_matrix, _vector_index, _vector_backend
    global _fact_embeddings, DEFAULT_PORT

    parser = argparse.ArgumentParser(description="Workspace RAG Server (with facts CRUD + forgetting curve)")
    parser.add_argument("-w", "--workspace", required=True, help="Workspace directory")
    parser.add_argument("-p", "--port", type=int, default=DEFAULT_PORT, help=f"Port (default: {DEFAULT_PORT})")
    parser.add_argument("--no-auto-reindex", action="store_true", help="Disable auto-reindex (default: enabled, every 30min)")
    parser.add_argument("--reindex-interval", type=int, default=1800, help="Auto-reindex interval in seconds (default: 1800)")
    parser.add_argument("--no-log-file", action="store_true", help="Disable rotating server.log (default: enabled)")
    parser.add_argument("--log-max-bytes", type=int, default=20 * 1024 * 1024, help="Log rotation threshold in bytes (default: 20MB)")
    parser.add_argument("--log-backup-count", type=int, default=5, help="Number of rotated log files to keep (default: 5)")
    args = parser.parse_args()

    _workspace = str(Path(args.workspace).resolve())
    _workspace_name = Path(_workspace).name
    DEFAULT_PORT = args.port
    _db_path = get_db_path(_workspace)

    # ローテーション付きで server.log に永続化（既存 stderr にも tee）
    if not args.no_log_file:
        log_path = Path(_workspace) / ".workspace_rag" / "server.log"
        try:
            log_file = _RotatingFile(str(log_path), max_bytes=args.log_max_bytes, backup_count=args.log_backup_count)
            sys.stderr = _Tee(sys.stderr, log_file)
            sys.stdout = _Tee(sys.stdout, log_file)
            print(f"[log] Rotating log enabled: {log_path} (max={args.log_max_bytes} bytes, backup={args.log_backup_count})", file=sys.stderr, flush=True)
        except Exception as e:
            print(f"[log] Failed to enable rotating log: {e}", file=sys.stderr, flush=True)

    if not _db_path.exists():
        print(f"Error: Index not found at {_db_path}", file=sys.stderr)
        print("Run: cd scripts && uv run python workspace_rag.py index -w <workspace>", file=sys.stderr)
        sys.exit(1)

    print(f"Loading model: {DEFAULT_MODEL}...", file=sys.stderr, flush=True)
    t0 = time.time()
    _model = SentenceTransformer(DEFAULT_MODEL)
    print(f"Model loaded in {time.time() - t0:.1f}s", file=sys.stderr, flush=True)

    _conn = init_db(_db_path)

    ensure_fts(_conn)
    populate_fts(_conn, _workspace_name)

    print("Caching embeddings...", file=sys.stderr, flush=True)
    t1 = time.time()
    _embedding_ids, _embedding_matrix = load_embeddings_cache(_conn, _workspace_name)
    _vector_index, _vector_backend = build_vector_index(_embedding_matrix)
    print(f"Cached {len(_embedding_ids)} chunk embeddings in {time.time() - t1:.1f}s", file=sys.stderr, flush=True)
    print(f"Vector backend: {_vector_backend}", file=sys.stderr, flush=True)

    _fact_embeddings = load_fact_embeddings(_conn, _workspace_name)
    print(f"Cached {len(_fact_embeddings)} fact embeddings", file=sys.stderr, flush=True)

    # 起動時に現在の facts を knowledge/rag_facts.md へ書き出す（mutation を待たず現状反映）
    _exported = export_facts_to_markdown()
    if _exported:
        print(f"Exported facts snapshot to {_exported}", file=sys.stderr, flush=True)

    write_pid(_workspace)

    def shutdown(signum, frame):
        print("\nShutting down...", file=sys.stderr, flush=True)
        remove_pid(_workspace)
        if _conn:
            _conn.close()
        sys.exit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    global _auto_reindex_enabled, _last_reindex_time, _reindex_count
    _auto_reindex_enabled = not args.no_auto_reindex
    _last_reindex_time = time.time()
    _reindex_count = 0

    if _auto_reindex_enabled:
        def auto_reindex():
            import gc
            interval = args.reindex_interval
            while True:
                time.sleep(interval)
                if not _run_reindex("auto"):
                    print("[auto-reindex] Skipped: reindex already in progress", file=sys.stderr, flush=True)
                    continue
                gc.collect()
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()

        reindex_thread = threading.Thread(target=auto_reindex, daemon=True)
        reindex_thread.start()

    server = WorkspaceRAGHTTPServer(("127.0.0.1", DEFAULT_PORT), WorkspaceRAGHandler)
    print(f"Workspace RAG Server running on http://127.0.0.1:{DEFAULT_PORT}", file=sys.stderr, flush=True)
    print(f"  Workspace: {_workspace} ({_workspace_name})", file=sys.stderr, flush=True)
    print(f"  Chunks: {len(_embedding_ids)}", file=sys.stderr, flush=True)
    print(f"  Facts:  {len(_fact_embeddings)}", file=sys.stderr, flush=True)
    if _auto_reindex_enabled:
        print(f"  Auto-reindex: every {args.reindex_interval}s (disable with --no-auto-reindex)", file=sys.stderr, flush=True)
    else:
        print(f"  Auto-reindex: disabled", file=sys.stderr, flush=True)
    print(f"  Endpoints:", file=sys.stderr, flush=True)
    print(f"    GET    /search?q=...&k=5&s=0.3&forgetting=on", file=sys.stderr, flush=True)
    print(f"    GET    /health", file=sys.stderr, flush=True)
    print(f"    GET    /facts", file=sys.stderr, flush=True)
    print(f"    GET    /facts/similar?q=...&k=3", file=sys.stderr, flush=True)
    print(f"    POST   /facts        body: {{facts:[{{text:...}}]}}", file=sys.stderr, flush=True)
    print(f"    PUT    /facts/{{id}}   body: {{text:...}}", file=sys.stderr, flush=True)
    print(f"    DELETE /facts/{{id}}", file=sys.stderr, flush=True)
    print(f"    POST   /reindex", file=sys.stderr, flush=True)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        shutdown(None, None)


if __name__ == "__main__":
    main()
