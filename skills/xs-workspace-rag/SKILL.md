---
name: xs-workspace-rag
description: ワークスペース全体をベクトル検索＋構造化ファクト管理する常駐サーバー（port 7890、約70ms）。会話で過去の記憶を参照する必要がある時、ファクトを ADD/UPDATE/DELETE する時、両方ともこのスキルを使う。「前に話した」「あの時の」「ワークスペース検索して」「RAGで探して」「ファクト登録」で使用。
---

# Workspace RAG

ワークスペース内のドキュメントをベクトル検索＋構造化ファクト管理するスキル。port 7890 で常駐、検索とファクト CRUD が 1 サーバーに集約されている。

## 特徴

- **軽量**: SQLite + numpy（PostgreSQL不要、単一ファイルDB）
- **マルチフォーマット**: md, txt, py, js, json, yaml, csv 等
- **差分インデックス**: ファイルハッシュで変更検出、未変更ファイルはスキップ
- **R²AG簡易版**: 検索結果に関連度スコアを付与し、LLMが重要度を判断しやすくする
- **構造化ファクト**: `/facts` 系 API で ADD/UPDATE/DELETE。`/search` にも相乗りで返る
- **忘却曲線オプション**: `?forgetting=on` のときだけ MemoryBank 式 decay を適用（**デフォルト OFF**）。NO_DECAY 系（`AGENTS.md/CLAUDE.md/MEMORY.md`）以外は全フォルダ対象。新しい記事を上に出したい時のみ ON
- **trigram FTS5**: 日本語の固有名詞検索に強い（漢字熟語も拾う）
- **OOM対策**: バッチ処理・定期的なDB再接続でメモリ使用量を抑制

## スキル構成

```
[SKILL_DIR]/
├── SKILL.md
└── scripts/
    ├── workspace_rag.py          # CLI（インデックス・検索）
    ├── workspace_rag_server.py   # 常駐HTTPサーバー
    ├── start_server.sh           # サーバー起動スクリプト
    └── pyproject.toml
```

## 実行フロー

### Step 1: セットアップ（初回のみ）

```bash
cd [SKILL_DIR]/scripts
uv sync
```

### Step 2: インデックス作成

```bash
cd [SKILL_DIR]/scripts

# 初回インデックス（全ファイル処理）
uv run python workspace_rag.py index -w [WORKSPACE]

# 差分インデックス（変更ファイルのみ更新。同じコマンドを再実行するだけ）
uv run python workspace_rag.py index -w [WORKSPACE]

# 強制再インデックス（全ファイル再処理）
uv run python workspace_rag.py index -w [WORKSPACE] -f

# ファイルサイズ上限を変更（デフォルト100KB、0=無制限）
uv run python workspace_rag.py index -w [WORKSPACE] --max-file-size 200000
```

**所要時間の目安:**
- 初回: ファイル数・サイズにより数十分〜数時間
- 差分更新: 変更ファイル数に応じて数秒〜数分

### バックグラウンド実行（長時間インデックス用）

AIツール（Claude Code / Codex CLI）のセッションでは、長時間処理でタイムアウトする可能性がある。
その場合は **nohup + バックグラウンド実行** を使う。

```bash
cd [SKILL_DIR]/scripts

# バックグラウンドでインデックス作成（ログはファイルに出力）
nohup uv run python workspace_rag.py index -w [WORKSPACE] > /tmp/rag_index.log 2>&1 &

# プロセスIDを確認
echo $!

# 進捗確認
tail -f /tmp/rag_index.log

# 完了確認（プロセスが終了したか）
ps aux | grep workspace_rag
```

**ポイント:**
- `nohup ... &` でセッションが切れても処理が継続
- ログは `/tmp/rag_index.log` で進捗確認可能
- 完了後に `tail /tmp/rag_index.log` で結果を確認

### Step 3: 検索（常駐サーバー経由 — 推奨）

常駐HTTPサーバーが起動中なら、curlで高速検索できる（約100ms）。

**重要: 日本語クエリは URL エンコードが必要。** `curl -G --data-urlencode` を使うこと（直書きは Bad request 400 になる）。

```bash
# 基本検索（ハイブリッド: ベクトル+FTS5）
curl -s -G "http://127.0.0.1:7890/search" --data-urlencode "q=検索クエリ"

# ベクトル検索のみ（意味的に近い文書を検索）
curl -s -G "http://127.0.0.1:7890/search" --data-urlencode "q=検索クエリ" --data-urlencode "mode=vector"

# キーワード検索のみ（FTS5 trigram、英語/コードに強い）
curl -s -G "http://127.0.0.1:7890/search" --data-urlencode "q=Python import" --data-urlencode "mode=keyword"

# R²AGフォーマット付き
curl -s -G "http://127.0.0.1:7890/search" --data-urlencode "q=検索クエリ" --data-urlencode "r2ag=1"

# 結果数・最低スコア指定
curl -s -G "http://127.0.0.1:7890/search" --data-urlencode "q=検索クエリ" --data-urlencode "k=10" --data-urlencode "s=0.5"

# ヘルスチェック
curl -s "http://127.0.0.1:7890/health"

# インデックス更新
curl -s -X POST "http://127.0.0.1:7890/reindex"
```

**検索モード:**
- **hybrid**（デフォルト）: ベクトル(0.7) + FTS5(0.3) の統合スコア。汎用
- **vector**: ベクトル検索のみ。日本語の意味検索に最適
- **keyword**: FTS5 trigramのみ。英語キーワード・コード検索に最適（超高速、約10ms）

**忘却曲線オプション (`?forgetting=on`)** — デフォルト OFF：
```bash
# 全フォルダのチャンクに MemoryBank 式 decay を適用
# （新しい記事/参照されてる記事を上に出したい時のみ使用）
curl -s -G "http://127.0.0.1:7890/search" --data-urlencode "q=検索クエリ" --data-urlencode "forgetting=on"
```
- **デフォルト OFF**: 全期間の検索結果を平等に出す（古いファイルも沈まない）
- **ON のとき**: `final = combined * path_weight * freshness * decay`、 `decay = 2^(-t/S), S = 30*(1+access_count*0.5)`（30日半減期、参照で延長）
- **ON でも例外**: `AGENTS.md/CLAUDE.md/MEMORY.md` は decay=1.0（常に参照されてほしいルール系）
- ON のときだけ、上位結果の `access_count` が更新されて忘れにくくなる

### Step 3c: ファクト管理（GET/POST/PUT/DELETE /facts）

構造化された事実を ID 付きで保存・更新・削除する API。**毎回「検索 → 判断 → 操作」の3ステップ**で進めること（自動 UPDATE は廃止）。

```bash
# (1) 検索: 既存ファクトに似たものがあるか
curl -s -G "http://127.0.0.1:7890/facts/similar" \
  --data-urlencode "q=ファクトの要点" --data-urlencode "k=3"

# (2-A) ADD: 新規追加（POST /facts）
curl -s -X POST "http://127.0.0.1:7890/facts" \
  -H "Content-Type: application/json" \
  -d '{"facts": [{"text": "好きな言語はPython"}]}'

# (2-B) UPDATE: 既存IDを上書き（同じ事実の最新化のみ）
curl -s -X PUT "http://127.0.0.1:7890/facts/<ID>" \
  -H "Content-Type: application/json" \
  -d '{"text": "新しい内容"}'

# (2-C) DELETE: 期限切れ・無関係になったファクトの削除
curl -s -X DELETE "http://127.0.0.1:7890/facts/<ID>"

# 一覧
curl -s "http://127.0.0.1:7890/facts"
```

判断基準:
- **ADD**: 似たファクトなし or トピックが別 → 新規
- **UPDATE**: 同じ事実の最新化（体重・売上数・進行中タスクの更新）→ 既存IDを上書き
- **DELETE**: 期限切れ・無関係 → 削除
- **何もしない**: 既存と内容が同等 → スキップ

**重要**: 別トピックを既存IDに UPDATE しない（`old_values` 履歴が混乱する）。違うトピックは ADD。

`/search` のレスポンスにもファクトが相乗りで返る（フィールド `facts`）ので、検索だけでファクトも引ける。

### Step 3d: 検索（CLI — サーバーが動いていない場合）

```bash
cd [SKILL_DIR]/scripts

# 基本検索
uv run python workspace_rag.py search -w [WORKSPACE] -q "検索クエリ"

# R²AGフォーマット出力（関連度ラベル付き、LLMへの入力に最適）
uv run python workspace_rag.py search -w [WORKSPACE] -q "検索クエリ" --r2ag

# 結果数を指定（デフォルト5件）
uv run python workspace_rag.py search -w [WORKSPACE] -q "検索クエリ" -k 10

# 最低スコア閾値を指定（デフォルト0.3）
uv run python workspace_rag.py search -w [WORKSPACE] -q "検索クエリ" -s 0.5

# JSON出力
uv run python workspace_rag.py search -w [WORKSPACE] -q "検索クエリ" --json
```

### Step 4: 結果を報告・活用

**必ずユーザーに以下を報告する：**
1. 「ワークスペースRAGで検索しました」と**RAGを使ったことを明示**
2. ヒット件数
3. 各結果の**ファイルパス**と**関連度スコア**を表示

**報告フォーマット例：**
```
ワークスペースRAGで「検索クエリ」を検索（10件ヒット）

| # | ファイル | 関連度 |
|---|---------|--------|
| 1 | notes/20250723_topic.md | 0.92 (高) |
| 2 | memory/20250722.md | 0.88 (高) |
| 3 | ... | 0.45 (低) |
```

その後、検索結果をもとに：
- 関連ファイルを直接読んで回答に活用
- 関連度スコアが高い文書を優先的に参照
- スコアが低い結果（0.85未満）はノイズの可能性を考慮

## R²AG簡易版について

論文「R²AG: Incorporating Retrieval Information into RAG」（EMNLP 2024）のアイデアを簡易実装。

**通常のRAG:**
```
文書1: ...
文書2: ...
質問に答えて
```

**R²AG簡易版（関連度スコア付き）:**
```
文書1 [関連度: 0.92 (高)]: ...  ← 「これは重要」
文書2 [関連度: 0.45 (低)]: ...  ← 「これは参考程度」
質問に答えて
```

関連度スコアをプロンプトに含めることで、LLMが文書の重要度を判断しやすくなる。

## 常駐サーバー管理

### サーバー起動（手動）

```bash
bash [SKILL_DIR]/scripts/start_server.sh
```

### pm2（自動起動・Linux/Mac両対応）

```bash
# ワークスペースルートに移動してから実行
cd [WORKSPACE]

# 起動
pm2 start "cd skills/xs-workspace-rag/scripts && uv run python workspace_rag_server.py -w $(pwd) -p 7890" --name workspace-rag

# 状態確認
pm2 status workspace-rag

# ログ確認
pm2 logs workspace-rag

# 再起動
pm2 restart workspace-rag

# OS再起動時の自動復帰
pm2 save
pm2 startup
```

**ポート:** 7890（`WORKSPACE_RAG_PORT` 環境変数で変更可）
**メモリ使用量:** 約800MB（モデル400MB + 埋め込みキャッシュ300MB + オーバヘッド100MB）

## カスタマイズ

### パス重み付け

`scripts/workspace_rag.py` の `PATH_WEIGHTS` でディレクトリごとの検索スコア重みを設定できる。重要なディレクトリのスコアを上げることで、検索結果の精度が向上する。

### 除外パターン・対象拡張子

`scripts/workspace_rag.py` の `DEFAULT_EXCLUDE_PATTERNS` / `DEFAULT_INCLUDE_EXTENSIONS` を直接編集する。

### ファイルサイズ上限

デフォルトは100KB。`--max-file-size` オプションまたは `DEFAULT_MAX_FILE_SIZE` 定数で変更可能。

## 技術仕様

- **埋め込みモデル:** `intfloat/multilingual-e5-small`（384次元）
- **チャンクサイズ:** 512文字（オーバーラップ64文字）
- **差分検出:** SHA-256ファイルハッシュ
- **データ保存先:** `[WORKSPACE]/.workspace_rag/index_<hash>.db`
- **対応形式:** `.md`, `.txt`, `.py`, `.js`, `.ts`, `.json`, `.yaml`, `.toml`, `.csv` 等
- **除外対象:** `.git/`, `node_modules/`, `__pycache__/`, `.venv/`, 画像・バイナリ等
- **スコア計算:** `base_score * path_weight * freshness_score`（forgetting=on 時はさらに decay）

## エラー対処

**「Index not found」エラー:**
→ `index` コマンドを先に実行する

**OOM（メモリ不足）でインデックスが途中で停止:**
→ バッチ処理+DB再接続でOOMを回避する設計だが、それでも落ちる場合は対象ディレクトリを絞って段階的にインデックスする

**検索結果が的外れ:**
→ クエリを具体的にする、`-s` で最低スコア閾値を上げる（0.5〜0.7）

**日本語クエリで `Bad request 400`:**
→ URL 直書きは NG。`curl -G --data-urlencode "q=..."` を使う

## 使用例

```
「AIエージェントについて書いたファイルを探して」
「コンテキストエンジニアリングに関するメモを検索して」
「去年のイベント登壇資料を見つけて」
「RAGで○○を調べて」
```

## ファクト管理のトリガー

以下のときに「検索 → 判断 → ADD/UPDATE/DELETE」を実行：

- ユーザーが「覚えておいて」「メモして」と言った
- 好み・習慣・計画・健康・家族など記憶に値する事実が出た
- 既存ファクトが変わった（体重更新・進行中タスクの状態更新など）

別トピックを既存 ID に UPDATE で上書き禁止（同じ事実の最新化のみ UPDATE、別トピックは ADD）。

## 参考

- [R²AG論文 (EMNLP 2024)](https://arxiv.org/abs/2406.13249)
