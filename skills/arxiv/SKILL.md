---
name: xs:arxiv
description: arXiv論文の検索・トレンド発見・詳細分析を行う統合スキル。興味度スコアでユーザーに刺さる論文を自動選定。PDF全文読み込み・Notion蓄積対応。「arXivチェックして」「論文検索」「論文分析して」で使用。
---

# arXiv論文調査スキル

## 重要：デフォルトはabstractのみ

- **全文読み込みはデフォルトでやらない。** abstractベースで要約・スコアリングする
- **全文読み込みをするのは「この論文詳しく」「全文読んで」と明示的に言われた時だけ**
- 検索コマンドは1回で済ませる（複数クエリを投げない）
- 中間報告を出す — 検索開始時に「arXiv検索中…」と一言送ってからコマンド実行

## 興味度スコアの判断基準

ユーザーの興味分野は `AGENTS.md` の「ユーザーについて」セクションを参照する。未設定の場合は以下のデフォルトカテゴリで判断：

- **最高関心（★★★）:** LLM/プロンプトエンジニアリング、AIエージェント、RAG、Computer Use/ブラウザ操作
- **高関心（★★☆）:** ロボティクス/Embodied AI、時系列予測、エッジAI/ローカル推論、TTS/音声合成
- **関心あり（★☆☆）:** 勾配ブースティング、コンピュータビジョン、マルチモーダル、3D生成

ユーザー側で `AGENTS.md` に固有の興味分野（例: 量子情報、創薬AI、強化学習）を書いていれば、そちらを優先する。

## 実行フロー

### Step 1: モード判定

- **検索モード** — 特定トピックの論文を探す
- **トレンドモード** — 最新の注目論文を発見する（スケジュール実行はこれ）
- **分析モード** — 特定論文を深く読む

### Step 2: 論文検索・トレンド取得

3 経路ある。**用途に応じて使い分ける** (export.arxiv.org API は混雑時間帯で 429/503 を返しがちで非推奨、fallback 扱い)。

#### A. トレンドモード (毎朝の自動実行はこれ)

**arxiv 公式 RSS** から並列取得。レート制限ほぼなし、1〜2 秒で完了。

```bash
cd [SKILL_DIR]/scripts && uv run python arxiv_tool.py trending -c cs.AI cs.LG cs.CL cs.CV -d 7 -n 20
```

返り値: `{"total_results": N, "papers": [...], "categories_queried": [...], "categories_failed": [...], "source": "rss"}`

#### B. 検索モード (任意クエリでの探索)

**Semantic Scholar API** がデフォルト。abstract / 著者 / 引用数 / OA PDF URL までリッチに取れる。

```bash
cd [SKILL_DIR]/scripts && uv run python arxiv_tool.py search "transformer attention" -n 10 [--year-from 2025]
```

返り値: `{"total_results": N, "papers": [{id, title, authors, abstract, published, citation_count, ...}], "source": "s2"}`

#### C. fallback: export.arxiv.org API (legacy)

旧経路。S2 が応答しない・S2 にない最新論文を狙うときだけ。指数バックオフリトライ済 (15s→45s→90s)。

```bash
cd [SKILL_DIR]/scripts && uv run python arxiv_tool.py search "クエリ" -n 10 --source legacy --date-from 2026-05-01 -s date
```

#### 検索クエリの最適化（B/C 共通）

- 引用句でフレーズ検索: `"multi-agent systems"`
- OR演算子で関連技術をカバー: `"AI agents" OR "intelligent agents"`
- フィールド指定検索: `ti:"exact title"`, `au:"author name"`, `abs:"keyword"`
- 除外検索: `"machine learning" ANDNOT "survey"`

**主要カテゴリ:** `cs.AI` / `cs.LG` / `cs.CL` / `cs.CV` / `cs.MA` / `cs.RO`

#### エラー時の挙動

S2 や legacy が全リトライ尽きると JSON が以下の形:

```json
{"error": "Semantic Scholar search failed", "detail": "HTTP 429", "retries_exhausted": true, "hint": "..."}
```

このときは:
1. **B → C** か **C → B** に経路を切り替えて再実行 (異なる API なので片方ダメでももう片方は通ることが多い)
2. それでもダメなら諦めて告知「混雑中、明日の定期実行に任せる」
3. 同セッション内で完結させる

#### arxiv ID から metadata 補完

トレンドで拾った論文の追加情報 (引用数等) が欲しいときは `lookup` で個別取得:

```bash
cd [SKILL_DIR]/scripts && uv run python arxiv_tool.py lookup 2401.12345
```

### Step 3: 興味度スコア付与

abstractを読んでAIが判断する（外部LLM不要）。

| スコア | 意味 | アクション |
|--------|------|-----------|
| ★★★ | 必読 | abstract要約 + 詳細コメント |
| ★★☆ | 読む価値あり | 概要紹介 |
| ★☆☆ | 参考程度 | タイトルのみ |
| なし | 関心外 | スキップ |

### Step 4: 論文全文読み込み（リクエスト時のみ）

**デフォルトではabstractのみで要約する。全文読み込みは行わない。**
**「この論文詳しく」「全文読んで」「分析して」と明示的に言われた時だけ全文を読む。**

```bash
# LaTeXソースがあればそちら（数式が正確）
cd [SKILL_DIR]/scripts && uv run python arxiv_tool.py latex {論文ID}

# アブストラクトのみ
cd [SKILL_DIR]/scripts && uv run python arxiv_tool.py latex {論文ID} --abstract-only

# セクション一覧
cd [SKILL_DIR]/scripts && uv run python arxiv_tool.py latex {論文ID} --sections

# 特定セクションを取得
cd [SKILL_DIR]/scripts && uv run python arxiv_tool.py latex {論文ID} --section "2.1"

# LaTeXソースが無い論文はPDFダウンロード→Markdown変換
cd [SKILL_DIR]/scripts && uv run python arxiv_tool.py download {論文ID} -o /tmp/papers
cd [SKILL_DIR]/scripts && uv run python arxiv_tool.py read {論文ID} -o /tmp/papers
```

**使い分け:**
- 数式が少ない論文 → PDF→Markdown で十分
- 数式が多い論文（数学、物理、理論系ML等） → LaTeXソースを使う
- LaTeXソースが存在しない論文もある（その場合はPDFにフォールバック）

### Step 5: 出力

**論文ごとに `===` で区切って出力する。**

```
★★★ **論文タイトル**
arXiv: {ID} | {著者} | {日付}
{URL}

{abstractベースの要約・分析 3-5文}

**新規性:** {何が新しいか}
**ユーザー的ポイント:** {なぜそのユーザーに関係あるか}
===
★★☆ **論文タイトル**
arXiv: {ID} | {著者}
{URL}

{abstract要約 1-2文}
===
★☆☆ {タイトル} ({ID}) — {一言}
```

### Step 5-2: 注目ピックアップ（必須）

論文一覧の後に、特に注目の1-2件を「注目ピックアップ」として再掲する。
**1論文 = 1投稿**（リプライ・コピペしやすくするため）。複数論文を1メッセージにまとめない。

```
💡 **arXiv注目ピックアップ (1/N)**

**論文タイトル**
arXiv: {ID}
{URL}

{なぜ注目か、技術的なポイント、ユーザーとの関連を2-3文で}
===
💡 **arXiv注目ピックアップ (2/N)**

**論文タイトル**
arXiv: {ID}
{URL}

{解説}
```

### Step 6: Notion蓄積（ユーザーに頼まれた時のみ）

**自動保存しない。** 「Notionに保存して」「DBに登録して」と言われた時だけ実行する。

#### 6-1. DBプロパティ登録

`notion-manager` スキル経由で Notion DB にエントリ追加（DB IDはユーザーが指定）。

プロパティ例: タイトル、著者、arXiv ID、URL、興味度、分野、一言メモ、分析日、全文読了

#### 6-2. ページ本文に分析内容を記載

以下のフォーマットに沿って記載：

```markdown
## エグゼクティブサマリー
{論文の目的・手法・結果を3-5文で}

## 新規性
{何が新しいか。既存手法との違い}

## 手法
{提案手法の概要。図や数式があれば言及}

## 結果
{主要な実験結果。数値を含める}

## ユーザー的ポイント
{なぜユーザーに関係あるか。やってるプロジェクト・興味分野との接続点}

## 次に読む論文
{関連論文2-3件}
```

#### 6-3. 論文PDFを添付

```bash
# PDFダウンロード（Step 4で未取得の場合）
cd [SKILL_DIR]/scripts && uv run python arxiv_tool.py download {論文ID} -o /tmp/papers

# notion-managerスキルでPDFをNotionページに添付
cd [WORKSPACE]/skills/notion-manager && uv run python notion_tool.py upload /tmp/papers/{論文ID}.pdf {ページID} --as-file -c "{論文タイトル} PDF"
```

## 使用例

- 「arXivチェックして」→ トレンドモード
- 「RAGの最新論文探して」→ 検索モード
- 「この論文分析して {URL}」→ 分析モード
- 「Notionに保存して」→ Step 6を実行

## 完了前チェックリスト

```
□ arxiv_tool.py の結果から興味度スコア付き論文一覧を整形した
□ ★★★/★★☆ 論文ごとに `===` 区切りで本体テキストを出力した（中間報告だけで終わらない）
□ 論文URL（http://arxiv.org/abs/{ID}）を含めた
□ 「Notionに保存して」と言われた場合のみ Step 6 を実行した（自動保存しない）
```

## ライセンス

全依存ライブラリが商用利用可能なライセンス：
- `arxiv` (MIT), `python-dateutil` (Apache-2.0/BSD-3-Clause), `arxiv-to-prompt` (MIT), `markitdown` (MIT)
