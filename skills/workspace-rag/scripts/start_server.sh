#!/bin/bash
# Workspace RAG Server 起動スクリプト
# 使い方: ./start_server.sh [workspace_path]

set -euo pipefail

# デフォルトはスクリプトの3階層上（skills/workspace-rag/scripts/ → ワークスペースルート）
WORKSPACE="${1:-$(cd "$(dirname "$0")/../../.." && pwd)}"
PORT="${WORKSPACE_RAG_PORT:-7890}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PID_FILE="${WORKSPACE}/.workspace_rag/server.pid"
LOG_FILE="${WORKSPACE}/.workspace_rag/server.log"

# 既に起動中ならスキップ
if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if kill -0 "$PID" 2>/dev/null; then
        echo "Workspace RAG Server already running (PID: $PID)"
        exit 0
    else
        echo "Stale PID file found, removing..."
        rm -f "$PID_FILE"
    fi
fi

# ポートが使用中ならスキップ
if ss -tlnp 2>/dev/null | grep -q ":${PORT} "; then
    echo "Port ${PORT} already in use"
    exit 0
fi

# ログディレクトリ確認
mkdir -p "$(dirname "$LOG_FILE")"

echo "Starting Workspace RAG Server on port ${PORT}..."
cd "$SCRIPT_DIR"
nohup uv run python workspace_rag_server.py \
    -w "$WORKSPACE" -p "$PORT" \
    >> "$LOG_FILE" 2>&1 &

echo "PID: $!"
echo "Log: $LOG_FILE"
echo "Health: curl http://127.0.0.1:${PORT}/health"
