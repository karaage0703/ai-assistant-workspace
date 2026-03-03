---
name: xs:arxiv
description: arXiv論文の検索・トレンド発見・詳細分析を行う統合スキル。Pythonスクリプト経由で論文を検索・ダウンロード・読み込み、話題性指標による定量評価でトレンド論文を自動選定。論文検索、トレンド把握、論文分析、研究調査時に使用。
---

# arXiv論文調査統合スキル

arXiv論文の検索、トレンド発見、詳細分析を統合的に行う。

## 絶対遵守事項

- 対話は日本語で行う

## スキル構成

- `scripts/arxiv_tool.py` - arXiv論文操作CLIスクリプト
- `scripts/arxiv_fetcher.py` - arXiv論文取得モジュール
- `scripts/pyproject.toml`, `scripts/uv.lock` - 依存関係定義

## 実行フロー

### Step 1: ユーザーの要望を確認

以下のモードを判定:
- **検索モード**: 特定のトピックや論文を探している
- **トレンドモード**: 最新のトレンド論文を知りたい
- **分析モード**: 特定の論文を詳しく分析したい

### Step 2: 論文検索

```bash
cd [SKILL_DIR]/scripts && uv run python arxiv_tool.py search "検索クエリ" \
  -n 10 \
  -c cs.AI cs.LG \
  --date-from 2024-01-01 \
  -s relevance
```

`[SKILL_DIR]`はこのSKILL.mdがあるディレクトリ。

**検索クエリの最適化**：
- 引用句でフレーズ検索: `"multi-agent systems"`
- OR演算子で関連技術をカバー: `"AI agents" OR "intelligent agents"`
- フィールド指定検索: `ti:"exact title"`, `au:"author name"`, `abs:"keyword"`
- 除外検索: `"machine learning" ANDNOT "survey"`

**主要カテゴリ**：

- `cs.AI` - 人工知能
- `cs.LG` - 機械学習
- `cs.CL` - 計算言語学（NLP）
- `cs.CV` - コンピュータビジョン
- `cs.MA` - マルチエージェントシステム
- `cs.RO` - ロボティクス

**CLIオプション**：
```
-n, --max-results  最大結果数（デフォルト: 10）
-c, --categories   カテゴリフィルタ（複数指定可）
--date-from        開始日（YYYY-MM-DD）
--date-to          終了日（YYYY-MM-DD）
-s, --sort-by      ソート方法（relevance/date）
```

### Step 3: 論文ダウンロード

```bash
cd [SKILL_DIR]/scripts && uv run python arxiv_tool.py download 2401.12345 -o ./papers
```

PDFをダウンロードし、自動的にMarkdownに変換。

**CLIオプション**：
```
-o, --output-dir  出力ディレクトリ（デフォルト: ./papers）
--pdf-only        PDFのみ（Markdown変換しない）
```

### Step 4: ダウンロード済み論文一覧

```bash
cd [SKILL_DIR]/scripts && uv run python arxiv_tool.py list -o ./papers
```

### Step 5: 論文読み込み

```bash
cd [SKILL_DIR]/scripts && uv run python arxiv_tool.py read 2401.12345 -o ./papers
```

### Step 6: LaTeXソースから論文を読む（数式が多い論文向け）

`arxiv-to-prompt` ライブラリを使い、論文のLaTeXソースを直接取得する。PDFからの変換では崩れがちな数式を正確に扱える。

```bash
# LaTeX全文を取得
cd [SKILL_DIR]/scripts && uv run python arxiv_tool.py latex 2401.12345

# アブストラクトのみ
cd [SKILL_DIR]/scripts && uv run python arxiv_tool.py latex 2401.12345 --abstract-only

# セクション一覧
cd [SKILL_DIR]/scripts && uv run python arxiv_tool.py latex 2401.12345 --sections

# 特定セクションを取得
cd [SKILL_DIR]/scripts && uv run python arxiv_tool.py latex 2401.12345 --section "2.1"
```

**使い分け:**
- 数式が少ない論文 → Step 3-5（PDF→Markdown）で十分
- 数式が多い論文（数学、物理、理論系ML等） → このStep 6でLaTeXソースを使う
- LaTeXソースが存在しない論文もある（その場合はStep 3-5にフォールバック）

## トレンド論文発見モード

最新のトレンド論文を話題性指標で評価して発見する場合。

### Phase 1: 基本データ収集

1. **arXiv検索実行**
   ```bash
   cd [SKILL_DIR]/scripts && uv run python arxiv_tool.py search \
     '"transformer" OR "LLM" OR "language model"' \
     -c cs.AI cs.LG cs.CL cs.CV \
     --date-from [1週間前の日付] \
     -n 20 \
     -s date
   ```

2. **基本情報整理**
   - 論文ID、タイトル、著者、アブストラクト、投稿日を抽出
   - 明らかに関連性の低い論文を除外
   - 各論文について著者所属と主要技術分野を事前分析

### Phase 2: 話題性定量評価

各論文に対して以下の指標で評価（100点満点）：

#### 即座評価指標 (40点満点)
1. **著者評判 (15点)**
   - Google Scholar h-index/引用数: h-index 50+ (15点), 20-49 (12点), 10-19 (8点), 5-9 (5点)
   - 著名機関所属: MIT, Stanford, Google, OpenAI等 (+3点)
   - 企業研究者: ByteDance, Apple, Microsoft等 (+2点)

2. **分野注目度 (15点)**
   - 最高優先度 (15点): GPT-5評価, 空間知能, LLM安全性
   - 高優先度 (12点): 4D生成, マルチモーダル, 拡散モデル
   - 中優先度 (10点): 強化学習, エッジAI, 解釈可能AI
   - 基準優先度 (8点): コンピュータビジョン, 自然言語処理

3. **タイミング (10点)**
   - 主要モデルリリース後 (10点)
   - 主要学会締切前（NeurIPS, ICML等）+5点
   - 重要技術イベント前（GTC等）+3点

#### 実装指標 (35点満点)
1. **GitHub実装 (20点)**: WebSearchで検索。公式実装:20点、非公式:10点
2. **Hugging Face登録 (10点)**: site:huggingface.co で検索
3. **企業関与 (5点)**: 企業研究者含有

#### コミュニティ反応指標 (25点満点)
1. **SNS言及 (10点)**: Twitter/reddit検索
2. **研究者ネットワーク (10点)**: 共著者の影響力
3. **実用性 (5点)**: 産業応用の明確性

### Phase 3: スコアリングと選定

1. 総合スコア計算（最大100点）
2. 60点以上の論文を候補として選定
3. 上位5論文を詳細分析対象とする

## 論文詳細分析モード

特定の論文を深く分析する場合。

### 準備フェーズ
1. `list` コマンドでダウンロード済みか確認
2. 未ダウンロードなら `download` コマンドで取得
3. `read` コマンドで全文を読み込み
4. `search` コマンドで関連論文も検索

### 分析構造

**1. エグゼクティブサマリー**
- 2-3文での論文要約
- 主な貢献・解決している問題・主な手法・結果・結論

**2. 研究コンテキスト**
- 研究領域と対象問題
- 先行研究とその限界
- 他の論文との比較

**3. 手法分析**
- アプローチのステップバイステップ解説
- 手法の革新点・理論的基盤・技術的実装
- 再現に必要な情報

**4. 結果分析**
- 実験セットアップ（データセット、ベンチマーク、評価指標）
- 主な実験結果とその意義
- 最先端手法との比較

**5. 実用的含意**
- 実装・応用の可能性
- 利用可能なコード、データセット

**6. 将来の方向性**
- 限界と今後の研究課題
- 他のアプローチとの統合可能性

## 結果の提示

分析結果はチャットに提示して完了。

### 必須セクション
- 基本情報（arXivリンク、著者、投稿日）
- 概要（一言まとめ）
- 新規性（何が過去の研究に比べて凄い？）
- 手法の概要
- **話題性スコア**: [X/100]（トレンドモードの場合）
- **話題性根拠**: スコア内訳と根拠（トレンドモードの場合）
- コメント
- **次に読む論文**: 関連研究3-5件

## 注意点

### ライセンス
全依存ライブラリが商用利用可能なライセンス：
- `arxiv` (MIT), `python-dateutil` (Apache-2.0/BSD-3-Clause), `arxiv-to-prompt` (MIT), `markitdown` (MIT)

### 評価の客観性確保
- 定量的指標を優先し、主観的判断を最小限に
- スコア根拠を必ず記録
- 評価基準の一貫性を保持

### 情報収集の制約
- WebSearch結果がない場合は0点として処理
- 情報不足の場合は明記
- 推測ではなく事実ベースで評価

## 使用例

### 論文検索
```
"attention mechanism" の最新論文を探して
```

### トレンド論文発見
```
この1週間でAI系のトレンド論文を教えて
```

### 特定論文の詳細分析
```
論文 2401.12345 を詳しく分析して
```

### 分野別検索
```
cs.CL カテゴリで RAG に関する論文を10件検索
```
