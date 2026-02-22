# スキル一覧

スキルは `skills/` ディレクトリに格納されたAIの拡張機能です。各スキルには `SKILL.md` が含まれ、AIが自動的に読み込みます。

## 利用可能なスキル

| スキル | 説明 | トリガー |
|--------|------|----------|
| **cat-diary** | 猫の写真を自動判定して猫日記を作成 | 「猫日記」「猫の写真を記録して」 |
| **marp-slides** | Marpでプレゼンスライドを作成 | 「スライド作って」「プレゼン資料を作って」 |
| **notion-manager** | Notion APIでページの検索・作成・ファイルアップロード | 「Notionで検索して」「Notionにページ作って」 |
| **podcast** | ポッドキャストの取得・文字起こし・まとめ | 「ポッドキャストまとめて」 |
| **skill-creator** | 新しいスキルを作成する | 「スキルを作って」 |
| **tech-news-curation** | AI・技術系の最新ニュースを取得 | 「テックニュース」「最新のニュース教えて」 |
| **transcriber** | 音声ファイルをWhisperで文字起こし | 「文字起こしして」「音声をテキストに」 |
| **workspace-rag** | ワークスペース全体をベクトル検索 | 「ワークスペース検索して」「RAGで探して」 |
| **xangi-settings** | xangiの設定をチャットから動的に変更 | 「設定確認して」「タイムアウト変えて」 |
| **health-advisor** | 食事・運動の記録と健康管理アドバイス | 「健康チェック」「食事記録して」「運動記録して」 |
| **youtube-notes** | YouTube動画の字幕からノートを作成 | 「YouTube動画をまとめて」 |
| **calendar** | ICSカレンダー予定確認＋画像からの予定追加 | 「今日の予定」「明日の予定」「スケジュール確認」 |

## SKILL.mdの書き方

各スキルのディレクトリに `SKILL.md` を作成します。先頭にYAMLフロントマターで `name` と `description` を記述してください。

```markdown
---
name: skill-name
description: 何をするスキルか。「呼び出しフレーズ」で使用。
---

# スキル名

## 手順

### Step 1: ...
```

`description` はAIがスキルを選択する際の判断材料になるので、具体的に書いてください。

## AIツール用シンボリックリンク

スキル本体は `skills/` に一元管理。各AIツールの設定ディレクトリにシンボリックリンクを張ることで、どのツールからも同じスキルが使えます。

```
~/.claude/skills → <ワークスペース>/skills/   # Claude Code 用
~/.agents/skills → <ワークスペース>/skills/   # Codex CLI 用
~/.gemini/skills → <ワークスペース>/skills/   # Gemini CLI 用
```

セットアップ方法:

```bash
# Claude Code 用
mkdir -p ~/.claude
ln -sf "$(pwd)/skills" ~/.claude/skills

# Codex CLI 用
mkdir -p ~/.agents
ln -sf "$(pwd)/skills" ~/.agents/skills

# Gemini CLI 用
mkdir -p ~/.gemini
ln -sf "$(pwd)/skills" ~/.gemini/skills
```

スキルを追加する時は `skills/` にフォルダを作るだけで、全ツールから自動的に利用できます。
