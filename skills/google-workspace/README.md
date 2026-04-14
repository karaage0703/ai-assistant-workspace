# google-workspace — Gmail・Drive・Calendar操作スキル

gogcli CLI経由でGoogle Workspaceサービスを操作する。複数アカウント対応。

## 前提条件

- [gogcli](https://github.com/steipete/gogcli) がインストール済みであること
- Google Cloud ConsoleでOAuth 2.0クライアントIDが設定済みであること

## gogcliのインストール

```bash
# macOS / Linux (Homebrew)
brew install gogcli

# Arch Linux
yay -S gogcli

# バイナリ直接ダウンロード（リリースページ: https://github.com/steipete/gogcli/releases）
mkdir -p ~/bin
curl -L https://github.com/steipete/gogcli/releases/latest/download/gogcli_<version>_<os>_<arch>.tar.gz | tar xz -C ~/bin gog

# PATHに追加（.bashrc等に記載）
export PATH="$HOME/bin:$PATH"
```

詳しいセットアップは [gogcli公式README](https://github.com/steipete/gogcli) を参照。

## 認証設定

```bash
# キーリングパスワードを設定（認証情報の暗号化に使用）
export GOG_KEYRING_PASSWORD=<任意のパスワード>

# ブラウザがある環境（PC等）
gog auth add <your-email@gmail.com> --services gmail,drive,calendar

# ヘッドレス環境（サーバー等）
gog auth add <your-email@gmail.com> --services gmail,drive,calendar --remote --step 1
# → 表示されたURLをブラウザで開いて認証
# → リダイレクトURLをコピー
gog auth add <your-email@gmail.com> --services gmail,drive,calendar --remote --step 2 --auth-url "<リダイレクトURL>"

# 認証済みアカウント一覧
gog auth list
```

## 使い方

```bash
# 環境変数を設定（毎回必要）
export PATH="$HOME/bin:$PATH"
export GOG_KEYRING_PASSWORD=<your-password>

# Gmail: 未読メール確認
gog -a <email> gmail search "is:unread" --max 10

# Gmail: メール本文を読む
gog -a <email> gmail read <messageId>

# Drive: ファイル一覧
gog -a <email> drive list

# Calendar: 今週の予定
gog -a <email> calendar list --days 7 --all
```

詳しいコマンドは `SKILL.md` を参照。
