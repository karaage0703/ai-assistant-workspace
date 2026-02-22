---
name: github-repo-analyzer
description: GitHubリポジトリの内容を詳しく分析するスキル。Deepwiki優先で構造化情報を取得し、使えない場合はgh CLIで分析。リポジトリ構造・技術スタック・主要ファイルを整理して報告。「リポジトリ分析して」「このリポジトリ見て」で使用。
---

# GitHub Repo Analyzer

GitHubリポジトリの内容を詳しく分析し、構造化レポートを生成する。

## 手順（必ずこの順番で実行）

### Step 1: リポジトリ情報の正規化

ユーザー入力から `owner/repo` を抽出:
- `https://github.com/owner/repo` → `owner/repo`
- `owner/repo` → そのまま使用

### Step 2: 情報取得（Deepwiki + gh CLI 並行）

**2a. Deepwikiで詳細情報を取得（並行実行）:**

WebFetchで `https://deepwiki.com/<owner>/<repo>` にアクセス。

取得する情報: 概要・目的、アーキテクチャ・設計思想、ディレクトリ構造、技術スタック、主要コンポーネント

**2b. gh CLIでメタ情報を取得（並行実行）:**

```bash
gh repo view <owner>/<repo> --json name,description,stargazerCount,forkCount,licenseInfo,primaryLanguage,createdAt,updatedAt
```

Star数・Fork数・ライセンス・作成日などはDeepwikiにないため、**常にgh CLIで取得する**。

Deepwikiで十分な情報が得られた場合 → Step 4 へ。

### Step 3: gh CLIで詳細分析（Deepwiki失敗時）

Deepwikiが使えない・情報不足の場合:

```bash
# リポジトリのメタ情報取得
gh repo view <owner>/<repo>

# READMEを取得
gh api repos/<owner>/<repo>/readme --jq '.content' | base64 -d

# ディレクトリ構造を取得（ルート）
gh api repos/<owner>/<repo>/contents

# 言語構成を取得
gh api repos/<owner>/<repo>/languages
```

必要に応じて `/tmp` にcloneして詳細分析:
```bash
gh repo clone <owner>/<repo> /tmp/<repo> -- --depth 1
```

**cloneした場合は分析後に削除:**
```bash
rm -rf /tmp/<repo>
```

### Step 4: レポート生成

以下の形式で整理して報告:

```
## <owner>/<repo> 分析レポート

https://github.com/<owner>/<repo>

### 概要
[リポジトリの目的・何をするものか]
- Star: [数] / Fork: [数]
- 作成: [日付] / 最終更新: [日付]

### 技術スタック
- 言語: [主要言語]
- フレームワーク: [使用フレームワーク]
- 主要ライブラリ: [依存関係]

### ディレクトリ構造
[主要ディレクトリとその役割]

### アーキテクチャ
[設計思想・パターン]

### 主要ファイル
[重要なファイルとその役割]

### ライセンス
[ライセンス情報]

### 所感
[特筆すべき点、参考になる設計、気になった点]
```

### Step 5: 保存（求められた場合）

note-taking スキルの手順に従い `notes/` に保存。

## 注意点

- Deepwikiはオープンリポジトリのみ対応。プライベートリポジトリは gh CLI を使う
- cloneは `/tmp` に `--depth 1` で行い、分析後は必ず削除
- 大規模リポジトリの場合、全ファイルを読むのではなく構造とREADMEから把握する

## 使用例

```
このリポジトリ分析して: owner/repo
https://github.com/owner/repo を見て
```
