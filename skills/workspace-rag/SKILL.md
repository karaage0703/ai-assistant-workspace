---
name: workspace-rag
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
skills/workspace-rag/
├── SKILL.md
├── workspace_rag.py    # メインスクリプト
├── pyproject.toml
└── uv.lock
```

## 実行フロー

### Step 1: セットアップ（初回のみ）

```bash
cd skills/workspace-rag
uv sync
```

### Step 2: インデックス作成

```bash
cd skills/workspace-rag

# 初回インデックス（全ファイル処理）
uv run python workspace_rag.py index -w ../..

# 差分インデックス（変更ファイルのみ更新。同じコマンドを再実行するだけ）
uv run python workspace_rag.py index -w ../..

# 強制再インデックス（全ファイル再処理）
uv run python workspace_rag.py index -w ../.. -f
```

**所要時間の目安:**
- 初回: ファイル数・サイズにより数十分〜数時間
- 差分更新: 変更ファイル数に応じて数秒〜数分

### バックグラウンド実行（長時間インデックス用）

AIツールのセッションでは、長時間処理でタイムアウトする可能性がある。
その場合は **nohup + バックグラウンド実行** を使う。

```bash
cd skills/workspace-rag

# バックグラウンドでインデックス作成（ログはファイルに出力）
nohup uv run python workspace_rag.py index -w ../.. > /tmp/rag_index.log 2>&1 &

# プロセスIDを確認
echo $!

# 進捗確認
tail -f /tmp/rag_index.log

# 完了確認（プロセスが終了したか）
ps aux | grep workspace_rag
```

### Step 3: 検索

```bash
cd skills/workspace-rag

# 基本検索
uv run python workspace_rag.py search -w ../.. -q "検索クエリ"

# R²AGフォーマット出力（関連度ラベル付き、LLMへの入力に最適）
uv run python workspace_rag.py search -w ../.. -q "検索クエリ" --r2ag

# 結果数を指定（デフォルト5件）
uv run python workspace_rag.py search -w ../.. -q "検索クエリ" -k 10

# 最低スコア閾値を指定（デフォルト0.3）
uv run python workspace_rag.py search -w ../.. -q "検索クエリ" -s 0.5

# JSON出力
uv run python workspace_rag.py search -w ../.. -q "検索クエリ" --json
```

### Step 4: 結果を報告・活用

**必ずユーザーに以下を報告する：**
1. 「ワークスペースRAGで検索しました」と**RAGを使ったことを明示**
2. ヒット件数
3. 各結果の**ファイルパス**と**関連度スコア**を表示

その後、検索結果をもとに：
- 関連ファイルを直接読んで回答に活用
- 関連度スコアが高い文書を優先的に参照
- スコアが低い結果はノイズの可能性を考慮

## R²AG簡易版について

論文「R²AG: Incorporating Retrieval Information into RAG」（EMNLP 2024）のアイデアを簡易実装。

関連度スコアをプロンプトに含めることで、LLMが文書の重要度を判断しやすくなる。

## 技術仕様

- **埋め込みモデル:** `intfloat/multilingual-e5-small`（384次元）
- **チャンクサイズ:** 512文字（オーバーラップ64文字）
- **差分検出:** SHA-256ファイルハッシュ
- **対応形式:** `.md`, `.txt`, `.py`, `.js`, `.ts`, `.json`, `.yaml`, `.toml`, `.csv` 等
- **除外対象:** `.git/`, `node_modules/`, `__pycache__/`, `.venv/`, 画像・バイナリ等

## エラー対処

- **「Index not found」エラー** → `index` コマンドを先に実行する
- **OOM（メモリ不足）でインデックスが途中で停止** → 対象ディレクトリを絞って段階的にインデックスする
- **検索結果が的外れ** → クエリを具体的にする、`-s` で最低スコア閾値を上げる（0.5〜0.7）

## 使用例

```
「AIエージェントについて書いたファイルを探して」
「○○に関するメモを検索して」
「RAGで○○を調べて」
```

## 参考

- [R²AG論文 (EMNLP 2024)](https://arxiv.org/abs/2406.13249)
