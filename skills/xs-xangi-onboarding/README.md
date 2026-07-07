# xangi-onboarding -- xangi 立ち上げ伴走スキル

[xangi](https://github.com/karaage0703/xangi)（マルチバックエンドAIアシスタント）の新しいインスタンスを **4 モード** から選んで立ち上げ、初心者の定着まで伴走するスキル。

## 何ができる

- 用途に合わせて最適な起動モードを選ぶ対話フロー
- 該当モードのセットアップを Step ごとに案内
- 初回 `BOOTSTRAP.md` 対話の進行サポート
- 魅力体感ツアー（メモ・日記・音声文字起こし・テックニュース・RAG 検索 等）
- モード別の推奨カスタマイズとトラブル対処

## 4 モード

| モード | 向いてる人 | 特徴 |
|--------|----------|------|
| A. ブラウザ（Standalone） | すぐ動かしたい / 初めて | `quickstart.sh` で約 5 分、トークン不要、Web UI |
| B. Discord | 普段使いしたい人（標準） | Bot 常駐、スマホからも使える、対話履歴が貯まる |
| C. Docker（フル compose） | セキュアに使いたい上級者 | カスタム `.env`、systemd 常駐、認可・公開範囲制御 |
| D. スタックチャン連動 | 物理アバターと喋らせたい上級者 | M5Stack ロボに USB 接続して TTS + 表情 + 首振り |

モード A〜C は単独完結、モード D は A〜C で xangi が動いている前提の追加構成。

## 構成

```
skills/xs-xangi-onboarding/
├── SKILL.md                       # エントリ + モード選択提示 + ナビ
├── README.md                      # この説明
└── references/
    ├── mode-a-browser.md          # ブラウザモード（Standalone）詳細手順
    ├── mode-b-discord.md          # Discord モード詳細手順
    ├── mode-c-docker.md           # Docker フル compose 詳細手順
    └── mode-d-stackchan.md        # スタックチャン連動（上級者向け）
```

詳細は `SKILL.md` を読んだ後、ユーザーが選んだモードの `references/mode-*.md` を順に追って実行する。SKILL.md 本体は分岐ハブの役割のみに圧縮されており、コンテキスト浪費を抑える設計（progressive disclosure）。

## 使い方

スキル発火フレーズ例:

```
xangi 入れたい
xangi セットアップ手伝って
新しい xangi インスタンス立ち上げて
ブラウザで使える xangi 作って
Discord で動く xangi 作って
本番運用の xangi 立ち上げたい
xangi にスタックチャンも繋ぎたい
```

Claude Code / Codex CLI / Grok CLI / xangi から呼び出すと、まず 4 モードのテーブルが提示され、ユーザーが番号で選んだ後に該当 references を Read して具体的なセットアップに入る。

## 関連リンク

- [xangi 本体](https://github.com/karaage0703/xangi)
- [ai-assistant-workspace](https://github.com/karaage0703/ai-assistant-workspace)（このスキルの推奨ワークスペース）
- [xangi-stackchan](https://github.com/karaage0703/xangi-stackchan)（モード D で使う物理アバター連動ブリッジ）
- [docs/discord-setup.md](https://github.com/karaage0703/xangi/blob/main/docs/discord-setup.md)（Discord Bot 作成）
- [docs/usage.md](https://github.com/karaage0703/xangi/blob/main/docs/usage.md)（環境変数・運用詳細）
