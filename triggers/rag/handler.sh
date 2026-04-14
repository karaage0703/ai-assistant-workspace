#!/bin/bash
QUERY="${*:-}"
if [ -z "$QUERY" ]; then
  echo "使い方: !rag <検索クエリ>"
  exit 0
fi

PORT="${WORKSPACE_RAG_PORT:-7891}"

RESULT=$(curl -s "http://127.0.0.1:${PORT}/search?q=$(python3 -c "import urllib.parse; print(urllib.parse.quote('$QUERY'))")&k=5" 2>/dev/null)

if [ -z "$RESULT" ]; then
  echo "workspace-ragサーバーが起動していません（port ${PORT}）"
  exit 1
fi

echo "$RESULT" | python3 -c "
import sys, json
data = json.load(sys.stdin)
results = data.get('results', [])
if not results:
    print('該当する結果がありませんでした')
else:
    print(f'検索結果: {len(results)}件 ({data.get(\"elapsed_ms\", 0):.0f}ms)\n')
    for r in results:
        score = r.get('score', 0)
        path = r.get('file_path', '')
        content = r.get('content', '')[:150].replace('\n', ' ')
        print(f'- **{path}** (score: {score})')
        print(f'  {content}...\n')
" 2>/dev/null || echo "検索結果の解析に失敗しました"
