---
name: xs-xangi-settings
description: xangiの設定確認・設定ファイル変更・反映再起動を行うスキル。最新仕様は対象cloneのxangiドキュメントを参照する。「このチャンネルでも応答して」「タイムアウト変えて」「設定確認して」で使用。
---

# xangi 設定変更スキル

チャットから xangi の設定確認、設定ファイル変更、反映再起動を行う。

## 基本方針

xangi 本体の設定項目や運用コマンドは変わる。スキル内の古い一覧だけで判断せず、作業前に対象 clone の一次情報を読む。

読む順番:

1. `[XANGI_ROOT]/docs/usage.md` の環境変数・service・再起動まわり
2. `[XANGI_ROOT]/.env.example`
3. `[XANGI_ROOT]/src/prompts/xangi-commands-chat-platform.ts`（チャット上でAIに注入される最新運用ルール）

`[XANGI_ROOT]` は設定変更対象の xangi clone。`[WORKSPACE]` はこのワークスペース。

## 実行フロー

### Step 1: 対象インスタンスを特定

複数の xangi clone が同じマシンで動くことがあるため、まず対象 clone を決める。

```bash
# 実行中コンテキストが xangi 上なら cwd/repo を確認
pwd
git rev-parse --show-toplevel 2>/dev/null

# xangi clone 候補と設定ファイルを確認
find "$HOME" -maxdepth 2 -name .env -path "$HOME/xangi-*/*" -print 2>/dev/null

# WORKSPACE_PATH / XANGI_INSTANCE_ID / XANGI_PROCESS_NAME / DATA_DIR を見て対象を絞る
for f in "$HOME"/xangi-*/.env; do
  [ -f "$f" ] || continue
  echo "## $f"
  grep -E '^(WORKSPACE_PATH|XANGI_INSTANCE_ID|XANGI_PROCESS_NAME|DATA_DIR)=' "$f" || true
done
```

判定の目安:

- 現在の Discord / Slack / Web Chat / LINE セッションを動かしている clone を優先
- `WORKSPACE_PATH` がこのワークスペースを指す clone を優先
- `XANGI_PROCESS_NAME` は `./bin/xangi service ...` の PM2 対象名
- Docker運用では host 側の compose / 設定ファイルを対象にし、コンテナ内だけを書き換えない

### Step 2: 最新ドキュメントを確認

対象 clone が `/path/to/xangi` なら:

```bash
cd /path/to/xangi
rg -n "service start|service stop|service restart|service status|XANGI_PROCESS_NAME|TIMEOUT_MS|CHANNEL_OVERRIDES|AUTO_REPLY_CHANNELS|SLACK_AUTO_REPLY_CHANNELS|system_settings|system_restart" \
  docs/usage.md .env.example src/prompts/xangi-commands-chat-platform.ts
```

運用ルールの現在形:

- 起動・停止・再起動・状態確認は対象 clone の `./bin/xangi service start|stop|restart|status` を使う
- PATHから使う場合は `xangi-dev` / `xangi-prod` のような名前付き symlink を使う
- `xangi tool system_restart` は起動中プロセスに graceful shutdown を要求する低レベル操作
- `system_settings` は確認用。AI は `system_settings` で設定変更しない
- 設定ファイル変更後は対象 clone で `./bin/xangi service restart` する

### Step 3: 要望の種類を判定

- 設定確認 → Step 4a
- 設定変更 → Step 4b

### Step 4a: 設定確認

```bash
cd /path/to/xangi

# service 状態
./bin/xangi service status

# 現在の設定を確認（トークン等は表示しない）
grep -vE '(TOKEN|SECRET|PASSWORD|API_KEY)=' .env | grep -v '^#' | grep -v '^$'
```

出力例:

```
xangi 現在の設定

- 対象: /path/to/xangi
- service: online
- AUTO_REPLY_CHANNELS: 123456789,987654321
- AGENT_BACKEND: codex
- TIMEOUT_MS: 1800000

※ トークン類は非表示
```

### Step 4b: 設定変更

1. ユーザーの意図から対象変数を決める
2. 対象 clone の `docs/usage.md` / `.env.example` で現在の名前・デフォルト・注意を確認する
3. 設定ファイルの現在値を読む
4. 設定ファイルを編集する（該当行を更新、なければ追加）
5. `git diff -- .env` は secrets を含む可能性があるため、そのまま貼らない。値は必要な範囲だけマスクして報告する
6. 反映に再起動が必要な場合、対象 clone とコマンドを明示して承認を取る

```
設定を変更しました

変更内容:
- AUTO_REPLY_CHANNELS: (なし) → 123456789,987654321

反映には再起動が必要です。
対象: /path/to/xangi
実行予定: cd /path/to/xangi && ./bin/xangi service restart
```

再起動の承認後:

```bash
cd /path/to/xangi
./bin/xangi service restart
./bin/xangi service status
```

## よくある変更

### チャンネル追加（メンションなしで応答）

```
「#generalでも反応して」
→ AUTO_REPLY_CHANNELS にチャンネルIDを追加
```

Slack の場合は `SLACK_AUTO_REPLY_CHANNELS` を使う。必要な Slack scope は対象 clone の `docs/slack-setup.md` で確認する。

### タイムアウト変更

```
「タイムアウトを10分に」
→ TIMEOUT_MS=600000 に変更
```

### ストリーミング切り替え

```
「ストリーミングオフにして」
→ DISCORD_STREAMING=false に変更
```

### 思考表示切り替え

```
「考え中アニメーションにして」
→ DISCORD_SHOW_THINKING=false に変更
```

### バックエンド切り替え設定

チャンネル単位の切り替えは、xangi の slash command が `CHANNEL_OVERRIDES` に永続化する。手動編集する前に現在のコマンド名を `docs/usage.md` で確認する。

```
「ALLOWED_BACKENDSを全部有効にして」
→ ALLOWED_BACKENDS=claude-code,codex,gemini,local-llm に変更 → 再起動

「Local LLMのモデルを変えて」
→ LOCAL_LLM_MODEL=<model> に変更 → 再起動
```

## Docker運用

Docker運用ではコンテナ内の一時設定ではなく、host 側の compose / 設定ファイルを変更する。反映は対象 clone の docker compose で行う。

```bash
cd /path/to/xangi
docker compose restart xangi
```

## Gotchas

- xangi clone を取り違えると変更が反映されない。最初に `WORKSPACE_PATH` と `XANGI_PROCESS_NAME` を見る
- トークン・secret は表示しない。確認時は `grep -vE '(TOKEN|SECRET|PASSWORD|API_KEY)='` を使う
- `system_settings` で AI が設定変更しない。最新の `XANGI_COMMANDS` でも確認専用扱い
- 稼働中の自分を動かしている xangi を再起動する場合は、会話が一時中断するため、対象とコマンドを明示してから承認を取る

## 完了前チェックリスト

```
□ 対象 clone の docs/usage.md / .env.example / src/prompts/xangi-commands-chat-platform.ts を確認した
□ 対象 clone と設定ファイルを取り違えていない
□ secret を表示していない
□ 設定変更後、反映に必要な再起動コマンドを明示した
□ 再起動した場合は ./bin/xangi service status で状態を確認した
```

## 使用例

```
xangiの設定確認して
このチャンネルでも反応するようにして（チャンネルID: 123456789）
タイムアウトを10分に変更して
ストリーミング出力をオフにして
ALLOWED_BACKENDSを設定して
```
