---
name: xs-github-repo-analyzer
description: GitHubリポジトリの内容を詳しく分析するスキル。現行HEADを確認し、DeepWikiの索引commitの鮮度を検証して併用。リポジトリ構造・技術スタック・主要ファイルを整理して報告。「リポジトリ分析して」「このリポジトリ見て」で使用。
---

# GitHub Repo Analyzer

GitHubリポジトリの内容を詳しく分析し、構造化レポートを生成する。

## 手順（必ずこの順番で実行）

### Step 1: リポジトリ情報の正規化

ユーザー入力から `owner/repo` を抽出:
- `https://github.com/owner/repo` → `owner/repo`
- `owner/repo` → そのまま使用

### Step 2: 現行HEADとDeepWikiの情報を取得

最初にGitHubでdefault branchと現行HEADを確認する。

```bash
is_private="$(gh api repos/<owner>/<repo> --jq '.private')"
default_branch="$(gh api repos/<owner>/<repo> --jq '.default_branch')"
head_sha="$(gh api repos/<owner>/<repo>/commits/"$default_branch" --jq '.sha')"
```

以後のソース確認はこのSHAを基準にする。`is_private=true` の場合はDeepWikiの取得を省略する。

**2a. Deepwikiで詳細情報を取得（並行実行）:**

公開リポジトリの場合だけ、利用できるWeb取得ツールで `https://deepwiki.com/<owner>/<repo>` にアクセス。非公開リポジトリの識別子やコードはDeepWikiへ送らず、GitHubの許可された読み取り経路を使う。

取得する情報: 概要・目的、アーキテクチャ・設計思想、ディレクトリ構造、技術スタック、主要コンポーネント

**2b. gh CLIでメタ情報を取得（並行実行）:**

```bash
gh repo view <owner>/<repo> --json name,description,stargazerCount,forkCount,licenseInfo,primaryLanguage,createdAt,updatedAt
```

Star数・Fork数・ライセンス・作成日などはDeepwikiにないため、**常にgh CLIで取得する**。

DeepWikiの `Last indexed` のcommitリンクから索引SHAを取得し、GitHubの現行HEADと比較する。

```bash
gh api repos/<owner>/<repo>/compare/<index_sha>..."$head_sha" \
  --jq '{status, ahead_by, behind_by, total_commits}'
```

- SHA一致: 現行版の補助解説として使う。
- HEADが先行: 差分があることを示し、主要な主張を現行コードで確認する。
- SHA不明・比較不能・分岐: 鮮度を検証できないと明記し、現在の仕様をDeepWikiだけで断定しない。

いずれの場合もStep 3で主要な機能・構成を確認する。

### Step 3: 現行コードで主要な主張を確認

DeepWikiの取得成否にかかわらず、README・主要コード・設定を確認する。

```bash
# リポジトリのメタ情報取得
gh repo view <owner>/<repo>

# READMEを取得
gh api "repos/<owner>/<repo>/readme?ref=$head_sha" --jq '.content' | base64 -d

# ディレクトリ構造を取得（ルート）
gh api "repos/<owner>/<repo>/contents?ref=$head_sha"

# 言語構成を取得
gh api repos/<owner>/<repo>/languages
```

必要に応じて `/tmp` にcloneして詳細分析:
```bash
repo_tmp="$(mktemp -d)"
gh repo clone <owner>/<repo> "$repo_tmp" -- --depth 1
git -C "$repo_tmp" fetch origin "$head_sha"
git -C "$repo_tmp" checkout --detach "$head_sha"
```

分析後は今回作成した `repo_tmp` だけを、環境のゴミ箱など復元可能な方法で片付ける。他の既存checkoutを削除しない。片付け手段がなければ保存場所を報告する。

### Step 4: レポート生成

以下の形式で整理して報告:

```
## <owner>/<repo> 分析レポート

https://github.com/<owner>/<repo>

### 概要
[リポジトリの目的・何をするものか]
- Star: [数] / Fork: [数]
- 作成: [日付] / 最終更新: [日付]

### 情報鮮度
- 確認したGitHub HEAD: [SHA]
- DeepWiki: [索引SHAと差分 / 未索引 / 検証不能]

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
- cloneは毎回固有の一時ディレクトリへ作成し、確認対象のSHAを固定する
- 大規模リポジトリの場合、全ファイルを読むのではなく構造とREADMEから把握する

## 使用例

```
このリポジトリ分析して: owner/repo
https://github.com/owner/repo を見て
```
