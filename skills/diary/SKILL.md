---
name: diary
description: |
  日記スキル。日次の振り返りとNotion連携。
  「日記書いて」「日記の時間」「今日やったこと記録して」「diary」で発動。
  「日記」というワードが含まれたら必ずこのスキルを使うこと。memory/への追記だけで終わらせない。
---

# 毎日の日記記録スキル

1日を日記形式で記録する。notes/ + Notion の両方に残す。

## 絶対遵守事項

- **日常の出来事（食事・家族・ペット・散歩・仕事の感想）は必ず記録する**
- 日常セクションを開発作業セクションより**上に配置**する
- ファイル操作なしに「記録した」と報告しない（嘘禁止）
- 完了報告には**Notion日記のURL**を含める（Notion連携時）

## 保存先

| 場所 | 用途 |
|------|------|
| `notes/YYYYMMDD_diary.md` | 日記本体 |
| `memory/YYYYMMDD.md` | 参考資料（会話ログ・調べたこと） |
| **Notion日記DB**（任意） | 画像・動画付きリッチ版 |

## 手順

### Step 1: 情報収集

1. `memory/YYYYMMDD.md` を読む（その日の出来事・会話ログ）
2. `date -d "YYYY-MM-DD" +%A` で**曜日を確認**（思い込みで書かない）

### Step 2: notes/に日記作成

`notes/YYYYMMDD_diary.md` を作成。

### Step 3: Notion日記ページ作成（任意）

Notion連携が設定されている場合、`notion-manager` スキルの `notion_tool.py` を使って日記ページを作成。

```bash
cd skills/notion-manager

# ページ作成
uv run python notion_tool.py diary <DB_ID> -t "YYYYMMDD_タイトル" -d YYYY-MM-DD

# 見出し・本文を追加
uv run python notion_tool.py append <page_id> -H "今日の出来事"
uv run python notion_tool.py append <page_id> -b "内容..."

# 画像アップロード（キャプション付き）
uv run python notion_tool.py upload /path/to/photo.jpg <page_id> -c "キャプション"
```

### Step 4: 同期

```bash
git add notes/ memory/ && git commit -m "日記 YYYYMMDD" && git push
```

### Step 5: 完了報告

```
MM/DDの日記完了！

Notion日記: https://www.notion.so/xxx（Notion連携時）

やったこと：
- ...
```

## notes/ フォーマット

```markdown
---
tags: [diary]
---

# YYYYMMDD (曜日)

## タイムライン
- HH:MM 出来事

## 食事
- 朝:
- 昼:
- 夜:

## 気づき・学び

## 開発作業

## 気分・体調

## 明日の予定
```

**セクション順序**: 日常（タイムライン・食事） → 開発 → その他

## 日付ルール

- **0時〜朝5時の作業** → 前日の日記に記録（寝るまでが1日）

## 完了前チェックリスト

```
□ `date` コマンドで曜日を確認した
□ 日常セクションに食事・家族・ペット・散歩・仕事を記録した
□ 日常セクションが開発より上にある
□ memory/ にファイル操作で書き込んだ
□ 投稿文は日本語のみ、作業ログ混入なし
```
