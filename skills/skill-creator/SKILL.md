---
name: xs:skill-creator
description: スキルの作成・改善を行うスキル。既存スキルの分析から抽出したパターンとテンプレートで統一感のあるスキルを効率的に作成。スキルを作りたい、新しいスキルを追加したい、スキルを改善したい、SKILL.mdを書きたい場合に使用。
---

# スキルクリエイター

ワークスペースの既存スキル群と統一感のあるスキルを作成・改善する。

## 絶対遵守事項

- 対話は日本語で行う
- 作成するスキルのSKILL.mdも日本語で記述

## スキル作成フロー

### Step 1: ヒアリング

ユーザーに以下を確認（わかっている情報はスキップ）：

1. **何をするスキル？** → 主機能の把握
2. **どんな時に使う？** → トリガー条件の特定
3. **入力と出力は？** → データフローの明確化
4. **スクリプトは必要？** → Python/Bash等の自動化有無

### Step 2: 分類と設計

4分類のどれに該当するか判定し、適切なテンプレートを選択：

| 分類 | 特徴 | 例 |
|------|------|-----|
| 対話型 | ユーザーとの対話で成果物を生成 | ブログ記事生成、プレゼン企画 |
| 自動実行型 | 指示一つで取得→加工→出力 | ニュース取得、サイト巡回 |
| ツール連携型 | 外部ツール/APIとの連携 | API操作、DB管理 |
| 思考支援型 | 構造化された思考フレームワーク提供 | ブレスト支援、調査整理 |

テンプレートの詳細は `[SKILL_DIR]/references/templates.md` を参照。

### Step 3: ディレクトリ作成

```bash
# スキル名はケバブケースで
mkdir -p [WORKSPACE]/skills/<skill-name>

# 必要に応じてサブディレクトリ作成
mkdir -p [WORKSPACE]/skills/<skill-name>/scripts
mkdir -p [WORKSPACE]/skills/<skill-name>/references
mkdir -p [WORKSPACE]/skills/<skill-name>/assets
```

### Step 4: スクリプト作成（該当する場合）

スクリプトが必要な場合：
1. `scripts/` にPython/Bashスクリプトを配置
2. **必ず `uv run` で実行する**（`python3` 直接実行は禁止。外部依存ゼロでも `uv run` を使う。理由: python未インストール環境でもuvがPythonを自動解決するため）
3. `--help` オプションを実装
4. **実際に `uv run` でテスト実行して動作確認**

### Step 5: SKILL.md作成

テンプレートに従い作成。以下の要素を必ず含める：

**フロントマター（必須）:**
```yaml
---
name: xs:<skill-name>
description: [50-200文字。何をするか＋いつ使うか＋トリガーフレーズ]
---
```

**本文の構成:**
1. **H1タイトル** - スキル名
2. **1行概要** - 何をするスキルか
3. **絶対遵守事項**（必要な場合）
4. **手順** - Step/STEP形式で番号付き
5. **出力フォーマット** - 期待する出力形式
6. **使用例** - 具体的なトリガーフレーズ

**パス規則:**
- `[SKILL_DIR]` - SKILL.mdがあるディレクトリ
- `[WORKSPACE]` - ワークスペースルート
- ハードコードパス禁止

**保存機能がある場合:**
- note-takingスキルがあればそちらへの委譲を記述
- 直接保存ロジックを書かない

### Step 6: 品質チェック

`[SKILL_DIR]/references/checklist.md` の全項目を確認。

### Step 7: 登録確認

スキルの配置場所がシンボリックリンクで管理されている場合（例: `.claude/skills/` → `skills/`）、`skills/` にフォルダを作るだけで自動認識される。

そうでない場合は、AIツールの設定に新しいスキルを登録する。

### Step 8: README更新

`[WORKSPACE]/skills/README.md` があれば、スキル一覧に追加。

### Step 9: Git同期

```bash
cd [WORKSPACE] && git add -A && git commit -m "Add skill: <skill-name>" && git push
```

### Step 10: 完了報告

```
スキル作成完了！

skills/<skill-name>/
- SKILL.md（XX行）
- scripts/（あれば）
- references/（あれば）
```

---

## スキル改善フロー

既存スキルの改善を依頼された場合：

### Step 1: 現状分析

```bash
# 対象スキルを読む
cat [WORKSPACE]/skills/<skill-name>/SKILL.md

# 行数を確認
wc -l [WORKSPACE]/skills/<skill-name>/SKILL.md
```

### Step 2: チェックリスト適用

`[SKILL_DIR]/references/checklist.md` で問題点を洗い出し。

### Step 3: パターン参照

`[SKILL_DIR]/references/patterns.md` でベストプラクティスと照合。

### Step 4: 改善実施

問題点を修正し、品質チェックを再実行。

### Step 5: Git同期と報告

---

## 参考資料

- `[SKILL_DIR]/references/patterns.md` - スキルの設計パターン集
- `[SKILL_DIR]/references/templates.md` - 分類別テンプレート
- `[SKILL_DIR]/references/checklist.md` - 品質チェックリスト
- `[WORKSPACE]/skills/README.md` - スキル一覧と作成ガイド

## 使用例

```
新しいスキルを作りたい
スキル作って：Twitterトレンド取得
このスキルを改善して
スキルのレビューして
```
