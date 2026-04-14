---
name: xs:workspace-rag
description: ワークスペース全体をベクトル検索するスキル。SQLite + multilingual-e5 で軽量実装。差分インデックスで高速更新、R²AG簡易版で関連度スコア付き検索結果を提示。「ワークスペース検索して」「RAGで探して」「〇〇について書いたファイルを見つけて」で使用。
---

# Workspace RAG

ワークスペース内のドキュメントをベクトル検索するスキル。

## 特徴

- **軽量**: SQLite + numpy（PostgreSQL不要、単一ファイルDB）
- **マルチフォーマット**: md, txt, py, js, json, yaml, csv 等
- **差分インデックス**: ファイルハッシュで変更検出、未変更ファイルはスキップ
- **R²AG簡易版**: 検索結果に関連度スコアを付与し、LLMが重要度を判断しやすくする
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

AIツールのセッションでは、長時間処理でタイムアウトする可能性がある。
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

常駐HTTPサーバーが起動中なら、curlで高速検索できる（~100ms）。

```bash
# 基本検索（ハイブリッド: ベクトル+FTS5）
curl -s "http://127.0.0.1:7891/search?q=検索クエリ"

# ベクトル検索のみ（意味的に近い文書を検索）
curl -s "http://127.0.0.1:7891/search?q=検索クエリ&mode=vector"

# キーワード検索のみ（FTS5 trigram、英語/コードに強い）
curl -s "http://127.0.0.1:7891/search?q=Python%20import&mode=keyword"

# R²AGフォーマット付き
curl -s "http://127.0.0.1:7891/search?q=検索クエリ&r2ag=1"

# 結果数・最低スコア指定
curl -s "http://127.0.0.1:7891/search?q=検索クエリ&k=10&s=0.5"

# ヘルスチェック
curl -s "http://127.0.0.1:7891/health"

# インデックス更新
curl -s -X POST "http://127.0.0.1:7891/reindex"
```

**検索モード:**
- **hybrid**（デフォルト）: ベクトル(0.7) + FTS5(0.3) の統合スコア。汎用
- **vector**: ベクトル検索のみ。日本語の意味検索に最適
- **keyword**: FTS5 trigramのみ。英語キーワード・コード検索に最適（超高速 ~10ms）

**注意:** memory-RAG（port 7890）とは別のサービス。workspace-ragはワークスペース全体を対象とし、memory-RAGはmemory/とnotes/のみを対象とする。

### Step 3b: 検索（CLI — サーバーが動いていない場合）

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
文書1 [関連度: 0.92 (高)]: ...  <- 「これは重要」
文書2 [関連度: 0.45 (低)]: ...  <- 「これは参考程度」
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
pm2 start "cd skills/workspace-rag/scripts && uv run python workspace_rag_server.py -w $(pwd) -p 7891" --name workspace-rag

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

**ポート:** 7891
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
- **スコア計算:** base_score * path_weight * freshness_score

## エラー対処

**「Index not found」エラー:**
-> `index` コマンドを先に実行する

**OOM（メモリ不足）でインデックスが途中で停止:**
-> バッチ処理+DB再接続でOOMを回避する設計だが、それでも落ちる場合は対象ディレクトリを絞って段階的にインデックスする

**検索結果が的外れ:**
-> クエリを具体的にする、`-s` で最低スコア閾値を上げる（0.5〜0.7）

## 使用例

```
「AIエージェントについて書いたファイルを探して」
「○○に関するメモを検索して」
「去年の○○の資料を見つけて」
「RAGで○○を調べて」
```

## 参考

- [R²AG論文 (EMNLP 2024)](https://arxiv.org/abs/2406.13249)
