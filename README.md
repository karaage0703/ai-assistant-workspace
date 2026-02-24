# ai-assistant-workspace

あなた専用のAIアシスタント・ワークスペースです。

AIコーディングツール（Claude Code / Codex CLI / Gemini CLI）をパーソナルアシスタントとして活用するためのスターターキットです。初回起動時に対話形式であなた専用のアシスタントが作られます。

[xangi](https://github.com/karaage0703/xangi)（Discord常駐型AIアシスタント）の推奨ワークスペースです。xangiと組み合わせることで、チャットからスキルを呼び出して日常タスクを自動化できます。

## できること

- **メモ管理** — 調査結果・アイデア・会議メモを整理して保存
- **日記** — 日々の記録をNotionと連携して管理
- **猫日記** — 猫の写真を送ると自動判定してNotionに記録
- **Notion連携** — ページの検索・作成・ファイルアップロード
- **音声文字起こし** — 音声ファイルをテキストに変換
- **ポッドキャスト** — ポッドキャストのダウンロード・要約（プリセット番組あり）
- **YouTube** — YouTube動画の内容をノートにまとめる
- **プレゼン作成** — マークダウンからスライドを生成
- **テックニュース** — 最新のAI・技術ニュースを収集・紹介
- **GitHubリポジトリ分析** — リポジトリの構造・技術スタックを分析
- **ワークスペース検索** — ファイルをベクトル検索で横断検索
- **カレンダー** — ICSカレンダー（Googleカレンダー等）の予定を確認
- **健康管理** — 食事・運動の記録と健康アドバイス
- **設定変更** — チャットからAIアシスタントの設定を変更（xangi利用時）
- **スキル作成** — 自分だけのカスタムスキルを作る

## クイックスタート

### 必要なもの

- [Claude Code](https://docs.anthropic.com/en/docs/claude-code/overview)、[Codex CLI](https://github.com/openai/codex)、[Gemini CLI](https://github.com/google-gemini/gemini-cli) のいずれか
- Discordで使う場合: [xangi](https://github.com/karaage0703/xangi)

### セットアップ手順

```bash
# 1. リポジトリをクローン
git clone https://github.com/karaage0703/ai-assistant-workspace
cd ai-assistant-workspace

# 2. AIツールを起動（いずれか）
claude          # Claude Code の場合
codex           # Codex CLI の場合
gemini          # Gemini CLI の場合

# 3. 自動セットアップが始まります
# AIがあなたに質問して、あなた専用のアシスタントを作ります
```

Claude Code の場合、`.claude/skills` → `skills/` のシンボリックリンクがリポジトリに含まれているため、クローンするだけでスキルが使えます。

## ディレクトリ構成

```
ai-assistant-workspace/
├── AGENTS.md              # 設定ファイル（全ツール共通）
├── CLAUDE.md              # → AGENTS.md へのシンボリックリンク
├── GEMINI.md              # → AGENTS.md へのシンボリックリンク
├── BOOTSTRAP.md           # 初回セットアップ用（セットアップ後に削除されます）
├── .claude/
│   └── skills -> ../skills  # Claude Code 用シンボリックリンク
├── .agents/
│   └── skills -> ../skills  # Codex CLI 用シンボリックリンク
├── .gemini/
│   └── skills -> ../skills  # Gemini CLI 用シンボリックリンク
├── memory/                # 日記・メモの保存先
├── notes/                 # ノート・調査メモの保存先
└── skills/                # スキル（AIの拡張機能）
    ├── calendar/          # カレンダースキル
    ├── cat-diary/         # 猫日記スキル
    ├── diary/             # 日記スキル
    ├── github-repo-analyzer/ # GitHubリポジトリ分析スキル
    ├── health-advisor/    # 健康管理スキル
    ├── marp-slides/       # スライド作成スキル
    ├── note-taking/       # メモ管理スキル
    ├── notion-manager/    # Notion連携スキル
    ├── podcast/           # ポッドキャストスキル
    ├── skill-creator/     # スキル作成スキル
    ├── tech-news-curation/# テックニューススキル
    ├── transcriber/       # 文字起こしスキル
    ├── workspace-rag/     # ワークスペース検索スキル
    ├── xangi-settings/    # xangi設定変更スキル
    └── youtube-notes/     # YouTubeノートスキル
```

## 使い方のヒント

### メモを取る
```
「調査結果をまとめて」
「会議メモを保存して」
「最近のメモ教えて」
```

### 日記を書く
```
「今日の日記を書いて」
「日記の時間」
```

### 猫日記をつける
```
[猫の画像を送信]
→ 自動で猫を検出してNotionに記録

「今週の猫ベストショット」
```

### プレゼン資料を作る
```
「AIの歴史について5枚のスライドを作って」
「このメモからプレゼン資料を作って」
```

### GitHubリポジトリを分析する
```
「このリポジトリ分析して: owner/repo」
「https://github.com/owner/repo を見て」
```

### ポッドキャストを聴く
```
「ポッドキャストの最新回をまとめて」
```

### テックニュースをチェック
```
「今日のテックニュースを教えて」
```

### カレンダーを確認する
```
「今日の予定」
「今週のスケジュール確認」
```

### 健康管理
```
「食事を記録して: ラーメン」
「今週の健康レポート」
```

### 自分だけのスキルを作る
```
「読書メモを管理するスキルを作って」
```

## カスタマイズ

### AIの性格を変える

`AGENTS.md` の「自分について」セクションを編集すると、AIの話し方や性格を変えられます。

### スキルを追加する

`skills/` ディレクトリにフォルダを作り、`SKILL.md` を書くだけで新しいスキルを追加できます。詳しくは `skills/README.md` を参照してください。

## ライセンス

MIT License
