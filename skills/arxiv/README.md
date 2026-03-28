# arxiv -- arXiv論文調査統合スキル

arXiv論文の検索・トレンド発見・詳細分析を統合的に行うスキル。

## 構成

### スクリプト（`scripts/`）
- `arxiv_tool.py` — arXiv論文操作CLI（検索・ダウンロード・読み込み・LaTeXソース取得）
- `arxiv_fetcher.py` — arXiv論文取得モジュール

### LaTeXソース取得機能
`latex` コマンドで論文のLaTeXソースを直接取得できる。PDFからの変換では崩れやすい数式を正確に読み取れる。数学・物理・理論系ML論文の分析時に特に有効。

内部で [arxiv-to-prompt](https://github.com/takashiishida/arxiv-to-prompt) ライブラリを使用。

## セットアップ

```bash
cd skills/arxiv/scripts && uv sync
```

## 使い方

```bash
cd skills/arxiv/scripts

# 検索
uv run python arxiv_tool.py search "transformer" -n 10 -c cs.AI

# ダウンロード（PDF→Markdown変換付き）
uv run python arxiv_tool.py download 2401.12345

# LaTeXソース取得（数式が多い論文向け）
uv run python arxiv_tool.py latex 2401.12345
uv run python arxiv_tool.py latex 2401.12345 --abstract-only
uv run python arxiv_tool.py latex 2401.12345 --sections
uv run python arxiv_tool.py latex 2401.12345 --section "2.1"
```

## サードパーティライセンス

### arxiv-to-prompt
- **ライセンス:** MIT License
- **著作者:** Copyright (c) 2025 Takashi Ishida
- **リポジトリ:** https://github.com/takashiishida/arxiv-to-prompt
- **用途:** `latex` コマンドでのLaTeXソース取得・セクション抽出
