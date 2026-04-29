# RAG trigger

ワークスペース内のすべてのファイル（`memory/`, `notes/`, `skills/`, ドキュメント等）をベクトル検索する `rag` トリガー。

`skills/workspace-rag/` の常駐サーバー（HTTP API）に問い合わせる薄いラッパー。LLMが Function Calling で呼び出すか、シェルから直接 `bash triggers/rag/handler.sh ...` で叩く。

## サブコマンド

`handler.sh` は第1引数でサブコマンドを切り替える。

| 引数 | 動作 |
|---|---|
| `(なし)` または `help` | 使い方を表示 |
| `start` | RAGサーバーを起動（起動済みならスキップ） |
| `index` | インデックス作成をバックグラウンド実行 |
| `<検索クエリ>` | 検索する（サーバー起動済みが前提） |

LLMから呼ぶ場合は `description` を見て自動的に適切な引数を組み立てる。例えば「過去のメモから AI エージェントの話を探して」と言われると、LLM は `rag("AIエージェント")` のように呼ぶ。

## 初回セットアップ

1. **依存パッケージのインストール** — `uv` が必要。

   ```bash
   cd skills/workspace-rag/scripts
   uv sync
   ```

2. **インデックス作成** — 初回はファイル数とサイズに応じて数十分〜数時間。

   ```bash
   bash triggers/rag/handler.sh index
   ```

   バックグラウンドで動くので、進捗は `tail -f .workspace_rag/index.log` で確認。

3. **サーバー起動**

   ```bash
   bash triggers/rag/handler.sh start
   ```

   起動後 `http://127.0.0.1:7891/health` が応答すれば準備完了。

セットアップが済めば、以降はLLMが必要なときに自動で呼んでくれる。

## 使用例

LLM経由（チャット）：

```
ユーザー: 過去にAIエージェントの設計について書いたメモあったっけ？
LLM: （内部で rag("AIエージェント 設計") を呼ぶ）
LLM: notes/20260301_ai_agents.md と memory/20260315.md にあったよ。前者では...
```

シェルから直叩き（デバッグ・確認用）：

```bash
$ bash triggers/rag/handler.sh "AIエージェントの最新動向"
検索結果: 5件 (72ms)

- **notes/20260301_ai_agents.md** (score: 0.91)
  AIエージェントの設計で重要なのは...
- **memory/20260315.md** (score: 0.88)
  今日のミーティングでエージェントの話が...
```

## 環境変数

| 変数 | デフォルト | 説明 |
|---|---|---|
| `WORKSPACE_PATH` | スクリプト位置から推定 | ワークスペースルート（`workspace-rag` のインデックス対象） |
| `WORKSPACE_RAG_PORT` | `7891` | RAGサーバーのポート |

xangi 経由で使う場合は xangi の `.env` に書いておく。

## 自動更新

`workspace-rag` サーバーはデフォルトで30分ごとに差分インデックス＋キャッシュ再読み込みを行う。新しく書いたメモも数十分以内には検索ヒット対象になる。

すぐ反映したい場合：

```bash
curl -s -X POST "http://127.0.0.1:7891/reindex"
```

## 検索のコツ

- **日本語OK** — multilingual-e5-small モデルなので日英どちらも検索できる
- **意味が近ければヒットする** — 「ラーメン」で「中華そば」もヒットする（ベクトル検索の長所）
- **スコア0.7以上が「関連あり」目安** — 0.5未満は関連薄い。0.3以下は除外推奨
- **キーワードが明確なら** — `mode=keyword` でFTS5検索の方が速い（〜10ms）。handler に `&mode=keyword` を渡す改造をすればOK

## 関連スキル

- [`skills/workspace-rag/`](../../skills/workspace-rag/) — このトリガーの本体。CLI操作やAPI仕様の詳細はこちら

## トラブルシューティング

### LLMが「サーバーが起動していません」と返してきた

→ `bash triggers/rag/handler.sh start` で起動。それでもダメなら `tail -50 .workspace_rag/server.log` を確認。`uv sync` が済んでないケースが多い。

### インデックス作成が一向に終わらない

初回は遅い。`tail -f .workspace_rag/index.log` で進捗を確認。途中で停止しても再実行で続きから再開する（差分インデックス）。

### 検索結果が出てこない

- インデックスが空 → `bash triggers/rag/handler.sh index` を実行
- ファイルが除外パターンにマッチ → `skills/workspace-rag/scripts/workspace_rag.py` の `DEFAULT_EXCLUDE_PATTERNS` を確認
- ファイルサイズが上限超 → デフォルト100KB上限。`--max-file-size 0` で無制限化可能

### ポート競合

`WORKSPACE_RAG_PORT` を別ポートに変えて再起動。
