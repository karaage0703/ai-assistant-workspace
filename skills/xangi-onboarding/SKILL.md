---
name: xs:xangi-onboarding
description: xangi の新しいインスタンスを 3 モード（ブラウザ / Discord / Docker フル compose）から選んで立ち上げ、初心者の定着まで伴走するスキル。最初に用途を確認してから分岐する。推奨ワークスペース ai-assistant-workspace の自動展開、初回 BOOTSTRAP、魅力体感ツアー、おすすめカスタマイズ、次の一歩までをガイドする。上級者向けにスタックチャン連動（モード D）もサポート。「xangi 入れたい」「xangi セットアップ」「xangi 始めたい」「xangi-onboarding」「新しい xangi インスタンス立てたい」で発動。
---

# xangi onboarding

xangi（マルチバックエンドAIアシスタント）の新しいインスタンスを **4 モード** から選んで立ち上げる。最初にユーザーに用途を聞いてから、該当モードのフロー（`references/mode-*.md`）に分岐する。

## こんなときに使う

- xangi を初めて触る人が魅力を最速で体感したい
- 既存ユーザーがお試し用に追加インスタンスを立てたい
- Discord / Docker など本格運用に進めたい
- 物理アバター（スタックチャン）と連動させたい

## 最初にやること: モード選択

スキル発動直後、**いきなり起動コマンドを叩かず**、まず以下のテキストを出してユーザーの返答を待つ:

```
xangi の起動モードを選んでください。

| モード | 向いてる人 | 特徴 |
|--------|----------|------|
| 1. ブラウザ（Standalone） | すぐ動かしたい / 初めて | quickstart.sh で約5分、トークン不要、Web UI |
| 2. Discord | 普段使いしたい人（標準） | Bot 常駐、スマホからも使える、対話履歴が貯まる |
| 3. Docker（フル compose） | セキュアに使いたい上級者 | カスタム .env、pm2 / systemd 常駐、認可・公開範囲制御 |
| 4. スタックチャン連動（上級） | 物理アバターと喋らせたい | モード 1〜3 で xangi が動いた後、USB 接続の M5Stack ロボに喋らせる |

迷ったら…
- とにかく試したい  → 1（ブラウザ）
- 日常的に使いたい  → 2（Discord）
- 本番運用 / セキュリティ重視 → 3（Docker フル）
- xangi 既に動いてて物理連動も足したい → 4（スタックチャン）

どれにしますか？
```

返答に応じて該当 references ファイルを Read して、その手順を実行する。途中で「やっぱり別のモードに」と言われたらいつでも切り替えてよい（ワークスペースは引き継げる）。

## モード別の進め方

| モード | 詳細手順 | 所要時間 |
|--------|--------|---------|
| A. ブラウザ（Standalone） | `[SKILL_DIR]/references/mode-a-browser.md` | 約 5 分 |
| B. Discord | `[SKILL_DIR]/references/mode-b-discord.md` | 約 15 分 |
| C. Docker（フル compose） | `[SKILL_DIR]/references/mode-c-docker.md` | 30 分〜数時間 |
| D. スタックチャン連動 | `[SKILL_DIR]/references/mode-d-stackchan.md` | 約 60〜90 分（A/B/C 完了後） |

モードが決まったら**該当 references を Read してその通り実行**する。各 references は Step ごとに区切られて完結している。SKILL.md 本体は分岐ハブの役割のみで、詳細手順は references 側に集約。

## 共通: 魅力体感ツアー

モード A/B/C のセットアップが終わったら、以下を順に試させると xangi の幅が伝わる:

1. **スキル一覧を確認** — 「どんなことができる？」「スキル一覧見せて」
2. **メモを取らせる** — 「今日の気づきメモして: 〇〇」（→ note-taking）
3. **日記を書く** — 「日記書きたい」（→ diary）
4. **音声文字起こし** — 「この音声文字起こして」+ 音声ファイル（→ transcriber）
5. **テックニュース** — 「テックニュースまとめて」（→ tech-news-curation）
6. **ベクトル検索** — 「〇〇について書いたファイル探して」（→ workspace-rag）
7. **arXiv チェック** — 「arXiv チェックして」（→ arxiv）

ツアーの詳細案内は各 references の「Step 5: 魅力体感ツアー」セクションにも記載。

## 注意

- **モード選択を飛ばさない** — 必ず最初に 4 モードを提示してユーザーの返答を待つ。「とりあえず一番速いやつ」と言われたらモード A
- **既存 xangi とのポート競合** — 18888 が使われていたら `WEB_CHAT_PORT=18889` 等で逃がす
- **ホスト Ollama 共有** — Mac モードで複数インスタンスがホスト Ollama を共有する場合、Ollama 停止で全インスタンスが止まる
- **ai-assistant-workspace の git 管理** — `quickstart.sh` は `.git` を消す。git で残したいなら起動後に `git init` するか fork から clone
- **.env の権限** — Discord トークンや API キーを書く場合は `chmod 600 .env`
- **公開モードでの放置厳禁** — モード C で WAN 公開する場合、必ず認証（Basic 認証 / Tailscale / Cloudflare Tunnel）を挟む
- **モード D は単独で動かない** — 必ずモード A/B/C で xangi が動いている前提

## 使用例

```
xangi 入れたい
xangi セットアップ手伝って
新しい xangi インスタンス立ち上げて
xangi-onboarding
xangi 始めたい
ブラウザで使える xangi 作って
Discord で動く xangi 作って
本番運用の xangi 立ち上げたい
xangi にスタックチャンも繋ぎたい
```
