#!/bin/bash
# spontaneous-talk 確率判定スクリプト
# 発話すべきなら "SPEAK" を出力、しないなら "NO_SPEAK" を出力して終了
# 内部判定の詳細は一切出力しない

STATE_FILE="${1:-$(dirname "$0")/../../../memory/spontaneous-talk-state.json}"
SPEAK_PROBABILITY=20
MIN_INTERVAL_MINUTES=60
# QUIET_START / QUIET_END: "none" で無効、"HH:MM" で有効
QUIET_START="23:00"
QUIET_END="08:00"

# 現在時刻
NOW_EPOCH=$(date +%s)
NOW_HOUR=$(date +%H)
NOW_MIN=$(date +%M)

# 静穏時間チェック
if [ "$QUIET_START" != "none" ] && [ "$QUIET_END" != "none" ]; then
    QS_H=${QUIET_START%%:*}
    QS_M=${QUIET_START##*:}
    QE_H=${QUIET_END%%:*}
    QE_M=${QUIET_END##*:}
    NOW_TOTAL=$((10#$NOW_HOUR * 60 + 10#$NOW_MIN))
    QS_TOTAL=$((10#$QS_H * 60 + 10#$QS_M))
    QE_TOTAL=$((10#$QE_H * 60 + 10#$QE_M))

    if [ $QS_TOTAL -le $QE_TOTAL ]; then
        # 同日内（例: 09:00-17:00）
        if [ $NOW_TOTAL -ge $QS_TOTAL ] && [ $NOW_TOTAL -lt $QE_TOTAL ]; then
            echo "NO_SPEAK"
            exit 0
        fi
    else
        # 日跨ぎ（例: 23:00-08:00）
        if [ $NOW_TOTAL -ge $QS_TOTAL ] || [ $NOW_TOTAL -lt $QE_TOTAL ]; then
            echo "NO_SPEAK"
            exit 0
        fi
    fi
fi

# 前回発話時刻チェック
if [ -f "$STATE_FILE" ]; then
    LAST_SPOKE=$(python3 -c "
import json, sys
try:
    with open('$STATE_FILE') as f:
        data = json.load(f)
    print(data.get('lastSpoke', ''))
except:
    print('')
" 2>/dev/null)

    if [ -n "$LAST_SPOKE" ]; then
        # ISO 8601 → epoch
        LAST_EPOCH=$(date -d "$LAST_SPOKE" +%s 2>/dev/null)
        if [ -n "$LAST_EPOCH" ]; then
            DIFF_SEC=$((NOW_EPOCH - LAST_EPOCH))
            DIFF_MIN=$((DIFF_SEC / 60))
            if [ $DIFF_MIN -lt $MIN_INTERVAL_MINUTES ]; then
                echo "NO_SPEAK"
                exit 0
            fi
        fi
    fi
fi

# 確率判定
RAND=$((RANDOM % 100))
if [ $RAND -ge $SPEAK_PROBABILITY ]; then
    echo "NO_SPEAK"
    exit 0
fi

echo "SPEAK"
