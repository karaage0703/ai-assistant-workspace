# Workspace RAG

ワークスペース全体をベクトル検索＋構造化ファクト管理する軽量パーソナルRAG。port 7890 で常駐し、ベクトル/FTS5 ハイブリッド検索とファクト CRUD・忘却曲線を 1 サーバーで提供する。

詳細な解説記事: [Skillsで実現する軽量パーソナルRAG](https://zenn.dev/karaage0703/articles/d7eaf62437185d)

## 特徴

- **SQLite + numpy** — PostgreSQL不要、ファイル1つでDB管理
- **multilingual-e5-small** — 384次元、日英対応の埋め込みモデル（約500MB）
- **差分インデックス** — ファイルハッシュで変更検出、未変更ファイルはスキップ
- **ハイブリッド検索** — ベクトル検索(0.7) + FTS5 trigram キーワード検索(0.3、日本語固有名詞OK)
- **R²AG簡易版** — 検索結果に関連度スコアを付与（EMNLP 2024論文のアイデアを簡易実装）
- **構造化ファクト** — `/facts` 系 API で ADD/UPDATE/DELETE。`/search` にも相乗りで返る
- **忘却曲線オプション** — `?forgetting=on` のときだけ MemoryBank 式 decay を適用（**デフォルト OFF**）。NO_DECAY 系（`AGENTS.md/CLAUDE.md/MEMORY.md` と `knowledge/`）以外の全フォルダが対象
- **常駐HTTPサーバー** — 起動後は約70msで検索（CLI版は毎回モデルロードで約9秒）
- **自動reindex** — サーバーが30分ごとに差分インデックス＋キャッシュ更新（デフォルトON）

## クイックスタート

```bash
cd skills/xs-workspace-rag/scripts
uv sync

# インデックス作成（初回）
uv run python workspace_rag.py index -w /path/to/workspace

# CLI検索
uv run python workspace_rag.py search -w /path/to/workspace -q "検索クエリ"

# 常駐サーバー起動（推奨。pm2 か systemd user service が標準）
uv run python workspace_rag_server.py -w /path/to/workspace -p 7890
```

## サーバーAPI

### GET /search

```bash
# ハイブリッド検索（デフォルト）
curl -s -G "http://127.0.0.1:7890/search" --data-urlencode "q=検索クエリ"

# ベクトル検索のみ（日本語の意味検索に最適）
curl -s -G "http://127.0.0.1:7890/search" --data-urlencode "q=検索クエリ" --data-urlencode "mode=vector"

# キーワード検索のみ（trigram FTS5、日本語固有名詞・英語/コードに強い）
curl -s -G "http://127.0.0.1:7890/search" --data-urlencode "q=固有名詞" --data-urlencode "mode=keyword"

# R²AGフォーマット付き（LLMへの入力に最適）
curl -s -G "http://127.0.0.1:7890/search" --data-urlencode "q=検索クエリ" --data-urlencode "r2ag=1"

# 忘却曲線あり（最近のものを上位に出したい時のみ）
curl -s -G "http://127.0.0.1:7890/search" --data-urlencode "q=検索クエリ" --data-urlencode "forgetting=on"

# パラメータ
# k=5           結果数（デフォルト5）
# s=0.3         最低スコア（デフォルト0.3）
# mode=hybrid   hybrid/vector/keyword
# forgetting=on デフォルト OFF。ON のとき NO_DECAY 以外に MemoryBank 式 decay を適用
```

**重要:** 日本語クエリは URL エンコードが必須。`curl -G --data-urlencode` を使う（直書きは Bad request 400 になる）。

レスポンスには `results`（チャンク）と `facts`（相乗りファクト）の両方が返る。

### GET /facts 系（構造化ファクト管理）

```bash
# 一覧
curl -s "http://127.0.0.1:7890/facts"

# 類似検索（ADD/UPDATE 判断材料）
curl -s -G "http://127.0.0.1:7890/facts/similar" \
  --data-urlencode "q=ファクトの要点" --data-urlencode "k=3"

# ADD（新規追加）
curl -s -X POST "http://127.0.0.1:7890/facts" \
  -H "Content-Type: application/json" \
  -d '{"facts":[{"text":"好きな言語はPython"}]}'

# UPDATE（既存ID上書き、同じ事実の最新化のみ）
curl -s -X PUT "http://127.0.0.1:7890/facts/<ID>" \
  -H "Content-Type: application/json" \
  -d '{"text":"新しい内容"}'

# DELETE
curl -s -X DELETE "http://127.0.0.1:7890/facts/<ID>"
```

判断は呼び出し側がやる方針（自動 UPDATE は廃止）。`/facts/similar` で既存と被ってないか確認 → ADD/UPDATE/DELETE/何もしない を選ぶ。

### GET /health

```bash
curl -s "http://127.0.0.1:7890/health"
```

レスポンス例:
```json
{
  "status": "ok",
  "workspace": "/home/user/ai-assistant-workspace",
  "workspace_name": "ai-assistant-workspace",
  "chunks_cached": 1234,
  "files_indexed": 87,
  "facts": 12,
  "facts_cached": 12,
  "db_size_mb": 15.3,
  "port": 7890,
  "auto_reindex": true,
  "reindex_count": 5,
  "last_reindex": "2026-05-17T07:30:00+00:00"
}
```

### POST /reindex

手動でインデックス更新＋キャッシュ再読み込み。

```bash
curl -s -X POST "http://127.0.0.1:7890/reindex"
```

## サーバーオプション

```bash
uv run python workspace_rag_server.py -w /path/to/workspace -p 7890 [OPTIONS]

# 自動reindexを無効化
--no-auto-reindex

# reindex間隔を変更（デフォルト: 1800秒 = 30分）
--reindex-interval 3600
```

ポートは環境変数 `WORKSPACE_RAG_PORT` でも変更できる（`start_server.sh` 経由）。

## 忘却曲線（`?forgetting=on`）

`MemoryBank` 式の時間減衰を `final = combined * path_weight * freshness * decay` に乗算。

- `decay = 2^(-t/S)`
- `S = 30 * (1 + access_count * 0.5)` 日（半減期30日、参照1回で50%延長）
- `t` = 最後にアクセスされてからの経過日数（無アクセスならファイル日付から）

**NO_DECAY（forgetting=on でも 1.0 維持）:**
- `AGENTS.md / CLAUDE.md / MEMORY.md`
- `knowledge/` 配下（編纂済み知識）

**それ以外**（memory / notes / information-hub / logs / skills 等）は全て減衰対象。

**いつ ON にする？**
- 「最近の日記やメモを上に出したい」
- 「最近参照したチャンクを優先的に出したい」（参照すると access_count +1 で強化）

**いつ OFF（デフォルト）のままにする？**
- 固有名詞検索（人名・店名・地名）→ 過去ログ全部から拾いたい
- アーカイブ探索（過去 Twitter ログや過去ブログ等）

## アーキテクチャ

```
ワークスペース内のファイル（.md, .py, .ts, .json, etc.）
  ↓ index（差分検出 + チャンク分割 + 埋め込み生成）
SQLite DB（チャンク + 埋め込みベクトル + FTS5 trigram + facts テーブル）
  ↓ search（クエリ埋め込み → コサイン類似度 + FTS5スコア + path_weight。forgetting=on のときだけ freshness × decay）
検索結果（関連度スコア付き）+ ファクト相乗り
```

**常駐サーバー版の動作:**
```
サーバープロセス（常駐、pm2 / systemd user service）
  ├── メインスレッド: HTTPリクエスト受付
  │   ├── /search   → メモリ上の埋め込み行列でコサイン類似度計算（約70ms）
  │   ├── /facts*   → ファクト CRUD + 類似検索
  │   ├── /health   → ステータス + インデックス統計
  │   └── /reindex  → 差分インデックス + キャッシュ再読み込み
  └── 自動reindexスレッド（daemon）: 30分ごとに差分インデックス + キャッシュ更新
```

## 技術仕様

| 項目 | 値 |
|------|-----|
| 埋め込みモデル | intfloat/multilingual-e5-small（384次元） |
| チャンクサイズ | 512文字（オーバーラップ64文字） |
| 差分検出 | SHA-256ファイルハッシュ |
| DB | SQLite（単一ファイル、`.workspace_rag/` に保存） |
| FTS5 | trigram tokenizer（日本語の固有名詞・漢字熟語対応） |
| 検索速度 | 約70ms（サーバー版）/ 約9秒（CLI版） |
| メモリ使用量 | 約900MB（モデル400MB + 埋め込みキャッシュ + ファクトキャッシュ） |
| 忘却曲線 | MemoryBank 式（半減期30日、access_count で延長）。`?forgetting=on` のみ |

## 対応ファイル形式

`.md`, `.txt`, `.py`, `.js`, `.ts`, `.json`, `.yaml`, `.toml`, `.csv` 等

## 除外対象

`.git/`, `node_modules/`, `__pycache__/`, `.venv/`, 画像・バイナリ等

## 参考

- [Skillsで実現する軽量パーソナルRAG](https://zenn.dev/karaage0703/articles/d7eaf62437185d)
- [R²AG論文 (EMNLP 2024)](https://arxiv.org/abs/2406.13249)
- [MemoryBank: Enhancing Large Language Models with Long-Term Memory](https://arxiv.org/abs/2305.10250)
