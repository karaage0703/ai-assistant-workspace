---
name: xs-code-reviewer
description: GitHub PRや手元の差分をレビューし、バグ・回帰・不足テストを根拠付きで報告する。チーム指定時は登録済みのxangiチームに依頼し、結果を検証して統合する。「PRレビューして」「コードレビューして」「PR#123をチェック」で使用。
---

# プルリクエストコードレビュー

GitHub CLIを使用してプルリクエストを分析し、バグ・リスク・回帰・不足テストを優先してレビューする。

重要: デフォルトはチャット上でのレビュー報告。GitHubへのコメント投稿、review投稿、approve/request changes は外部状態変更なので、ユーザーの明示OKを取ってから行う。

## 使用方法

```text
PR#123をレビューして
owner/repo の PR#123 をレビューして
登録済みの「レビュー班」でこのPRをレビューして
```

## レビュー完了の定義

通常レビュー:

1. PR情報と差分を確認した
2. チーム指定時は、取得したチームの指摘を差分と照合した
3. findings を重要度順に統合した
4. チャットでレビュー結果を報告した

GitHub投稿まで依頼された場合:

1. 投稿対象（repo / PR / コメント種別）を明示してユーザーのOKを取った
2. GitHubに投稿した
3. 投稿URLまたはPR URLを報告した

## レビュー手順

### Step 1: PR情報の確認

```bash
# PRテンプレートがあれば確認
test -f .github/pull_request_template.md && cat .github/pull_request_template.md

# PR詳細
gh pr view <PR番号> --repo <owner>/<repo> --json title,body,headRefOid,baseRefName,headRefName,files,additions,deletions,url

# 差分
gh pr diff <PR番号> --repo <owner>/<repo>

# 変更ファイル一覧
gh pr diff <PR番号> --repo <owner>/<repo> --name-only
```

`--repo <owner>/<repo>` を明示する。remote が複数ある環境では、`gh` が別リポジトリを選ぶ事故が起きやすい。

### Step 2: ファイル別詳細分析

差分から該当ファイルの変更を確認し、必要に応じて手元のコードを `git show <headRefOid>:<ファイルパス>` で読む。手元に対象コミットがない場合は対象SHAでファイルを取得する。GitHub CLIが使えない場合はユーザーが提示した差分や手元の差分を使い、確認できた範囲を報告する。

### Step 3: レビュー観点

優先順位:

1. セキュリティ、データ損失、権限、公開範囲の問題
2. バグ、回帰、エラーハンドリング不足
3. テスト不足、検証不足
4. 仕様・ドキュメントとの不整合
5. 保守性、可読性、設計上の懸念
6. 好みの問題や軽微なスタイル

コードレビューでは、良い点より先に findings を出す。問題がない場合は「ブロッカーなし」と明示し、残るリスクや未検証項目を書く。

### Step 4: 指定されたチームへの依頼

通常は現在のセッションでレビューする。チームを指定された場合は、実行環境のxangi CLIで `tool help team` を読み、`team list` と `team show` で登録済みチームとリーダーを確認する。複数AIでのレビューを希望され、候補が複数ある場合は使うチームを確認する。チームを利用できない場合は理由を伝え、現在のセッションでレビューを続ける。

チームが対象コードを参照できることを確認し、PR URL、確認したHEAD、レビューに必要な差分と背景、観点を `team run` の依頼に含める。登録済みのリーダーがいない場合は、helpに沿って各担当の依頼も渡す。チームへの依頼範囲は読み取りとレビューに絞る。

run IDで `team status` または `team wait` を使って結果を確認する。未完了なら同じIDで確認を続ける。失敗した担当や確認できなかった範囲は報告し、取得できた指摘を差分と照合してから採用する。確認が済んだ依頼は `team close` で終了する。

### Step 5: 結果統合

複数AIの意見はそのまま並べず、重複をまとめて重要度順に統合する。

重要度:

- `blocker`: セキュリティ、データ損失、明確なバグ、重大な回帰
- `major`: 修正した方がよい設計・仕様・テスト不足
- `minor`: 軽微な改善
- `nit`: 好みや表記揺れ。必要な時だけ

誤検出の可能性がある指摘は、必ず差分やファイルを再確認してから出す。

## 出力フォーマット

```markdown
レビュー結果

- blocker: 0件
- major: 1件
- minor: 2件

Findings

1. major: <タイトル>
   - file: <path>:<line>
   - 内容:
   - 理由:
   - 修正案:

2. minor: <タイトル>
   - file:
   - 内容:

確認したこと
- `gh pr view ...`
- `gh pr diff ...`
- チームレビュー: チーム名・確認範囲（利用した場合）

残るリスク
- ...
```

問題が見つからない場合:

```markdown
ブロッカーなし。

確認したこと
- ...

残るリスク
- <未実行テストや見ていない範囲>
```

## GitHubに投稿する場合

GitHub投稿は外部状態変更。以下を明示してOKを取る。

```text
これから public/private repo <owner>/<repo> の PR #<番号> に以下を投稿します。
- review comment: <件数>
- summary review: 1件

OK？
```

OK後に投稿する。

### サマリーのみ投稿

```bash
gh pr review <PR番号> --repo <owner>/<repo> --comment --body-file /tmp/review-summary.md
```

### インラインコメント投稿

GitHubのインラインコメントは diff position や line/side 指定が必要。失敗しやすいので、投稿前に対象行と diff を確認する。

```bash
COMMIT_ID=$(gh pr view <PR番号> --repo <owner>/<repo> --json headRefOid --jq .headRefOid)

gh api repos/<owner>/<repo>/pulls/<PR番号>/comments \
  -F body="<コメント本文>" \
  -F commit_id="$COMMIT_ID" \
  -F path="<ファイルパス>" \
  -F line=<行番号> \
  -F side=RIGHT
```

投稿できない場合は、サマリーコメントにファイルパス・行番号付きでまとめる。

投稿後はGitHubから対象レビューやコメントを読み戻し、対象PRと本文を確認してURLを報告する。

## 完了前チェックリスト

- [ ] `gh pr view` でPR情報を取得した
- [ ] `gh pr diff` で差分を確認した
- [ ] 重要な変更ファイルを直接確認した
- [ ] チームを使った場合、結果を対象の差分と照合した
- [ ] findings を重要度順にした
- [ ] GitHub投稿が必要な場合、投稿前にユーザーのOKを取った
- [ ] 投稿した場合、GitHubから読み戻して投稿先URLを報告した
- [ ] 指摘と未確認範囲を整形し、レビュー本文を返した

## 注意事項

- GitHub CLI（gh）がインストール・認証済みであることを確認
- PRテンプレートが存在しない場合は、標準的なレビュー観点を適用
- 大量の変更がある場合は、重要度の高い問題から優先する
- 建設的で具体的なフィードバックにする
- 初学者でも分かるように、専門用語には補足を入れる
- 外部AIの出力をそのまま信用しない。差分で再確認してから採用する
