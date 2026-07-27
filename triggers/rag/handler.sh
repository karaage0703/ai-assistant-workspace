#!/bin/bash
# Workspace RAG trigger
# Subcommands: start / index / health / <query>

set -uo pipefail

# WORKSPACE はリポジトリのルートを指す。
# 環境変数 WORKSPACE_PATH があれば優先、なければスクリプト位置から推定。
WORKSPACE="${WORKSPACE_PATH:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
RAG_SCRIPT_DIR="${WORKSPACE}/skills/xs-workspace-rag/scripts"
PORT="${WORKSPACE_RAG_PORT:-7890}"
RUNTIME_DIR="${WORKSPACE}/.workspace_rag"
PID_FILE="${RUNTIME_DIR}/server.pid"
LOG_FILE="${RUNTIME_DIR}/server.log"
INDEX_LOG="${RUNTIME_DIR}/index.log"
INDEX_PID_FILE="${RUNTIME_DIR}/index.pid"
INDEX_EXIT_FILE="${RUNTIME_DIR}/index.exit"

mkdir -p "${RUNTIME_DIR}"

get_health() {
  curl -fsS --connect-timeout 1 --max-time 3 \
    "http://127.0.0.1:${PORT}/health" 2>/dev/null
}

is_valid_health() {
  python3 -c '
import json
import sys

try:
    data = json.load(sys.stdin)
except (json.JSONDecodeError, TypeError):
    raise SystemExit(1)

raise SystemExit(
    0
    if isinstance(data, dict)
    and data.get("status") == "ok"
    and data.get("service") == "workspace-rag"
    and data.get("api_version") == 1
    else 1
)
' >/dev/null 2>&1
}

is_running() {
  local health
  health="$(get_health)" || return 1
  is_valid_health <<< "$health"
}

start_server() {
  if is_running; then
    echo "RAGサーバーはすでに起動中です（port ${PORT}）"
    return 0
  fi
  if [ ! -d "$RAG_SCRIPT_DIR" ]; then
    echo "workspace-ragスキルが見つかりません: $RAG_SCRIPT_DIR"
    return 1
  fi
  cd "$RAG_SCRIPT_DIR" || return 1
  if command -v setsid >/dev/null 2>&1; then
    setsid uv run python workspace_rag_server.py -w "$WORKSPACE" -p "$PORT" \
      >> "$LOG_FILE" 2>&1 < /dev/null &
  else
    nohup uv run python workspace_rag_server.py -w "$WORKSPACE" -p "$PORT" \
      >> "$LOG_FILE" 2>&1 < /dev/null &
  fi
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
  if [ ! -d "$RAG_SCRIPT_DIR" ]; then
    echo "workspace-ragスキルが見つかりません: $RAG_SCRIPT_DIR"
    return 1
  fi
  rm -f "$INDEX_EXIT_FILE"
  if command -v setsid >/dev/null 2>&1; then
    DETACH_COMMAND=(setsid)
  else
    DETACH_COMMAND=(nohup)
  fi
  "${DETACH_COMMAND[@]}" bash -lc '
    script_dir="$1"
    workspace="$2"
    log_file="$3"
    exit_file="$4"
    cd "$script_dir" || exit 1
    uv run python workspace_rag.py index -w "$workspace" > "$log_file" 2>&1
    rc=$?
    echo "$rc" > "$exit_file"
    exit "$rc"
  ' bash "$RAG_SCRIPT_DIR" "$WORKSPACE" "$INDEX_LOG" "$INDEX_EXIT_FILE" >/dev/null 2>&1 < /dev/null &
  echo $! > "$INDEX_PID_FILE"
  sleep 1
  if ! kill -0 "$(cat "$INDEX_PID_FILE")" 2>/dev/null && [ ! -f "$INDEX_EXIT_FILE" ]; then
    echo "インデックス作成を開始できませんでした。ログ: $INDEX_LOG"
    return 1
  fi
  echo "インデックス作成をバックグラウンドで開始しました（PID $(cat "$INDEX_PID_FILE")）"
  echo "進捗: tail -f $INDEX_LOG"
  echo "終了状態: cat $INDEX_EXIT_FILE"
  if [ "${DETACH_COMMAND[0]}" = "nohup" ]; then
    echo "setsidがないためnohup fallbackを使用しました。永続運用にはservice managerを使ってください"
  fi
  echo "このtrigger単体では完了通知しません。上の終了状態を確認してください"
}

health_check() {
  local health
  health="$(get_health)" || {
    echo "RAGサーバーは起動していません（port ${PORT}）。\`bash triggers/rag/handler.sh start\` で起動してください"
    return 1
  }
  if ! is_valid_health <<< "$health"; then
    echo "port ${PORT}の応答はworkspace-RAGサーバーではありません"
    return 1
  fi
  printf '%s\n' "$health"
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
