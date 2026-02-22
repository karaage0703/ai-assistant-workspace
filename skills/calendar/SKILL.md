---
name: calendar
description: カレンダー予定を確認するスキル。ICS（Googleカレンダー等）と手動追加（画像読み取り）を統合。「今日の予定」「明日の予定」「カレンダー画像送って」「スケジュール確認」で使用。`/calendar` で発動。
---

# calendar スキル

ICSカレンダー（Googleカレンダー等）＋ 手動追加の予定（画像読み取り等）を統合して予定を確認する。

## セットアップ

`[SKILL_DIR]/calendar_urls.json` にICS URLを登録する：

```json
{
  "calendars": [
    {
      "name": "main",
      "url": "https://calendar.google.com/calendar/ical/xxxxx/basic.ics"
    },
    {
      "name": "family",
      "label": "家族",
      "url": "https://calendar.google.com/calendar/ical/yyyyy/basic.ics"
    }
  ]
}
```

- `name`: カレンダー識別名（必須）
- `url`: ICSのURL（必須）。Googleカレンダーの場合「設定 → カレンダーの統合 → iCal形式の非公開URL」
- `label`: 表示ラベル（任意）。設定すると予定に `[家族]` のようなタグが付く。共有カレンダーなど、自分の予定とは限らないものに付けると便利

## コマンド

```bash
cd [SKILL_DIR] && uv run python calendar_check.py [引数]
```

- `today` / 引数なし → 今日
- `tomorrow` → 明日
- `week` → 今後7日間
- `0 7` → 今日から7日間（範囲指定）
- `-7 0` → 過去7日間

## 画像からの予定追加

カレンダーのスクリーンショットが送られたら：

### Step 1: 画像を読み取る

添付画像を Read ツールで確認する。

### Step 2: 予定を抽出

画像から以下の情報を読み取る：
- 日付、開始時刻、終了時刻、予定名
- 終日予定かどうか

### Step 3: manual_events.json に保存

`[SKILL_DIR]/manual_events.json` に保存。既存の予定と**マージ**する（同じ日付の予定は上書き）。

```json
{
  "events": [
    {
      "date": "2026-03-01",
      "time_start": "09:00",
      "time_end": "10:00",
      "summary": "ミーティング",
      "all_day": false
    },
    {
      "date": "2026-03-01",
      "summary": "有給休暇",
      "all_day": true
    }
  ],
  "updated_at": "2026-03-01T12:00:00+09:00"
}
```

### 保存ルール

- 同じ日付の予定は**上書き**（最新の画像が正）
- `updated_at` を更新時刻に設定
- 過去の予定は放置OK（表示時にフィルタされる）

### Step 4: 再確認

保存後、`calendar_check.py` を再実行して反映を確認。

## チェックリスト（実行時に必ず確認）

- [ ] `calendar_urls.json` が存在するか（初回はセットアップを案内）
- [ ] 画像から予定を追加した場合、保存後に再実行して確認したか
- [ ] **🚨 共有カレンダーの予定を「あなたの予定」と断定しない**（labelで区別する）
