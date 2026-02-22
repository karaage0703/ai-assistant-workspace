---
name: marp-slides
description: Marp（Markdown Presentation）でプレゼンスライドを作成するスキル。PDF/PPTX/HTMLに変換可能。「スライド作って」「プレゼン資料を作って」で使用。
---

# スライド作成スキル

Marp（Markdown Presentation）を使ってプレゼンスライドを作成するスキルです。

## トリガー

「スライド作って」「プレゼン資料を作って」「LT資料を作って」

## 使い方

### 基本的な流れ

1. ユーザーからテーマ・内容を確認する
2. Marp形式のMarkdownを生成する
3. `notes/` または指定の場所に保存する
4. PDF/PPTXに変換する（ユーザーが希望した場合）

### テンプレート

`examples/templates/` にテンプレートがあります：
- `slide-default.md` — シンプルな汎用テンプレート
- `slide-tech.md` — 技術発表向け（ダークテーマ）

### Marp記法の基本

```markdown
---
marp: true
theme: default
paginate: true
---

# スライドタイトル

内容

---

# 次のスライド

- ポイント1
- ポイント2
```

- `---` でスライドを区切る
- `paginate: true` でページ番号を表示
- `<!-- _class: invert -->` でスライドを反転（暗い背景）

### 画像の挿入

```markdown
![width:500px](画像パス)
![bg right:40%](背景画像パス)
```

### PDF/PPTX変換

```bash
# Marp CLIのインストール（初回のみ）
npm install -g @marp-team/marp-cli

# PDFに変換
marp スライド.md --pdf

# PPTXに変換
marp スライド.md --pptx

# HTMLに変換
marp スライド.md --html
```

### ヒント

- 1スライド1メッセージが基本
- 文字は少なめ、キーワードと図を中心に
- 5分のLTなら5〜8枚が目安
- 発表者ノートは `<!-- ここにメモ -->` で書ける
