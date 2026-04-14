#!/bin/bash
CITY="${1:-Tokyo}"
curl -s "wttr.in/${CITY}?format=3&lang=ja" 2>/dev/null || echo "天気情報の取得に失敗しました"
