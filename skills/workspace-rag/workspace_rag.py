#!/usr/bin/env python3
"""
Workspace RAG - ワークスペース全体をベクトル検索
SQLite + sentence-transformers のシンプル実装（PostgreSQL不要）
R²AG簡易版: 検索結果に関連度スコアを付与
"""

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
import gc
from pathlib import Path
from typing import Optional

import torch
import numpy as np
from sentence_transformers import SentenceTransformer

# 設定
DEFAULT_MODEL = "intfloat/multilingual-e5-small"
CHUNK_SIZE = 512
CHUNK_OVERLAP = 64
BATCH_SIZE = 16  # メモリ安定優先
COMMIT_INTERVAL = 50  # ファイル単位でのコミット間隔
PROGRESS_INTERVAL = 1000  # 進捗表示間隔（チャンク数）
RECONNECT_INTERVAL = 2000  # DB再接続間隔（チャンク数）- メモリリセット用

# 除外パターン
DEFAULT_EXCLUDE_PATTERNS = [
    r"\.git/",
    r"node_modules/",
    r"__pycache__/",
    r"\.venv/",
    r"venv/",
    r"\.pyc$",
    r"\.pyo$",
    r"\.so$",
    r"\.dylib$",
    r"\.dll$",
    r"\.exe$",
    r"\.bin$",
    r"\.o$",
    r"\.a$",
    r"\.lib$",
    r"\.png$",
    r"\.jpg$",
    r"\.jpeg$",
    r"\.gif$",
    r"\.webp$",
    r"\.svg$",
    r"\.ico$",
    r"\.mp3$",
    r"\.mp4$",
    r"\.wav$",
    r"\.avi$",
    r"\.mov$",
    r"\.pdf$",
    r"\.zip$",
    r"\.tar$",
    r"\.gz$",
    r"\.rar$",
    r"\.7z$",
    r"\.lock$",
    r"package-lock\.json$",
    r"yarn\.lock$",
    r"\.DS_Store$",
    r"Thumbs\.db$",
    r"\.workspace_rag/",
    r"\.openclaw/",
    r"\.clawdbot/",
    r"dist/",
    r"build/",
    r"\.next/",
]

# 対象拡張子
DEFAULT_INCLUDE_EXTENSIONS = {
    ".md", ".txt", ".py", ".js", ".ts", ".jsx", ".tsx",
    ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg",
    ".sh", ".bash", ".zsh", ".fish",
    ".html", ".css", ".scss", ".less",
    ".sql", ".graphql",
    ".rs", ".go", ".java", ".kt", ".scala",
    ".c", ".cpp", ".h", ".hpp",
    ".rb", ".php", ".pl", ".pm",
    ".r", ".R", ".jl",
    ".swift", ".m", ".mm",
    ".lua", ".vim", ".el",
    ".dockerfile", ".dockerignore",
    ".gitignore", ".gitattributes",
    ".env", ".env.example",
    ".csv",
}


def _get_rss_mb() -> float:
    """現在のRSS(MB)を取得"""
    try:
        with open('/proc/self/status') as f:
            for line in f:
                if line.startswith('VmRSS:'):
                    return int(line.split()[1]) / 1024
    except Exception:
        return 0.0


def get_db_path(workspace: str) -> Path:
    """DBファイルのパスを取得"""
    workspace_hash = hashlib.md5(workspace.encode()).hexdigest()[:8]
    return Path(workspace) / ".workspace_rag" / f"index_{workspace_hash}.db"


def init_db(db_path: Path) -> sqlite3.Connection:
    """データベース初期化"""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    # WALモードで書き込みパフォーマンス向上
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    # メモリ使用量を制限（2MB）- OOM対策
    conn.execute("PRAGMA cache_size = -2000")
    conn.execute("PRAGMA mmap_size = 0")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            workspace TEXT NOT NULL,
            file_path TEXT NOT NULL,
            chunk_index INTEGER NOT NULL,
            content TEXT NOT NULL,
            file_hash TEXT NOT NULL,
            embedding BLOB,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(workspace, file_path, chunk_index)
        )
    """)
    # 既存テーブルにembeddingカラムがなければ追加（インデックス作成前に実行）
    cursor = conn.execute("PRAGMA table_info(chunks)")
    columns = [row[1] for row in cursor.fetchall()]
    if "embedding" not in columns:
        conn.execute("ALTER TABLE chunks ADD COLUMN embedding BLOB")
        conn.commit()

    conn.execute("CREATE INDEX IF NOT EXISTS idx_workspace ON chunks(workspace)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_file_path ON chunks(workspace, file_path)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_has_embedding ON chunks(workspace, embedding IS NOT NULL)")
    conn.commit()

    return conn


def should_exclude(path: str, patterns: list[str]) -> bool:
    """除外すべきファイルか判定"""
    for pattern in patterns:
        if re.search(pattern, path):
            return True
    return False


def should_include(path: str, extensions: set[str]) -> bool:
    """対象ファイルか判定"""
    ext = Path(path).suffix.lower()
    if not ext:
        name = Path(path).name.lower()
        return name in {"readme", "makefile", "dockerfile", "license", "authors", "changelog", "contributing"}
    return ext in extensions


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """テキストをチャンクに分割"""
    if len(text) <= chunk_size:
        return [text] if text.strip() else []

    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]
        if chunk.strip():
            chunks.append(chunk)
        start = end - overlap

    return chunks


def get_file_hash(content: str) -> str:
    """ファイル内容のハッシュを取得"""
    return hashlib.sha256(content.encode()).hexdigest()[:16]


def collect_files(workspace: str, exclude_patterns: list[str] = None, include_extensions: set[str] = None):
    """対象ファイルを収集（ジェネレータ版 - メモリ節約）"""
    workspace_path = Path(workspace).resolve()
    if exclude_patterns is None:
        exclude_patterns = DEFAULT_EXCLUDE_PATTERNS
    if include_extensions is None:
        include_extensions = DEFAULT_INCLUDE_EXTENSIONS

    # まずパスだけ集めてソート（文字列で保持、Pathオブジェクトより軽量）
    paths = []

    for root, dirs, filenames in os.walk(workspace_path):
        dirs[:] = [d for d in dirs if not should_exclude(os.path.join(root, d) + "/", exclude_patterns)]

        for filename in filenames:
            filepath = os.path.join(root, filename)
            rel_path = os.path.relpath(filepath, workspace_path)

            if should_exclude(rel_path, exclude_patterns):
                continue
            if not should_include(rel_path, include_extensions):
                continue

            paths.append(filepath)

    paths.sort()
    for p in paths:
        yield Path(p)


def embed_and_store_batch(conn: sqlite3.Connection, model, chunk_ids: list[int], texts: list[str]) -> None:
    """バッチで埋め込みを生成し、即座にDBに保存"""
    if not chunk_ids:
        return
    batch_texts = [f"passage: {text}" for text in texts]
    # torch.no_grad() で計算グラフの蓄積を防止（OOM対策の核心）
    with torch.no_grad():
        embeddings = model.encode(batch_texts, normalize_embeddings=True, show_progress_bar=False)

    for cid, emb in zip(chunk_ids, embeddings):
        blob = emb.astype(np.float16).tobytes()
        conn.execute("UPDATE chunks SET embedding = ? WHERE id = ?", (blob, cid))
    # 明示的にembeddings解放 + PyTorchキャッシュクリア
    del embeddings, batch_texts
    gc.collect()


def index_workspace(workspace: str, force: bool = False) -> None:
    """ワークスペースをインデックス（メモリ効率版）"""
    workspace_path = Path(workspace).resolve()
    workspace_name = workspace_path.name

    print(f"Loading model: {DEFAULT_MODEL}", flush=True)
    model = SentenceTransformer(DEFAULT_MODEL)
    dim = model.get_sentence_embedding_dimension()
    print(f"Model dimension: {dim}", flush=True)

    db_path = get_db_path(str(workspace_path))
    conn = init_db(db_path)

    if force:
        print(f"  Clearing workspace: {workspace_name}", flush=True)
        conn.execute("DELETE FROM chunks WHERE workspace = ?", (workspace_name,))
        conn.commit()

    # ファイル収集（ジェネレータなので2パス: カウント用 + 処理用）
    file_count_total = sum(1 for _ in collect_files(str(workspace_path)))
    print(f"  Found {file_count_total} files to index", flush=True)

    # Phase 1: チャンクをDBに挿入（埋め込みなし）
    total_new_chunks = 0
    skipped_files = 0
    file_count = 0

    for file_path in collect_files(str(workspace_path)):
        rel_path = str(file_path.relative_to(workspace_path))
        file_count += 1

        try:
            content = file_path.read_text(encoding="utf-8", errors="ignore")
        except Exception as e:
            print(f"  Warning: Could not read {rel_path}: {e}", flush=True)
            continue

        if not content.strip():
            continue

        file_hash = get_file_hash(content)

        # 既存のハッシュをチェック
        cursor = conn.execute(
            "SELECT file_hash FROM chunks WHERE workspace = ? AND file_path = ? LIMIT 1",
            (workspace_name, rel_path)
        )
        row = cursor.fetchone()

        if row and row[0] == file_hash and not force:
            skipped_files += 1
            continue

        # 既存のチャンクを削除
        conn.execute(
            "DELETE FROM chunks WHERE workspace = ? AND file_path = ?",
            (workspace_name, rel_path)
        )

        chunks = chunk_text(content)

        for i, chunk in enumerate(chunks):
            conn.execute(
                """INSERT INTO chunks (workspace, file_path, chunk_index, content, file_hash)
                   VALUES (?, ?, ?, ?, ?)""",
                (workspace_name, rel_path, i, chunk, file_hash)
            )
            total_new_chunks += 1

        # 定期的にコミット
        if file_count % COMMIT_INTERVAL == 0:
            conn.commit()
            if file_count % 500 == 0:
                print(f"  Scanned {file_count}/{file_count_total} files ({total_new_chunks} new chunks)...", flush=True)
        # 明示的にcontentを解放
        del content

    conn.commit()
    print(f"  Scan complete: {total_new_chunks} new chunks from {file_count - skipped_files} files ({skipped_files} unchanged)", flush=True)

    # Phase 2: 埋め込みがないチャンクを取得してバッチ処理
    cursor = conn.execute(
        "SELECT COUNT(*) FROM chunks WHERE workspace = ? AND embedding IS NULL",
        (workspace_name,)
    )
    chunks_to_embed = cursor.fetchone()[0]

    if chunks_to_embed == 0:
        print("  All chunks already have embeddings. Nothing to do.", flush=True)
    else:
        print(f"  Generating embeddings for {chunks_to_embed} chunks (batch_size={BATCH_SIZE})...", flush=True)

        processed = 0
        while True:
            # バッチ分だけDBから取得（メモリに全部載せない）
            cursor = conn.execute(
                "SELECT id, content FROM chunks WHERE workspace = ? AND embedding IS NULL LIMIT ?",
                (workspace_name, BATCH_SIZE)
            )
            rows = cursor.fetchall()

            if not rows:
                break

            chunk_ids = [r[0] for r in rows]
            texts = [r[1] for r in rows]
            batch_len = len(rows)

            embed_and_store_batch(conn, model, chunk_ids, texts)
            conn.commit()
            del rows, chunk_ids, texts  # 明示的に解放

            processed += batch_len

            # 進捗表示 + GC
            if processed % PROGRESS_INTERVAL < BATCH_SIZE:
                print(f"    Processed {processed}/{chunks_to_embed} chunks (RSS: {_get_rss_mb():.0f}MB)", flush=True)
                gc.collect()

            # 定期的にDB再接続（SQLiteのページキャッシュをリセット）
            if processed % RECONNECT_INTERVAL < BATCH_SIZE:
                conn.close()
                conn = init_db(db_path)
                gc.collect()
                print(f"    [Memory reset] DB reconnected at {processed} chunks", flush=True)

        print(f"    Processed {processed}/{chunks_to_embed} chunks", flush=True)

    # 統計
    cursor = conn.execute(
        "SELECT COUNT(*) FROM chunks WHERE workspace = ?",
        (workspace_name,)
    )
    total_chunks = cursor.fetchone()[0]

    cursor = conn.execute(
        "SELECT COUNT(*) FROM chunks WHERE workspace = ? AND embedding IS NOT NULL",
        (workspace_name,)
    )
    total_with_embeddings = cursor.fetchone()[0]

    print(f"\n✅ Indexing complete!", flush=True)
    print(f"   Total chunks: {total_chunks}", flush=True)
    print(f"   With embeddings: {total_with_embeddings}", flush=True)
    print(f"   Database: {db_path}", flush=True)
    print(f"   DB size: {db_path.stat().st_size / 1024 / 1024:.1f} MB", flush=True)

    conn.close()
    gc.collect()


def search(workspace: str, query: str, top_k: int = 5, min_score: float = 0.3) -> list[dict]:
    """検索を実行（バッチ読み込みでメモリ効率化）"""
    workspace_path = Path(workspace).resolve()
    workspace_name = workspace_path.name

    db_path = get_db_path(str(workspace_path))

    if not db_path.exists():
        print("Error: Index not found. Run 'index' first.", file=sys.stderr)
        return []

    # モデルロード
    print(f"Loading model: {DEFAULT_MODEL}", flush=True)
    model = SentenceTransformer(DEFAULT_MODEL)
    dim = model.get_sentence_embedding_dimension()

    # クエリ埋め込み
    with torch.no_grad():
        query_emb = model.encode(f"query: {query}", normalize_embeddings=True).astype(np.float32)

    conn = sqlite3.connect(str(db_path))

    # チャンク数を確認
    cursor = conn.execute(
        "SELECT COUNT(*) FROM chunks WHERE workspace = ? AND embedding IS NOT NULL",
        (workspace_name,)
    )
    total = cursor.fetchone()[0]

    if total == 0:
        print("Error: No embeddings found. Run 'index' first.", file=sys.stderr)
        conn.close()
        return []

    print(f"Searching {total} chunks...", flush=True)

    # バッチで読み込んでスコア計算（全部メモリに載せない）
    SEARCH_BATCH = 1000
    top_results = []  # (score, chunk_id)

    offset = 0
    while offset < total:
        cursor = conn.execute(
            "SELECT id, embedding FROM chunks WHERE workspace = ? AND embedding IS NOT NULL LIMIT ? OFFSET ?",
            (workspace_name, SEARCH_BATCH, offset)
        )
        rows = cursor.fetchall()
        if not rows:
            break

        for row_id, emb_blob in rows:
            emb = np.frombuffer(emb_blob, dtype=np.float16).astype(np.float32)
            score = float(np.dot(emb, query_emb))

            if score >= min_score:
                top_results.append((score, row_id))

        offset += len(rows)

    # スコアでソートして上位k件
    top_results.sort(key=lambda x: x[0], reverse=True)
    top_results = top_results[:top_k]

    # 結果を取得
    results = []
    for score, chunk_id in top_results:
        cursor = conn.execute(
            "SELECT file_path, chunk_index, content FROM chunks WHERE id = ?",
            (chunk_id,)
        )
        row = cursor.fetchone()
        if row:
            file_path, chunk_index, content = row
            results.append({
                "file_path": file_path,
                "chunk_index": chunk_index,
                "content": content,
                "score": score,
            })

    conn.close()
    return results


def format_results_r2ag(results: list[dict]) -> str:
    """R²AG簡易版フォーマット（関連度ラベル付き）"""
    if not results:
        return "検索結果なし"

    output = "以下の文書を参考に質問に答えてください。\n"
    output += "関連度が高いほど信頼できます。\n\n"

    for i, r in enumerate(results, 1):
        score = r["score"]
        if score >= 0.7:
            label = "高"
        elif score >= 0.5:
            label = "中"
        else:
            label = "低"

        output += f"**文書{i}** [{r['file_path']}] [関連度: {score:.2f} ({label})]\n"
        output += f"{r['content'][:300]}...\n\n"

    return output


def main():
    parser = argparse.ArgumentParser(description="Workspace RAG (SQLite版, メモリ効率改善)")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # index コマンド
    index_parser = subparsers.add_parser("index", help="Index a workspace")
    index_parser.add_argument("-w", "--workspace", required=True, help="Workspace directory")
    index_parser.add_argument("-f", "--force", action="store_true", help="Force re-index")

    # search コマンド
    search_parser = subparsers.add_parser("search", help="Search the index")
    search_parser.add_argument("-w", "--workspace", required=True, help="Workspace directory")
    search_parser.add_argument("-q", "--query", required=True, help="Search query")
    search_parser.add_argument("-k", "--top-k", type=int, default=5, help="Number of results")
    search_parser.add_argument("-s", "--min-score", type=float, default=0.3, help="Minimum score threshold")
    search_parser.add_argument("--json", action="store_true", help="Output as JSON")
    search_parser.add_argument("--r2ag", action="store_true", help="R²AG format output (with relevance labels)")

    args = parser.parse_args()

    if args.command == "index":
        index_workspace(args.workspace, args.force)

    elif args.command == "search":
        results = search(args.workspace, args.query, args.top_k, args.min_score)

        if args.json:
            print(json.dumps(results, ensure_ascii=False, indent=2))
        elif args.r2ag:
            print(format_results_r2ag(results))
        else:
            if not results:
                print("No results found.")
            else:
                for i, r in enumerate(results, 1):
                    print(f"\n{'='*60}")
                    print(f"[{i}] {r['file_path']} (chunk {r['chunk_index']}) - Score: {r['score']:.3f}")
                    print(f"{'='*60}")
                    print(r['content'][:500] + ("..." if len(r['content']) > 500 else ""))


if __name__ == "__main__":
    main()
