#!/usr/bin/env python3
"""
Workspace RAG Server - 常駐HTTPサーバー版（facts CRUD + 忘却曲線オプション統合）

特徴:
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
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse, parse_qs

import torch
import numpy as np
from sentence_transformers import SentenceTransformer


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

# 忘却曲線（MemoryBank式）
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

# グローバル（サーバー内で共有）
_model = None
_conn = None
_workspace = None
_workspace_name = None
_db_path = None
_embedding_ids = None       # np.ndarray (N,) int64
_embedding_matrix = None    # np.ndarray (N, 384) float32
_fact_embeddings = None     # list[(id, np.ndarray)]

# auto-reindex スレッドと HTTP リクエスト処理の間で _conn を保護する。
# RLock なので同一スレッドからのネスト acquire は OK。
_conn_lock = threading.RLock()


def _swap_conn(new_conn: sqlite3.Connection):
    """グローバル _conn を新しい接続に差し替え、古い接続は安全に閉じる。

    パターン: 新規接続を先に作って差し替える → 「closed _conn が一瞬でも見える」
    隙間をゼロにする。すでに _conn を握って execute 中の処理は古い接続を最後まで
    使い切ってから close される。
    """
    global _conn
    with _conn_lock:
        old_conn = _conn
        _conn = new_conn
    if old_conn is not None:
        try:
            old_conn.close()
        except Exception:
            pass


def _ensure_conn():
    """_conn が壊れていたら作り直す。手動 /reindex 等のリカバリ手段としても使う。"""
    global _conn
    with _conn_lock:
        try:
            if _conn is not None:
                _conn.execute("SELECT 1").fetchone()
                return
        except sqlite3.ProgrammingError:
            pass
        except Exception:
            pass
        # 壊れている or None → 作り直す
        new_conn = init_db(_db_path)
        old = _conn
        _conn = new_conn
    if old is not None:
        try:
            old.close()
        except Exception:
            pass


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
    print("Building FTS5 index (rebuild)...", file=sys.stderr, flush=True)
    t0 = time.time()
    conn.execute("INSERT INTO chunks_fts(chunks_fts) VALUES('rebuild')")
    conn.commit()
    count = conn.execute("SELECT COUNT(*) FROM chunks_fts").fetchone()[0]
    print(f"FTS5 indexed {count} chunks in {time.time() - t0:.1f}s", file=sys.stderr, flush=True)


def load_embeddings_cache(conn: sqlite3.Connection, workspace_name: str):
    rows = conn.execute(
        "SELECT id, embedding FROM chunks WHERE workspace = ? AND embedding IS NOT NULL",
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
    """忘却曲線（MemoryBank式）
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

        with torch.no_grad():
            emb = _model.encode(f"passage: {text}", normalize_embeddings=True).astype(np.float32)
        emb_blob = emb.astype(np.float16).tobytes()

        nearest_id = None
        nearest_score = 0.0
        for fid, fvec in _fact_embeddings:
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

        with torch.no_grad():
            emb = _model.encode(f"passage: {new_text}", normalize_embeddings=True).astype(np.float32)
        emb_blob = emb.astype(np.float16).tobytes()

        with _conn_lock:
            _conn.execute("""
                UPDATE facts SET text = ?, embedding = ?, source_file = ?,
                    updated_at = ?, old_values = ?, fact_date = ?
                WHERE id = ?
            """, (new_text, emb_blob, new_source, now, old_values_json, new_fact_date, fact_id))

        _fact_embeddings = [(fid, fvec) if fid != fact_id else (fid, emb)
                            for fid, fvec in _fact_embeddings]
    else:
        with _conn_lock:
            _conn.execute("""
                UPDATE facts SET source_file = ?, updated_at = ?, fact_date = ?
                WHERE id = ?
            """, (new_source, now, new_fact_date, fact_id))

    with _conn_lock:
        _conn.commit()
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

    _fact_embeddings = [(fid, fvec) for fid, fvec in _fact_embeddings if fid != fact_id]

    return {"action": "DELETE", "id": fact_id, "text": deleted_text}


def find_similar_facts(query: str, top_k: int = 3) -> list[dict]:
    global _model, _conn, _fact_embeddings

    if not _fact_embeddings:
        return []

    with torch.no_grad():
        query_emb = _model.encode(f"query: {query}", normalize_embeddings=True).astype(np.float32)

    scored = []
    for fid, fvec in _fact_embeddings:
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

    if not _fact_embeddings:
        return []

    scored = []
    for fid, fvec in _fact_embeddings:
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
    use_like = len(query.strip()) < 3

    try:
        if use_like:
            cursor = conn.execute(
                "SELECT id FROM chunks WHERE workspace = ? AND content LIKE ? LIMIT 50",
                (workspace_name, f"%{query}%")
            )
            rows = [(r[0], 1.0) for r in cursor.fetchall()]
        else:
            cursor = conn.execute(
                "SELECT rowid, rank FROM chunks_fts WHERE chunks_fts MATCH ? ORDER BY rank LIMIT 50",
                (query,)
            )
            rows = cursor.fetchall()

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


def do_search(query: str, top_k: int = 5, min_score: float = 0.3,
              mode: str = "hybrid", forgetting: bool = False) -> list[dict]:
    """常駐サーバー用の検索。
    forgetting=True のときのみ memory/notes/knowledge 配下に decay を掛け、access_count を更新。
    """
    global _model, _conn, _workspace_name, _embedding_ids, _embedding_matrix, _workspace

    vector_scores = {}
    fts_scores = {}

    if mode in ("hybrid", "vector") and _embedding_matrix is not None and len(_embedding_matrix) > 0:
        with torch.no_grad():
            query_emb = _model.encode(f"query: {query}", normalize_embeddings=True).astype(np.float32)
        scores = _embedding_matrix @ query_emb
        for i in range(len(scores)):
            if scores[i] >= min_score:
                vector_scores[int(_embedding_ids[i])] = float(scores[i])

    if mode in ("hybrid", "keyword"):
        with _conn_lock:
            fts_scores = search_fts(_conn, query, _workspace_name)

    all_ids = set(vector_scores.keys()) | set(fts_scores.keys())
    if not all_ids:
        return []

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
    # 後で path_weight/freshness/decay を掛けて再ソートするので少し多めに保持
    scored = scored[:max(top_k * 4, 20)]

    results = []
    decay_updates: list[int] = []
    for combined, chunk_id, v_score, f_score in scored:
        with _conn_lock:
            cursor = _conn.execute(
                "SELECT file_path, chunk_index, content, access_count, last_accessed FROM chunks WHERE id = ?",
                (chunk_id,)
            )
            row = cursor.fetchone()
        if not row:
            continue
        file_path, chunk_index, content, access_count, last_accessed = row
        access_count = access_count or 0

        from workspace_rag import get_path_weight, get_freshness_score
        pw = get_path_weight(file_path)
        fr = get_freshness_score(file_path, _workspace)

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
        returned_ids = {r["file_path"] for r in results}
        # 上位 top_k 件のうち decay 対象だったものだけ更新
        top_chunk_ids = [
            cid for (_, cid, _, _) in scored
            if any(r["file_path"] for r in results)  # 上位フィルタ
        ][:top_k]
        with _conn_lock:
            for cid in decay_updates[:top_k]:
                _conn.execute(
                    "UPDATE chunks SET access_count = COALESCE(access_count, 0) + 1, last_accessed = ? WHERE id = ?",
                    (today, cid)
                )
            _conn.commit()

    return results


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

class WorkspaceRAGHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def _send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

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
                "workspace": _workspace,
                "workspace_name": _workspace_name,
                "chunks_cached": len(_embedding_ids) if _embedding_ids is not None else 0,
                "files_indexed": file_count,
                "facts": fact_count,
                "facts_cached": len(_fact_embeddings) if _fact_embeddings else 0,
                "db_size_mb": db_size_mb,
                "port": DEFAULT_PORT,
                "model": DEFAULT_MODEL,
                "auto_reindex": _auto_reindex_enabled,
                "reindex_count": _reindex_count,
                "last_reindex": _dt.fromtimestamp(_last_reindex_time, tz=timezone.utc).isoformat() if _last_reindex_time else None,
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
            results = do_search(query, top_k, min_score, mode, forgetting)

            # ファクト検索を相乗り（memory-rag 互換）
            fact_results = []
            if _fact_embeddings:
                with torch.no_grad():
                    query_emb = _model.encode(f"query: {query}", normalize_embeddings=True).astype(np.float32)
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
            global _fact_embeddings
            try:
                from workspace_rag import index_workspace
                index_workspace(_workspace, force=False)
                # 新規接続を先に作って atomic に差し替え → closed _conn 残留からの
                # 自己復旧手段としても機能する。
                new_conn = init_db(_db_path)
                _swap_conn(new_conn)
                with _conn_lock:
                    _embedding_ids, _embedding_matrix = load_embeddings_cache(_conn, _workspace_name)
                    _fact_embeddings = load_fact_embeddings(_conn, _workspace_name)
                self._send_json({
                    "status": "ok",
                    "message": "Reindex complete",
                    "chunks_cached": len(_embedding_ids),
                    "facts_cached": len(_fact_embeddings),
                })
            except Exception as e:
                self._send_json({"error": str(e)}, 500)

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
    global _embedding_ids, _embedding_matrix, _fact_embeddings, DEFAULT_PORT

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
    print(f"Cached {len(_embedding_ids)} chunk embeddings in {time.time() - t1:.1f}s", file=sys.stderr, flush=True)

    _fact_embeddings = load_fact_embeddings(_conn, _workspace_name)
    print(f"Cached {len(_fact_embeddings)} fact embeddings", file=sys.stderr, flush=True)

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
            global _embedding_ids, _embedding_matrix, _fact_embeddings, _last_reindex_time, _reindex_count
            import gc
            interval = args.reindex_interval
            while True:
                time.sleep(interval)
                try:
                    # ループ先頭で _conn の健全性を確認。壊れていたら作り直す。
                    # 前回ループで何かが起きて closed のまま残ったケースの自己修復。
                    _ensure_conn()

                    from workspace_rag import index_workspace
                    print(f"[auto-reindex] Starting (interval={interval}s)...", file=sys.stderr, flush=True)
                    index_workspace(_workspace, force=False)

                    # 新規接続を先に作って atomic に差し替え → 「closed _conn が
                    # 一瞬でも見える」隙間をゼロにする。
                    new_conn = init_db(_db_path)
                    _swap_conn(new_conn)
                    with _conn_lock:
                        _embedding_ids, _embedding_matrix = load_embeddings_cache(_conn, _workspace_name)
                        _fact_embeddings = load_fact_embeddings(_conn, _workspace_name)
                    _last_reindex_time = time.time()
                    _reindex_count += 1
                    gc.collect()
                    if torch.cuda.is_available():
                        torch.cuda.empty_cache()
                    rss_mb = os.popen("ps -o rss= -p %d" % os.getpid()).read().strip()
                    rss_mb = int(rss_mb) // 1024 if rss_mb else 0
                    print(f"[auto-reindex] Done. {len(_embedding_ids)} chunks / {len(_fact_embeddings)} facts cached. (count={_reindex_count}, RSS={rss_mb}MB)", file=sys.stderr, flush=True)
                except Exception as e:
                    print(f"[auto-reindex] Error: {e}", file=sys.stderr, flush=True)

        reindex_thread = threading.Thread(target=auto_reindex, daemon=True)
        reindex_thread.start()

    server = HTTPServer(("127.0.0.1", DEFAULT_PORT), WorkspaceRAGHandler)
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
