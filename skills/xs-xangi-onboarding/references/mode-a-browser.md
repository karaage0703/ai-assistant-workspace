# モード A: ブラウザ（Standalone）

> **対象**: すぐ動かしたい人 / 初めて触る人
> **所要時間**: 約 5 分（初回モデル DL 別途数分）
> **前提**: Docker, git, 空き 10GB+

Discord/Slack 設定不要。`quickstart.sh` がワークスペース clone + モデル DL + Docker compose 起動まで全部やってくれる。

## 全体像

```bash
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

## Step 1: 前提チェック

```bash
docker --version && docker compose version
git --version
df -h ~ | tail -1   # 空きが 10GB 以上あるか
```

不足時の案内:

- Docker 未導入 → <https://docs.docker.com/get-docker/>
- Mac は Docker Desktop 入れてから `--mac` オプション推奨（ホスト Ollama で Metal GPU が使える）

## Step 2: クローン場所を決める

既存の xangi ディレクトリと衝突しないように専用ディレクトリへ:

```bash
mkdir -p ~/xangi-onboarding && cd ~/xangi-onboarding
git clone https://github.com/karaage0703/xangi.git
cd xangi
```

## Step 3: 起動

```bash
./quickstart.sh          # Linux/WSL（Docker 内 Ollama）
./quickstart.sh --mac    # Mac（ホスト Ollama + Metal GPU）
```

初回はモデル pull で数分かかる。完了したらブラウザで:

```
http://localhost:18888
```

## Step 4: 初回対話（BOOTSTRAP.md フロー）

ブラウザに繋いで「こんにちは」と打つと、xangi が `BOOTSTRAP.md` を読み込み対話形式でセットアップを進める（約 3 分）:

- 名前・呼び方
- 興味分野
- 話し方の好み

これらの回答が `AGENTS.md` に書き込まれ、以後のセッションで自動読み込みされる。途中スキップしても OK。

## Step 5: 「魅力体感ツアー」を案内

BOOTSTRAP.md が終わったら、以下を順に試させると xangi の幅が伝わる:

1. **スキル一覧を確認** — 「どんなことができる？」「スキル一覧見せて」
2. **メモを取らせる** — 「今日の気づきメモして: 〇〇」（→ note-taking）
3. **日記を書く** — 「日記書きたい」（→ diary）
4. **音声文字起こし** — 「この音声文字起こして」+ 音声ファイル（→ transcriber）
5. **テックニュース** — 「テックニュースまとめて」（→ tech-news-curation）
6. **ベクトル検索** — 「〇〇について書いたファイル探して」（→ workspace-rag）
7. **arXiv チェック** — 「arXiv チェックして」（→ arxiv）

## Step 6: 推奨カスタマイズ

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

## Step 7: モデル選び

| 用途 | モデル例 | 推奨 RAM/VRAM |
|------|---------|--------------|
| 軽量お試し（デフォルト） | `gemma4:e4b` | 8GB+ |
| 標準利用 | `gemma4:26b` | 32GB+ |
| Tool 実行重視 | `nemotron-3-nano` / `nemotron-3-super` | 16GB+ |
| 日本語強め | `qwen3.5:9b` | 16GB+ |

```bash
LOCAL_LLM_MODEL=gemma4:26b ./quickstart.sh
```

## Step 8: 停止・再起動

```bash
# 停止
cd ~/xangi-onboarding/xangi
docker compose -f docker/docker-compose.standalone.yml down

# 再起動
./quickstart.sh
```

## Step 9: トラブル対処

| 症状 | 対処 |
|------|------|
| `port is already allocated`（18888 競合） | `WEB_CHAT_PORT=18889 ./quickstart.sh` |
| Ollama がモデル pull できない | `docker logs ollama` でエラー確認、ネットワーク・空き容量チェック |
| 応答が遅い | `LOCAL_LLM_NUM_CTX=8000` を `.env` に追加、または軽量モデルに戻す |
| Mac で重い | `--mac` モードに切り替え（ホスト Ollama の Metal GPU を使う） |
| 文字化け・古い挙動 | `git pull` で xangi 最新版に更新 |

## Step 10: 次の一歩

気に入ったらモード B（Discord）かモード C（Docker フル）にステップアップ。ワークスペースを引き継げば対話履歴・メモはそのまま残る。

スタックチャン（M5Stack 単体ロボット）と連動させたくなったらモード D（`references/mode-d-stackchan.md`）へ。

## 出力フォーマット

セットアップ完了報告:

```
xangi 起動完了（ブラウザモード）

アクセス: http://localhost:18888
モデル: <モデル名>
ワークスペース: ~/xangi-onboarding/xangi/ai-assistant-workspace

最初に試して: 「こんにちは」と挨拶 → BOOTSTRAP.md フローで自分用にカスタマイズ
停止: docker compose -f docker/docker-compose.standalone.yml down
```
