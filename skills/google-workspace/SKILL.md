---
name: xs:google-workspace
description: gogcli経由でGmail・Google Drive・Google Calendarを操作するスキル。複数Googleアカウント対応。「メールチェック」「メール確認して」「Driveにアップロード」「Driveのファイル」「Gmailで検索」で使用。
---

# Google Workspace（gogcli）

gogcli CLIで Gmail / Google Drive / Google Calendar を操作する。複数アカウント対応。

## 絶対遵守事項

- メール送信・ファイル削除など**外部に影響する操作は必ず確認してから**実行
- メール本文にプライベートな情報が含まれる場合、グループチャットには流さない

## 環境設定

```bash
export PATH="$HOME/bin:$PATH"
export GOG_KEYRING_PASSWORD=<your-password>
```

全コマンドの先頭にこの2行が必要。パスワードは環境に合わせて設定。

## 登録済みアカウント

```bash
gog auth list
```

## Gmail

### メールチェック（全アカウント一括）

全アカウントの未読メールを確認し、重要なものをピックアップして報告。

```bash
gog -a <email> gmail search "is:unread" --max 10
```

### メール検索

```bash
gog -a <email> gmail search "<Gmailの検索クエリ>" --max 20
```

検索クエリ例:
- `is:unread` — 未読
- `from:someone@example.com` — 特定の送信者
- `subject:会議` — 件名に「会議」
- `newer_than:7d` — 7日以内
- `has:attachment` — 添付あり

### メール本文を読む

```bash
gog -a <email> gmail read <messageId>
```

### メール送信（確認必須）

```bash
gog -a <email> gmail send --to "recipient@example.com" --subject "件名" --body "本文"
```

### その他

```bash
gog -a <email> gmail archive <messageId>      # アーカイブ
gog -a <email> gmail mark-read <messageId>     # 既読にする
gog -a <email> gmail labels list               # ラベル一覧
```

## Google Drive

### ファイル一覧・検索

```bash
gog -a <email> drive list                              # ルート一覧
gog -a <email> drive list --query "name contains 'xxx'" # 検索
gog -a <email> drive list --folder <folderId>           # フォルダ内
```

### ファイルダウンロード

```bash
gog -a <email> drive download <fileId> -o /path/to/output
```

### ファイルアップロード（確認必須）

```bash
gog -a <email> drive upload /path/to/file --folder <folderId>
```

## Google Calendar

### 予定確認

```bash
gog -a <email> calendar list                    # 今日の予定（primaryのみ）
gog -a <email> calendar list --days 7           # 1週間の予定
gog -a <email> calendar list --all --days 7     # 全カレンダー（ファミリー含む）
```

**注意:** デフォルトはprimaryカレンダーのみ。ファミリーカレンダー等を含めるには `--all` を付ける。

## アカウント追加

新しいアカウントを追加する場合:

```bash
# ヘッドレス環境: remoteフローで認証
GOG_KEYRING_PASSWORD=<password> gog auth add <email> --services gmail,drive,calendar --remote --step 1
# → URLをユーザーに送る → ブラウザで認証 → リダイレクトURLを受け取る
GOG_KEYRING_PASSWORD=<password> gog auth add <email> --services gmail,drive,calendar --remote --step 2 --auth-url "<リダイレクトURL>"

# ブラウザがある環境: 直接認証
GOG_KEYRING_PASSWORD=<password> gog auth add <email> --services gmail,drive,calendar
```

※Google Cloud Consoleのテストユーザーに追加が必要。

## 対話フロー

### 「メールチェックして」

1. 全登録アカウントの未読メールを取得
2. ニュースレター・通知系・プロモーションなど重要度の低いメールは自動スキップ
3. **重要なメール**をアカウントごとにハイライトして報告

### 「〇〇のメール読んで」

1. 検索クエリで該当メールを特定
2. `gmail read` で本文取得
3. 要約して報告

### 「Driveにファイルアップロードして」

1. ファイルパスとアップロード先を確認
2. 確認後に実行

## 使用例

```
メールチェックして
未読メール見せて
Zennからのメール探して
Driveのファイル一覧
今週の予定確認
```
