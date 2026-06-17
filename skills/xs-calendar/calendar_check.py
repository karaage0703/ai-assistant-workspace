#!/usr/bin/env python3
"""ICSカレンダーから予定を取得するスクリプト

使い方:
  python calendar_check.py              # 今日
  python calendar_check.py today        # 今日
  python calendar_check.py tomorrow     # 明日
  python calendar_check.py 3            # 3日後
  python calendar_check.py -1           # 昨日
  python calendar_check.py 0 7          # 今日から7日間
  python calendar_check.py week         # 今後7日間

設定:
  calendar_urls.json にICS URLを登録する（同ディレクトリ）
  manual_events.json に手動追加の予定を保存（画像読み取り等）
"""

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
from icalendar import Calendar

SKILL_DIR = Path(__file__).parent
CALENDAR_URLS_PATH = SKILL_DIR / "calendar_urls.json"
MANUAL_EVENTS_PATH = SKILL_DIR / "manual_events.json"
TZ = ZoneInfo("Asia/Tokyo")


def load_calendar_urls() -> list[dict]:
    """設定ファイルからカレンダーURLを読み込む"""
    if not CALENDAR_URLS_PATH.exists():
        print("エラー: calendar_urls.json が見つかりません", file=sys.stderr)
        print(f"  {CALENDAR_URLS_PATH} を作成してください", file=sys.stderr)
        sys.exit(1)

    with open(CALENDAR_URLS_PATH) as f:
        data = json.load(f)
    return data.get("calendars", [])


def load_manual_events(start_date: datetime, end_date: datetime) -> list[dict]:
    """手動追加の予定（manual_events.json）を読み込む"""
    if not MANUAL_EVENTS_PATH.exists():
        return []

    try:
        with open(MANUAL_EVENTS_PATH) as f:
            data = json.load(f)
    except (json.JSONDecodeError, IOError):
        return []

    events = []
    for e in data.get("events", []):
        try:
            event_date = datetime.strptime(e["date"], "%Y-%m-%d").date()
            if not (start_date.date() <= event_date < end_date.date()):
                continue

            is_all_day = e.get("all_day", False)
            if is_all_day:
                dt_start = datetime.combine(event_date, datetime.min.time(), tzinfo=TZ)
                dt_end = None
            else:
                time_start = datetime.strptime(e.get("time_start", "00:00"), "%H:%M").time()
                dt_start = datetime.combine(event_date, time_start, tzinfo=TZ)
                if e.get("time_end"):
                    time_end = datetime.strptime(e["time_end"], "%H:%M").time()
                    dt_end = datetime.combine(event_date, time_end, tzinfo=TZ)
                else:
                    dt_end = None

            events.append({
                "summary": e.get("summary", "（タイトルなし）"),
                "start": dt_start,
                "end": dt_end,
                "all_day": is_all_day,
                "source": "manual",
                "label": e.get("label", ""),
            })
        except (KeyError, ValueError) as err:
            print(f"警告: 手動予定のパースに失敗: {err}", file=sys.stderr)
            continue

    return events


def fetch_ics(url: str) -> str:
    """ICS URLからカレンダーデータを取得"""
    response = httpx.get(url, timeout=30)
    response.raise_for_status()
    return response.text


def parse_events(ics_text: str, start_date: datetime, end_date: datetime) -> list[dict]:
    """ICSデータをパースして指定期間のイベントを抽出"""
    cal = Calendar.from_ical(ics_text)
    events = []

    for component in cal.walk():
        if component.name != "VEVENT":
            continue

        dtstart = component.get("dtstart")
        dtend = component.get("dtend")
        summary = str(component.get("summary", "（タイトルなし）"))

        if dtstart is None:
            continue

        dt_start = dtstart.dt

        if isinstance(dt_start, datetime):
            dt_start = dt_start.astimezone(TZ)
            is_all_day = False
        else:
            dt_start = datetime.combine(dt_start, datetime.min.time(), tzinfo=TZ)
            is_all_day = True

        event_date = dt_start.date()
        if not (start_date.date() <= event_date < end_date.date()):
            continue

        dt_end = None
        if dtend:
            dt_e = dtend.dt
            if isinstance(dt_e, datetime):
                dt_end = dt_e.astimezone(TZ)
            else:
                dt_end = datetime.combine(dt_e, datetime.min.time(), tzinfo=TZ)

        events.append({
            "summary": summary,
            "start": dt_start,
            "end": dt_end,
            "all_day": is_all_day,
        })

    events.sort(key=lambda x: x["start"])
    return events


def format_event(event: dict) -> str:
    """イベントを表示用にフォーマット"""
    label = event.get("label", "")
    tag = f"[{label}] " if label else ""

    if event["all_day"]:
        return f"終日 {tag}{event['summary']}"

    start_str = event["start"].strftime("%H:%M")
    if event["end"]:
        end_str = event["end"].strftime("%H:%M")
        return f"{start_str}-{end_str} {tag}{event['summary']}"
    return f"{start_str} {tag}{event['summary']}"


def parse_args(args: list[str]) -> tuple[int, int]:
    """引数をパースして (開始日オフセット, 終了日オフセット) を返す"""
    if not args:
        return (0, 1)

    arg1 = args[0].lower()

    if arg1 == "today":
        return (0, 1)
    elif arg1 == "tomorrow":
        return (1, 2)
    elif arg1 == "yesterday":
        return (-1, 0)
    elif arg1 == "week":
        return (0, 7)
    elif arg1 == "lastweek":
        return (-7, 0)

    try:
        start_offset = int(arg1)
        if len(args) >= 2:
            end_offset = int(args[1])
        else:
            end_offset = start_offset + 1
        return (start_offset, end_offset)
    except ValueError:
        print(f"不明な引数: {arg1}", file=sys.stderr)
        sys.exit(1)


def main():
    args = sys.argv[1:]
    start_offset, end_offset = parse_args(args)

    now = datetime.now(TZ)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    start_date = today_start + timedelta(days=start_offset)
    end_date = today_start + timedelta(days=end_offset)

    # タイトル生成
    if start_offset == 0 and end_offset == 1:
        title = f"今日の予定 ({start_date.strftime('%Y-%m-%d')})"
    elif start_offset == 1 and end_offset == 2:
        title = f"明日の予定 ({start_date.strftime('%Y-%m-%d')})"
    elif start_offset == -1 and end_offset == 0:
        title = f"昨日の予定 ({start_date.strftime('%Y-%m-%d')})"
    elif end_offset - start_offset == 1:
        title = f"{start_date.strftime('%Y-%m-%d')} の予定"
    else:
        title = f"予定 ({start_date.strftime('%m/%d')} 〜 {(end_date - timedelta(days=1)).strftime('%m/%d')})"

    # ICSカレンダー取得
    calendars = load_calendar_urls()
    all_events = []

    for cal_info in calendars:
        try:
            ics_text = fetch_ics(cal_info["url"])
            events = parse_events(ics_text, start_date, end_date)
            label = cal_info.get("label", "")
            for e in events:
                e["source"] = cal_info["name"]
                e["label"] = label
            all_events.extend(events)
        except Exception as e:
            print(f"警告: {cal_info['name']} の取得に失敗: {e}", file=sys.stderr)

    # 手動追加の予定を取得
    manual_events = load_manual_events(start_date, end_date)
    all_events.extend(manual_events)

    # 重複除去＆ソート
    seen = set()
    unique_events = []
    for e in all_events:
        key = (e["summary"], e["start"])
        if key not in seen:
            seen.add(key)
            unique_events.append(e)

    unique_events.sort(key=lambda x: x["start"])

    # 出力
    print(f"📅 {title}")
    print()

    if not unique_events:
        print("予定はありません")
    else:
        current_date = None
        for event in unique_events:
            event_date = event["start"].date()
            if end_offset - start_offset > 1 and event_date != current_date:
                if current_date is not None:
                    print()
                weekday = ["月", "火", "水", "木", "金", "土", "日"][event_date.weekday()]
                print(f"**{event_date.strftime('%m/%d')} ({weekday})**")
                current_date = event_date
            print(f"  {format_event(event)}")


if __name__ == "__main__":
    main()
