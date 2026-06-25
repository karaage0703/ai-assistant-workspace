---
name: xs-code-reviewer
description: 複数のAI（自分/Codex/Grok/Cursor等）でPRをレビューするスキル。GitHub PRの差分を取得し、各AIの視点を統合したレビューを提供する。GitHubへの投稿はユーザーの明示OK後に行う。「PRレビューして」「コードレビューして」「PR#123をチェック」で使用。
---

# プルリクエストコードレビュー

GitHub CLIを使用してプルリクエストを分析し、バグ・リスク・回帰・不足テストを優先してレビューする。

重要: デフォルトはチャット上でのレビュー報告。GitHubへのコメント投稿、review投稿、approve/request changes は外部状態変更なので、ユーザーの明示OKを取ってから行う。

## 使用方法

```text
PR#123をレビューして
owner/repo の PR#123 をレビューして
このPRを複数AIで見て
```

## レビュー完了の定義

通常レビュー:

1. PR情報と差分を確認した
2. 必要に応じて `xs-multi-agent` で外部AIにも見せた
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

各変更ファイルについて必要に応じて確認する。

```bash
gh pr diff <PR番号> --repo <owner>/<repo> -- <ファイルパス>
```

ローカルにブランチを取得する場合は、既存未コミット変更を確認してから行う。

### Step 3: レビュー観点

優先順位:

1. セキュリティ、データ損失、権限、公開範囲の問題
2. バグ、回帰、エラーハンドリング不足
3. テスト不足、検証不足
4. 仕様・ドキュメントとの不整合
5. 保守性、可読性、設計上の懸念
6. 好みの問題や軽微なスタイル

コードレビューでは、良い点より先に findings を出す。問題がない場合は「ブロッカーなし」と明示し、残るリスクや未検証項目を書く。

### Step 4: マルチエージェント検証

複数AIで見る依頼、重要PR、大きめの差分では `xs-multi-agent` を併用する。

```bash
CONFIG_PATH="$(bash skills/xs-multi-agent/scripts/check_agents.sh)"
cat "$CONFIG_PATH"
```

依頼プロンプトはファイルに保存してから、利用可能な外部エージェントへ渡す。

```bash
cat > /tmp/pr-review-prompt.txt <<'EOF'
以下のPR差分をレビューしてください。
バグ、セキュリティ、回帰、不足テストを優先し、好みの指摘は後回しにしてください。

<PR情報と差分>
EOF

bash skills/xs-multi-agent/scripts/run_agent.sh codex /tmp/pr-review-prompt.txt "$PWD"
```

外部AIが使えない場合は、自分だけでレビューしてよい。その場合は「外部AIは検出したが使用できなかった」と報告する。

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
- Codex: 使用 / 未使用（理由）

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

## チェックリスト

- [ ] `gh pr view` でPR情報を取得した
- [ ] `gh pr diff` で差分を確認した
- [ ] 重要な変更ファイルを直接確認した
- [ ] 必要に応じて `xs-multi-agent` を使った
- [ ] findings を重要度順にした
- [ ] GitHub投稿が必要な場合、投稿前にユーザーのOKを取った
- [ ] 投稿した場合、投稿先URLを報告した

## 注意事項

- GitHub CLI（gh）がインストール・認証済みであることを確認
- PRテンプレートが存在しない場合は、標準的なレビュー観点を適用
- 大量の変更がある場合は、重要度の高い問題から優先する
- 建設的で具体的なフィードバックにする
- 初学者でも分かるように、専門用語には補足を入れる
- 外部AIの出力をそのまま信用しない。差分で再確認してから採用する
