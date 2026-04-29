#!/bin/bash
# Workspace RAG trigger
# Subcommands: start / index / health / <query>

set -uo pipefail

# WORKSPACE はリポジトリのルートを指す。
# 環境変数 WORKSPACE_PATH があれば優先、なければスクリプト位置から推定。
WORKSPACE="${WORKSPACE_PATH:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
SCRIPT_DIR="${WORKSPACE}/skills/workspace-rag/scripts"
PORT="${WORKSPACE_RAG_PORT:-7891}"
RUNTIME_DIR="${WORKSPACE}/.workspace_rag"
PID_FILE="${RUNTIME_DIR}/server.pid"
LOG_FILE="${RUNTIME_DIR}/server.log"
INDEX_LOG="${RUNTIME_DIR}/index.log"

mkdir -p "${RUNTIME_DIR}"

is_running() {
  curl -s --max-time 2 "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1
}

start_server() {
  if is_running; then
    echo "RAGサーバーはすでに起動中です（port ${PORT}）"
    return 0
  fi
  if [ ! -d "$SCRIPT_DIR" ]; then
    echo "workspace-ragスキルが見つかりません: $SCRIPT_DIR"
    return 1
  fi
  cd "$SCRIPT_DIR" || return 1
  nohup uv run python workspace_rag_server.py -w "$WORKSPACE" -p "$PORT" \
    >> "$LOG_FILE" 2>&1 &
  echo $! > "$PID_FILE"
  for _ in $(seq 1 15); do
    sleep 1
    if is_running; then
      echo "RAGサーバー起動完了（port ${PORT}, PID $(cat "$PID_FILE")）"
      return 0
    fi
  done
  echo "起動を待ちましたがヘルスチェックに応答しません。ログ: $LOG_FILE"
  return 1
}

start_index() {
  if pgrep -f "workspace_rag.py index -w $WORKSPACE" >/dev/null 2>&1; then
    echo "インデックス作成はすでに実行中です。進捗: tail -f $INDEX_LOG"
    return 0
  fi
  if [ ! -d "$SCRIPT_DIR" ]; then
    echo "workspace-ragスキルが見つかりません: $SCRIPT_DIR"
    return 1
  fi
  cd "$SCRIPT_DIR" || return 1
  nohup uv run python workspace_rag.py index -w "$WORKSPACE" \
    > "$INDEX_LOG" 2>&1 &
  echo "インデックス作成をバックグラウンドで開始しました（PID $!）"
  echo "進捗: tail -f $INDEX_LOG"
}

health_check() {
  if is_running; then
    curl -s --max-time 5 "http://127.0.0.1:${PORT}/health" 2>/dev/null \
      || echo "ヘルスチェックの取得に失敗しました"
  else
    echo "RAGサーバーは起動していません（port ${PORT}）。\`bash triggers/rag/handler.sh start\` で起動してください"
  fi
}

do_search() {
  local query="$*"
  if ! is_running; then
    echo "RAGサーバーが起動していません。\`bash triggers/rag/handler.sh start\` で起動してください"
    return 1
  fi
  local encoded
  encoded=$(python3 -c "import urllib.parse,sys;print(urllib.parse.quote(sys.argv[1]))" "$query" 2>/dev/null)
  RESULT=$(curl -s --max-time 10 "http://127.0.0.1:${PORT}/search?q=${encoded}&k=5" 2>/dev/null)
  if [ -z "$RESULT" ]; then
    echo "検索に失敗しました"
    return 1
  fi
  echo "$RESULT" | python3 -c "
import sys, json
data = json.load(sys.stdin)
results = data.get('results', [])
if not results:
    print('該当する結果がありませんでした')
else:
    elapsed = data.get('elapsed_ms', 0)
    print(f'検索結果: {len(results)}件 ({elapsed:.0f}ms)\n')
    for r in results:
        score = r.get('score', 0)
        path = r.get('file_path', '')
        content = r.get('content', '')[:150].replace('\n', ' ')
        print(f'- **{path}** (score: {score:.2f})')
        print(f'  {content}...\n')
" 2>/dev/null || echo "検索結果の解析に失敗しました"
}

show_help() {
  cat <<EOF
ワークスペースRAG（port ${PORT}）

使い方:
  start         サーバー起動（起動済みならスキップ）
  index         インデックス作成（バックグラウンド、初回は数十分〜）
  health        サーバーの稼働状況・統計を表示
  <検索クエリ>  検索（サーバー起動済みが前提）

例:
  bash triggers/rag/handler.sh start
  bash triggers/rag/handler.sh AIエージェント
EOF
}

case "${1:-}" in
  ""|help|-h|--help)
    show_help
    ;;
  start)
    start_server
    ;;
  index)
    start_index
    ;;
  health)
    health_check
    ;;
  *)
    do_search "$@"
    ;;
esac
