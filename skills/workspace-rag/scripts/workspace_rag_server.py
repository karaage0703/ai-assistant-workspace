#!/usr/bin/env python3
"""
Workspace RAG Server - 常駐HTTPサーバー版
モデルを1回ロードして常駐し、検索を高速化（~1s/query → ~100ms/query）

Usage:
  cd scripts && uv run python workspace_rag_server.py -w /path/to/workspace -p 7891
  curl http://127.0.0.1:7891/search?q=サウナ&k=5
  curl http://127.0.0.1:7891/health
  curl -X POST http://127.0.0.1:7891/reindex
"""

import argparse
import hashlib
import json
import os
import signal
import sqlite3
import sys
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import torch
import numpy as np
from sentence_transformers import SentenceTransformer

# 設定
DEFAULT_MODEL = "intfloat/multilingual-e5-small"
DEFAULT_PORT = 7891
VECTOR_WEIGHT = 0.7
FTS_WEIGHT = 0.3

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
_embedding_ids = None    # np.ndarray (N,) int64
_embedding_matrix = None  # np.ndarray (N, 384) float32


def get_db_path(workspace: str) -> Path:
    workspace_hash = hashlib.md5(workspace.encode()).hexdigest()[:8]
    return Path(workspace) / ".workspace_rag" / f"index_{workspace_hash}.db"


def init_db(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA cache_size = -2000")
    return conn


def ensure_fts(conn: sqlite3.Connection):
    """FTS5テーブルとトリガーを作成（なければ）"""
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
    """FTS5インデックスをrebuildで構築（content tableモード用）"""
    # rebuildはcontent tableモードで必須（直接INSERTではインデックスが不完全）
    print("Building FTS5 index (rebuild)...", file=sys.stderr, flush=True)
    t0 = time.time()
    conn.execute("INSERT INTO chunks_fts(chunks_fts) VALUES('rebuild')")
    conn.commit()
    count = conn.execute("SELECT COUNT(*) FROM chunks_fts").fetchone()[0]
    print(f"FTS5 indexed {count} chunks in {time.time() - t0:.1f}s", file=sys.stderr, flush=True)


def search_fts(conn: sqlite3.Connection, query: str, workspace_name: str) -> dict[int, float]:
    """FTS5キーワード検索（trigram: 3文字以上、2文字以下はLIKEフォールバック）"""
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


def load_embeddings_cache(conn: sqlite3.Connection, workspace_name: str):
    """全埋め込みをNumPy行列としてメモリにキャッシュ（高速ドット積用）"""
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


def do_search(query: str, top_k: int = 5, min_score: float = 0.3, mode: str = "hybrid") -> list[dict]:
    """常駐サーバー用の検索（hybrid/vector/keyword）"""
    global _model, _conn, _workspace_name, _embedding_ids, _embedding_matrix

    vector_scores = {}
    fts_scores = {}

    # ベクトル検索
    if mode in ("hybrid", "vector") and _embedding_matrix is not None and len(_embedding_matrix) > 0:
        with torch.no_grad():
            query_emb = _model.encode(f"query: {query}", normalize_embeddings=True).astype(np.float32)

        scores = _embedding_matrix @ query_emb

        for i in range(len(scores)):
            if scores[i] >= min_score:
                vector_scores[int(_embedding_ids[i])] = float(scores[i])

    # FTS5キーワード検索
    if mode in ("hybrid", "keyword"):
        fts_scores = search_fts(_conn, query, _workspace_name)

    # スコア統合
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
    scored = scored[:top_k]

    results = []
    for combined, chunk_id, v_score, f_score in scored:
        cursor = _conn.execute(
            "SELECT file_path, chunk_index, content FROM chunks WHERE id = ?",
            (chunk_id,)
        )
        row = cursor.fetchone()
        if row:
            file_path, chunk_index, content = row
            from workspace_rag import get_freshness_score
            fr = get_freshness_score(file_path, _workspace)
            final_score = combined * fr
            result = {
                "file_path": file_path,
                "chunk_index": chunk_index,
                "content": content,
                "score": round(final_score, 4),
                "base_score": round(combined, 4),
                "freshness": round(fr, 2),
            }
            if mode == "hybrid":
                result["vector_score"] = round(v_score, 4)
                result["fts_score"] = round(f_score, 4)
            results.append(result)

    # 鮮度適用後に再ソート
    results.sort(key=lambda r: r["score"], reverse=True)
    return results


class WorkspaceRAGHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # アクセスログを抑制

    def _send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        if parsed.path == "/health":
            # DBからファイル数を取得
            file_count = 0
            db_size_mb = 0
            try:
                cur = _conn.execute(f"SELECT COUNT(DISTINCT file_path) FROM chunks WHERE workspace = ?", (_workspace_name,))
                file_count = cur.fetchone()[0]
                db_size_mb = round(_db_path.stat().st_size / (1024 * 1024), 1) if _db_path.exists() else 0
            except Exception:
                pass
            from datetime import datetime, timezone
            self._send_json({
                "status": "ok",
                "workspace": _workspace,
                "workspace_name": _workspace_name,
                "chunks_cached": len(_embedding_ids) if _embedding_ids is not None else 0,
                "files_indexed": file_count,
                "db_size_mb": db_size_mb,
                "port": DEFAULT_PORT,
                "model": DEFAULT_MODEL,
                "auto_reindex": _auto_reindex_enabled,
                "reindex_count": _reindex_count,
                "last_reindex": datetime.fromtimestamp(_last_reindex_time, tz=timezone.utc).isoformat() if _last_reindex_time else None,
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

            t0 = time.time()
            results = do_search(query, top_k, min_score, mode)
            elapsed_ms = (time.time() - t0) * 1000

            response = {
                "query": query,
                "mode": mode,
                "elapsed_ms": round(elapsed_ms, 1),
                "count": len(results),
                "results": results,
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

        else:
            self._send_json({"error": "Not found. Use /search?q=... or /health"}, 404)

    def do_POST(self):
        global _embedding_ids, _embedding_matrix
        parsed = urlparse(self.path)

        if parsed.path == "/reindex":
            try:
                from workspace_rag import index_workspace
                index_workspace(_workspace, force=False)
                _embedding_ids, _embedding_matrix = load_embeddings_cache(_conn, _workspace_name)
                self._send_json({
                    "status": "ok",
                    "message": "Reindex complete",
                    "chunks_cached": len(_embedding_ids),
                })
            except Exception as e:
                self._send_json({"error": str(e)}, 500)
        else:
            self._send_json({"error": "Not found"}, 404)


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
    global _embedding_ids, _embedding_matrix, DEFAULT_PORT

    parser = argparse.ArgumentParser(description="Workspace RAG Server")
    parser.add_argument("-w", "--workspace", required=True, help="Workspace directory")
    parser.add_argument("-p", "--port", type=int, default=DEFAULT_PORT, help=f"Port (default: {DEFAULT_PORT})")
    parser.add_argument("--no-auto-reindex", action="store_true", help="Disable auto-reindex (default: enabled, every 30min)")
    parser.add_argument("--reindex-interval", type=int, default=1800, help="Auto-reindex interval in seconds (default: 1800)")
    args = parser.parse_args()

    _workspace = str(Path(args.workspace).resolve())
    _workspace_name = Path(_workspace).name
    DEFAULT_PORT = args.port
    _db_path = get_db_path(_workspace)

    if not _db_path.exists():
        print(f"Error: Index not found at {_db_path}", file=sys.stderr)
        print("Run: cd scripts && uv run python workspace_rag.py index -w <workspace>", file=sys.stderr)
        sys.exit(1)

    # モデルロード
    print(f"Loading model: {DEFAULT_MODEL}...", file=sys.stderr, flush=True)
    t0 = time.time()
    _model = SentenceTransformer(DEFAULT_MODEL)
    print(f"Model loaded in {time.time() - t0:.1f}s", file=sys.stderr, flush=True)

    # DB接続
    _conn = init_db(_db_path)

    # FTS5テーブル作成＋初回データ投入
    ensure_fts(_conn)
    populate_fts(_conn, _workspace_name)

    # 埋め込みをメモリにキャッシュ（NumPy行列）
    print("Caching embeddings...", file=sys.stderr, flush=True)
    t1 = time.time()
    _embedding_ids, _embedding_matrix = load_embeddings_cache(_conn, _workspace_name)
    print(f"Cached {len(_embedding_ids)} embeddings in {time.time() - t1:.1f}s", file=sys.stderr, flush=True)

    # PIDファイル
    write_pid(_workspace)

    # シグナルハンドラ
    def shutdown(signum, frame):
        print("\nShutting down...", file=sys.stderr, flush=True)
        remove_pid(_workspace)
        if _conn:
            _conn.close()
        sys.exit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    # 自動reindex（デフォルトON、--no-auto-reindexで無効化）
    import threading
    global _auto_reindex_enabled, _last_reindex_time, _reindex_count
    _auto_reindex_enabled = not args.no_auto_reindex
    _last_reindex_time = time.time()
    _reindex_count = 0

    if _auto_reindex_enabled:
        def auto_reindex():
            global _embedding_ids, _embedding_matrix, _last_reindex_time, _reindex_count, _conn
            import gc
            interval = args.reindex_interval
            while True:
                time.sleep(interval)
                try:
                    from workspace_rag import index_workspace
                    print(f"[auto-reindex] Starting (interval={interval}s)...", file=sys.stderr, flush=True)
                    index_workspace(_workspace, force=False)
                    # DB再接続してメモリリークを防止
                    try:
                        _conn.close()
                    except Exception:
                        pass
                    _conn = init_db(_db_path)
                    _embedding_ids, _embedding_matrix = load_embeddings_cache(_conn, _workspace_name)
                    _last_reindex_time = time.time()
                    _reindex_count += 1
                    # GC強制実行
                    gc.collect()
                    if torch.cuda.is_available():
                        torch.cuda.empty_cache()
                    rss_mb = os.popen("ps -o rss= -p %d" % os.getpid()).read().strip()
                    rss_mb = int(rss_mb) // 1024 if rss_mb else 0
                    print(f"[auto-reindex] Done. {len(_embedding_ids)} embeddings cached. (count={_reindex_count}, RSS={rss_mb}MB)", file=sys.stderr, flush=True)
                except Exception as e:
                    print(f"[auto-reindex] Error: {e}", file=sys.stderr, flush=True)

        reindex_thread = threading.Thread(target=auto_reindex, daemon=True)
        reindex_thread.start()

    # サーバー起動
    server = HTTPServer(("127.0.0.1", DEFAULT_PORT), WorkspaceRAGHandler)
    print(f"Workspace RAG Server running on http://127.0.0.1:{DEFAULT_PORT}", file=sys.stderr, flush=True)
    print(f"  Workspace: {_workspace} ({_workspace_name})", file=sys.stderr, flush=True)
    print(f"  Chunks: {len(_embedding_ids)}", file=sys.stderr, flush=True)
    if _auto_reindex_enabled:
        print(f"  Auto-reindex: every {args.reindex_interval}s (disable with --no-auto-reindex)", file=sys.stderr, flush=True)
    else:
        print(f"  Auto-reindex: disabled", file=sys.stderr, flush=True)
    print(f"  Endpoints:", file=sys.stderr, flush=True)
    print(f"    GET  /search?q=...&k=5&s=0.3", file=sys.stderr, flush=True)
    print(f"    GET  /health", file=sys.stderr, flush=True)
    print(f"    POST /reindex", file=sys.stderr, flush=True)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        shutdown(None, None)


if __name__ == "__main__":
    main()
