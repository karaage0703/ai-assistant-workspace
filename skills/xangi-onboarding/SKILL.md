---
name: xs:xangi-onboarding
description: xangi の新しいインスタンスをブラウザモード（Standalone）で立ち上げ、初心者の定着まで伴走するスキル。Discord/Slack トークン不要、ローカルLLM（Ollama）+ Web チャットUIで動作。推奨ワークスペース ai-assistant-workspace の自動展開、初回セットアップ、魅力体感ツアー、おすすめカスタマイズ、次の一歩までをガイドする。「xangi 入れたい」「xangi セットアップ」「xangi 始めたい」「xangi-onboarding」「新しい xangi インスタンス立てたい」で発動。
---

# xangi onboarding

xangi（マルチバックエンドAIアシスタント）の新しいインスタンスを **ブラウザモード（Standalone）** で立ち上げる。Discord/Slack 設定不要、Docker さえあれば数分で動く。

## こんなときに使う

- xangi を初めて触る人が魅力を最速で体感したい
- 既存ユーザーがお試し用に追加インスタンスを立てたい
- API キー・Bot トークン無しでまず動かしてみたい

## 全体像

```
git clone https://github.com/karaage0703/xangi.git
cd xangi
./quickstart.sh        # Linux/WSL
./quickstart.sh --mac  # Mac（ホスト Ollama, Metal GPU）
# → http://localhost:18888 をブラウザで開く
```

`quickstart.sh` がやってくれること:

1. 推奨ワークスペース [ai-assistant-workspace](https://github.com/karaage0703/ai-assistant-workspace) を自動 clone
2. デフォルトモデル `gemma4:e4b`（約3GB）を Ollama に pull
3. Docker compose で xangi + Ollama + Web チャットUI を一括起動

## 実行フロー

### Step 1: 前提チェック

```bash
docker --version && docker compose version
git --version
df -h ~ | tail -1   # 空きが 10GB 以上あるか
```

不足時の案内:

- Docker 未導入 → https://docs.docker.com/get-docker/
- Mac は Docker Desktop 入れてから `--mac` オプション推奨（ホスト Ollama で Metal GPU が使える）

### Step 2: クローン場所を決める

既存の xangi ディレクトリと衝突しないように専用ディレクトリへ:

```bash
mkdir -p ~/xangi-onboarding && cd ~/xangi-onboarding
git clone https://github.com/karaage0703/xangi.git
cd xangi
```

### Step 3: 起動

```bash
./quickstart.sh          # Linux/WSL（Docker 内 Ollama）
./quickstart.sh --mac    # Mac（ホスト Ollama + Metal GPU）
```

初回はモデル pull で数分かかる。完了したらブラウザで:

```
http://localhost:18888
```

### Step 4: 初回対話（BOOTSTRAP.md フロー）

ブラウザに繋いで「こんにちは」と打つと、xangi が `BOOTSTRAP.md` を読み込み対話形式でセットアップを進める（約3分）:

- 名前・呼び方
- 興味分野
- 話し方の好み

これらの回答が `AGENTS.md` に書き込まれ、以後のセッションで自動読み込みされる。途中スキップしても OK。

### Step 5: 「魅力体感ツアー」を案内

BOOTSTRAP.md が終わったら、以下を順に試させると xangi の幅が伝わる:

1. **スキル一覧を確認** — 「どんなことができる？」「スキル一覧見せて」
2. **メモを取らせる** — 「今日の気づきメモして: 〇〇」（→ note-taking）
3. **日記を書く** — 「日記書きたい」（→ diary）
4. **音声文字起こし** — 「この音声文字起こして」+ 音声ファイル（→ transcriber）
5. **テックニュース** — 「テックニュースまとめて」（→ tech-news-curation）
6. **ベクトル検索** — 「〇〇について書いたファイル探して」（→ workspace-rag）
7. **arXiv チェック** — 「arXiv チェックして」（→ arxiv）

ai-assistant-workspace には 20+ スキルがプリセットされているので、興味に応じて試行錯誤を促す。

### Step 6: 推奨カスタマイズの提案

慣れてきたら `.env` でいじれる箇所を案内:

**コンテキスト幅を絞って高速化:**

```bash
# .env に追記
LOCAL_LLM_NUM_CTX=8000
```

未指定だとモデル最大値（例: 262144）が使われて遅くなる。普段使いは 8000〜16000 で十分速い。

**Web チャットだけ動かしたい場合の最低限 .env:**

```bash
WEB_CHAT_ENABLED=true
WEB_CHAT_PORT=18888
AGENT_BACKEND=local-llm
LOCAL_LLM_MODEL=gemma4:e4b
WORKSPACE_PATH=./ai-assistant-workspace
```

### Step 7: モデル選び

マシンスペックに応じて推奨が変わる:

| 用途 | モデル例 | 推奨RAM/VRAM |
|------|---------|--------------|
| 軽量お試し（デフォルト） | `gemma4:e4b` | 8GB+ |
| 標準利用 | `gemma4:26b` | 32GB+ |
| Tool 実行重視 | `nemotron-3-nano` / `nemotron-3-super` | 16GB+ |
| 日本語強め | `qwen3.5:9b` | 16GB+ |

モデルを変えて起動:

```bash
LOCAL_LLM_MODEL=gemma4:26b ./quickstart.sh
```

迷ったらデフォルトでまず動かして、物足りなければ増量。Mac は `--mac` で Metal を使うと体感がだいぶ違う。

### Step 8: 停止・再起動

```bash
# 停止
cd ~/xangi-onboarding/xangi
docker compose -f docker/docker-compose.standalone.yml down

# 再起動
./quickstart.sh
```

### Step 9: トラブル対処

| 症状 | 対処 |
|------|------|
| `port is already allocated`（18888 競合） | `WEB_CHAT_PORT=18889 ./quickstart.sh` |
| Ollama がモデル pull できない | `docker logs ollama` でエラー確認、ネットワーク・空き容量チェック |
| 応答が遅い | `LOCAL_LLM_NUM_CTX=8000` を `.env` に追加、または軽量モデルに戻す |
| Mac で重い | `--mac` モードに切り替え（ホスト Ollama の Metal GPU を使う） |
| 文字化け・古い挙動 | `git pull` で xangi 最新版に更新 |

詳細は [xangi/docs/usage.md](https://github.com/karaage0703/xangi/blob/main/docs/usage.md) を参照。

### Step 10: 次の一歩

ブラウザモードで気に入ったら、以下にステップアップできる:

- **Discord 連携** — Bot トークン取得 → `.env` に `DISCORD_TOKEN` と `DISCORD_ALLOWED_USER` 追加 → 通常モードへ。ワークスペースをそのまま使えるので対話履歴・メモは引き継がれる。[Discord セットアップ](https://github.com/karaage0703/xangi/blob/main/docs/discord-setup.md)
- **Claude Code バックエンド** — `.env` に `AGENT_BACKEND=claude-code` 設定。別途 `curl -fsSL https://claude.ai/install.sh | bash` でインストール。応答品質が一気に上がる
- **pm2 で常駐** — `pm2 start "npm start" --name xangi` で再起動・自動復帰可能に
- **マルチインスタンス連動** — xangi を 2 つ立てて inter-instance-chat で会話させたり、xangi-pets（デスクトップマスコット）と組み合わせる発展形もある

## 出力フォーマット

セットアップ完了報告のテンプレ:

```
✅ xangi 起動完了！

📍 アクセス: http://localhost:18888
📦 モデル: <モデル名>
📁 ワークスペース: ~/xangi-onboarding/xangi/ai-assistant-workspace

▶️ 最初に試して: 「こんにちは」と挨拶 → BOOTSTRAP.md フローで自分用にカスタマイズ

🛑 停止: docker compose -f docker/docker-compose.standalone.yml down
```

## 注意

- **既存 xangi インスタンスとのポート競合**: 同マシンで他の xangi が 18888 を使っていたら `WEB_CHAT_PORT` を別に指定する
- **ホスト Ollama 共有**: Mac モードでは複数 xangi がホスト Ollama を共有するため、モデル pull の重複が無くて済む（メリット）反面、Ollama を止めると全インスタンスが止まる
- **ai-assistant-workspace の更新**: `quickstart.sh` は `.git` を消してテンプレ展開する仕様なので、ワークスペースを git 管理したいなら起動後に自分で `git init` するか、別途 fork して clone する

## 使用例

```
xangi 入れたい
xangi セットアップ手伝って
新しい xangi インスタンス立ち上げて
xangi-onboarding
xangi 始めたい
ブラウザで使える xangi 作って
```
