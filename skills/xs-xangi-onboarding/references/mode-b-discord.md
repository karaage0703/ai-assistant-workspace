# モード B: Discord — 標準的な普段使い

> **対象**: 普段使いしたい人（標準モード）
> **所要時間**: 約 15 分（Bot 作成・招待含む）
> **前提**: Docker, git, 空き 10GB+、Discord アカウント、自分のサーバー

Bot として常駐させて、スマホ含めどこからでも話しかけられる構成。

## Step 1: 前提チェック

```bash
docker --version && docker compose version
git --version
df -h ~ | tail -1   # 空きが 10GB 以上
```

加えて以下が必要:

- Discord アカウント
- 自分の Discord サーバー（無ければ無料で 1 個作る）

## Step 2: Discord Bot を作る

1. <https://discord.com/developers/applications> にログイン
2. **New Application** → 名前を入れる（例: `xangi-mybot`）
3. 左サイドの **Bot** タブ → **Reset Token** → 表示されたトークンを控える → `DISCORD_TOKEN`
4. 同画面の **Privileged Gateway Intents** で以下を ON:
   - MESSAGE CONTENT INTENT
   - SERVER MEMBERS INTENT
5. **OAuth2** → **URL Generator**:
   - scopes: `bot`, `applications.commands`
   - bot permissions: `Send Messages`, `Read Message History`, `Attach Files`, `Use Slash Commands`
6. 生成された URL を開いて自分のサーバーに招待

## Step 3: 自分の Discord ユーザー ID を取得

1. Discord 設定 → **詳細設定** → **開発者モード** を ON
2. 自分のアイコンを右クリック → **ID をコピー** → `DISCORD_ALLOWED_USER`

これを設定しないと「誰でも Bot を叩ける」状態になるので必ずやる。

## Step 4: clone と .env

```bash
mkdir -p ~/xangi && cd ~/xangi
git clone https://github.com/karaage0703/xangi.git
cd xangi
cp .env.example .env
```

`.env` を編集:

```bash
# Discord
DISCORD_TOKEN=<Step 2 のトークン>
DISCORD_ALLOWED_USER=<Step 3 の ID>

# Backend
AGENT_BACKEND=local-llm           # 後で claude-code に切り替え可
LOCAL_LLM_MODEL=gemma4:e4b
LOCAL_LLM_NUM_CTX=8000

# Workspace
WORKSPACE_PATH=./ai-assistant-workspace

# Web チャットも併用したいなら（任意）
WEB_CHAT_ENABLED=true
WEB_CHAT_PORT=18888
```

## Step 5: ワークスペース取得

```bash
git clone https://github.com/karaage0703/ai-assistant-workspace.git
# あるいは quickstart.sh と同じ要領で展開
```

## Step 6: 起動

通常モード（Discord 含む）の compose を使う:

```bash
docker compose up -d
docker compose logs -f xangi   # 接続ログを確認
```

ログに `Logged in as xangi-mybot#1234` のような行が出たら接続成功。

## Step 7: 初回対話（BOOTSTRAP）

招待した Discord サーバーで Bot をメンション、または DM で「こんにちは」と話しかける → BOOTSTRAP.md フローが走る（モード A と同じ）。

返答は `AGENTS.md` に記録される。

## Step 8: 魅力体感ツアー

モード A の Step 5 と同じツアーを Discord で試す:

1. 「スキル一覧見せて」
2. 「メモして: 〇〇」
3. 「日記書きたい」
4. 「テックニュースまとめて」
5. 「arXiv チェックして」

Discord の利点として:

- スマホ Discord アプリ経由でどこからでも会話可能
- メッセージ履歴がそのまま記録になる
- ファイル添付（画像・音声）もそのまま渡せる

## Step 9: 推奨カスタマイズ

**反応するチャンネルを制限する:**

```bash
# .env に追記
DISCORD_ALLOWED_CHANNELS=<channel_id_1>,<channel_id_2>
```

**反応の有無を切り替えたいとき:**

ランタイムで `xangi-settings` スキル（「このチャンネルでも応答して」「タイムアウト変えて」等）で `.env` を書き換えて再起動できる。

**Claude Code バックエンドに切り替え（応答品質を上げる）:**

```bash
curl -fsSL https://claude.ai/install.sh | bash   # ホストにインストール
# .env で
AGENT_BACKEND=claude-code
docker compose up -d --build
```

## Step 10: 停止・再起動・アップデート

```bash
# 停止
docker compose down

# 再起動
docker compose up -d

# xangi 更新
git pull && docker compose up -d --build
```

## Step 11: トラブル対処

| 症状 | 対処 |
|------|------|
| Bot がオンラインにならない | `docker compose logs xangi` でトークン誤り / Intent 設定不足を確認 |
| メッセージに反応しない | `MESSAGE CONTENT INTENT` が ON か、`DISCORD_ALLOWED_USER` が自分の ID か再確認 |
| `403 Forbidden` | Bot をサーバーに招待し直す（OAuth URL を再生成） |
| 応答が遅い | `LOCAL_LLM_NUM_CTX=8000` / 軽量モデルへ / Claude Code バックエンドに切り替え |

詳細は [docs/discord-setup.md](https://github.com/karaage0703/xangi/blob/main/docs/discord-setup.md) を参照。

## 次の一歩

セキュアに運用したくなったらモード C（`references/mode-c-docker.md`）へ。
スタックチャン連動させたくなったらモード D（`references/mode-d-stackchan.md`）へ。

## 出力フォーマット

セットアップ完了報告:

```
xangi 起動完了（Discord モード）

接続先: Discord サーバー <名前>
Bot: <Bot 名>
Web UI (任意): http://localhost:18888
ワークスペース: ~/xangi/xangi/ai-assistant-workspace

最初に試して: Bot に DM またはメンションで「こんにちは」
停止: docker compose down
```
