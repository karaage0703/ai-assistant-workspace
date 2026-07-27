---
name: xs-workspace-rag
description: ワークスペース全体をベクトル検索＋構造化ファクト管理する任意スキル。ユーザーがRAGのセットアップ・検索・ファクト操作を明示的に依頼した場合に使う。「RAGをセットアップして」「RAGで探して」「ファクト登録」で使用。
---

# Workspace RAG

ワークスペース内のドキュメントをベクトル検索＋構造化ファクト管理するスキル。port 7890 で常駐、検索とファクト CRUD が 1 サーバーに集約されている。

## 特徴

- **軽量**: SQLite + Faiss（PostgreSQL不要。Faiss利用不可時はNumPyへ縮退）
- **マルチフォーマット**: md, txt, py, js, json, yaml, csv 等
- **差分インデックス**: ファイルハッシュで変更検出。追記型ログは変更末尾だけ再埋め込み
- **R²AG簡易版**: 検索結果に関連度スコアを付与し、LLMが重要度を判断しやすくする
- **構造化ファクト**: `/facts` 系 API で ADD/UPDATE/DELETE。`/search` にも相乗りで返る
- **忘却曲線オプション**: `?forgetting=on` のときだけ MemoryBank 式 decay を適用（**デフォルト OFF**）。NO_DECAY 系（`AGENTS.md/CLAUDE.md/MEMORY.md`）以外は全フォルダ対象。新しい記事を上に出したい時のみ ON
- **trigram FTS5**: 日本語の固有名詞検索に強い（漢字熟語も拾う）
- **OOM対策**: バッチ処理・定期的なDB再接続でメモリ使用量を抑制
- **並行検索**: reindex中も既存キャッシュで検索。query encoder混雑時はkeywordへ縮退

## 利用条件

このスキルは、ユーザーがRAGの導入または利用を明示した場合だけ使う。通常の会話や開発作業では、サーバーの確認・起動・検索を自動実行しない。

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

# 大規模インデックス向けのFaissは任意
uv sync --extra faiss
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
その場合は **setsid + バックグラウンド実行** を使う。`nohup` 単独では親tool shellのprocess group cleanupに巻き込まれる環境がある。

以下はLinux / WSLの例。`setsid` がないmacOSでは、後述のlaunchdまたはpm2などservice managerで常駐させる。

```bash
cd [SKILL_DIR]/scripts

# バックグラウンドでインデックス作成（PID・ログ・終了コードを保存）
RAG_STATE_DIR="$(mktemp -d)"
TRIGGER_CHANNEL=""  # xangiの場合だけチャンネルIDを設定
setsid bash -lc '
  state_dir="$1"
  trigger_channel="$2"
  echo $$ > "$state_dir/pid"
  uv run python workspace_rag.py index -w [WORKSPACE] > "$state_dir/index.log" 2>&1
  rc=$?
  echo "$rc" > "$state_dir/exit"
  if [ -n "$trigger_channel" ] && command -v xangi-cmd >/dev/null 2>&1; then
    xangi-cmd trigger --channel "$trigger_channel" \
      --message "RAGインデックス処理が終了しました。保存済みの終了状態とログを確認してください" \
      --source workspace-rag-index
  fi
  exit "$rc"
' bash "$RAG_STATE_DIR" "$TRIGGER_CHANNEL" >/dev/null 2>&1 &

# 起動報告前に、親とは別SID/PGIDで生存していることを確認
sleep 2
ps -o pid,ppid,sid,pgid,stat,etime,cmd -p "$(cat "$RAG_STATE_DIR/pid")"
echo "State: $RAG_STATE_DIR"

# 進捗確認
tail -f "$RAG_STATE_DIR/index.log"

# 完了確認
cat "$RAG_STATE_DIR/exit"
tail "$RAG_STATE_DIR/index.log"
```

**ポイント:**
- `setsid bash -lc '...' &` で親tool shellから分離する
- 開始時はPIDの存在だけでなく、`ps` で別SID/PGIDと生存を確認する
- 完了時は終了コードとログを確認する
- xangiでは `TRIGGER_CHANNEL` を設定し、成功・失敗の両方で結果確認のturnを起動する

### Step 3: 検索（常駐サーバー経由 — 推奨）

常駐HTTPサーバーが起動中なら、curlで高速検索できる。ベクトル検索はFaiss `IndexFlatIP`の完全検索を使い、`/health`の`vector_backend`で実際のbackendを確認できる。

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

# インデックス更新（HTTP 202を返し、バックグラウンドで処理）
curl -s -X POST "http://127.0.0.1:7890/reindex"

# 完了確認
curl -s "http://127.0.0.1:7890/health"
```

`POST /reindex`の202は受付完了であり、再索引完了ではない。必要な場合は`reindex_in_progress=false`かつ`last_reindex_error=null`を確認する。再索引中も既存キャッシュで検索できる。

query encoderを短時間で取得できない場合はHTTP待ち行列を伸ばさずkeyword検索へ縮退し、レスポンスへ`degraded: true`と`degraded_reason: "query_encoder_busy"`を付ける。RAG停止とは区別する。

`RAG_VECTOR_BACKEND=numpy`を設定するとベクトルbackendをNumPyへ切り替えられる。Faissのimportまたはindex構築に失敗した場合も自動でNumPyへ縮退する。

**検索モード:**
- **hybrid**（デフォルト）: ベクトル(0.7) + FTS5(0.3) の統合スコア。汎用
- **vector**: ベクトル検索のみ。日本語の意味検索に最適
- **keyword**: FTS5 trigramのみ。英語キーワード・コード検索に最適

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

#### ファクトの粒度

ファクトは「後から検索で一発で取り出したい、比較的変わりにくい事実」を短く持つ。目安は1〜3行、200字程度まで。

ファクトへ入れる例:
- 好み、習慣、記念日、継続利用する環境情報
- 進行中プロジェクトの短い状態と、詳細ファイルへのポインタ

別の場所へ保存する例:
- PRのコミット列挙、検証ログ、日々変わる進捗 → `memory/YYYYMMDD.md` または `MEMORY.md`
- 調査結果、比較、設計の全文 → `notes/`

同じファクトの最新化だけUPDATEし、別トピックはADDする。長文になりそうなら、核となる事実と詳細ファイルへの参照だけを残す。

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

検索結果を回答に使う時は、必要に応じて以下を報告する。

1. 検索したクエリ
2. ヒット件数
3. 重要なファイルパス
4. 違和感があった場合の再検索・代替手段

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

チャットの短い返答では、表形式にこだわらず「RAG: 5件ヒット、主に `notes/foo.md` と `memory/yyyymmdd.md` を参照」のように短くまとめてもよい。

#### 固有名詞・過去履歴を「無い」と判定する前のガード

人名、施設名、製品名、イベント名、過去記事を探す場合、依頼文全体を1本の長い
クエリに詰め込まない。FTS5の空白区切りは実質ANDになり、文書にない周辺語が
1つ混ざるだけでキーワード点が0になる。

1. 最初の検索結果は件数だけでなく、返った全 `k` 件の `file_path` と本文を確認する
2. 固有名詞を2〜3個の短いクエリへ分解する
   - 例: `施設名` / `人名 施設名` / `イベント名`
3. パスや本文に対象語が直接含まれる結果は、スコアが低くてもファイルを開く
RAGが結果を返しているのに採用しなかった場合は「RAGでヒットしなかった」と表現せず、
「結果に出ていたが読み落とした」と区別して報告する。

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
- **スコア計算:** 通常は `base_score * path_weight`。`forgetting=on` のときだけ
  `base_score * path_weight * freshness_score * decay`

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
