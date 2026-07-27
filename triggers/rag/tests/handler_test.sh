#!/usr/bin/env bash
set -euo pipefail

TRIGGER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TEST_TMP="$(mktemp -d)"
trap 'rm -rf "$TEST_TMP"' EXIT

FAKE_BIN="$TEST_TMP/bin"
mkdir -p "$FAKE_BIN"

cat > "$FAKE_BIN/curl" <<'EOF'
#!/usr/bin/env bash
case "${FAKE_CURL_MODE:-down}" in
  down)
    exit 7
    ;;
  healthy)
    printf '{"status":"ok","service":"workspace-rag","api_version":1}\n'
    ;;
  malformed)
    printf '<html>not rag</html>\n'
    ;;
  starting)
    printf '{"status":"starting"}\n'
    ;;
esac
EOF
chmod +x "$FAKE_BIN/curl"

if PATH="$FAKE_BIN:/usr/bin:/bin" FAKE_CURL_MODE=down \
  WORKSPACE_PATH="$(cd "$TRIGGER_DIR/../.." && pwd)" \
  WORKSPACE_RAG_PORT=9999 bash "$TRIGGER_DIR/handler.sh" health \
  > "$TEST_TMP/down.out" 2>&1; then
  echo "FAIL: unavailable health returned success" >&2
  exit 1
fi
grep -q '起動していません' "$TEST_TMP/down.out"

PATH="$FAKE_BIN:/usr/bin:/bin" FAKE_CURL_MODE=healthy \
  WORKSPACE_PATH="$(cd "$TRIGGER_DIR/../.." && pwd)" \
  WORKSPACE_RAG_PORT=9999 bash "$TRIGGER_DIR/handler.sh" health \
  > "$TEST_TMP/healthy.out" 2>&1
grep -q '"status":"ok"' "$TEST_TMP/healthy.out"
grep -q '"service":"workspace-rag"' "$TEST_TMP/healthy.out"

for mode in malformed starting; do
  if PATH="$FAKE_BIN:/usr/bin:/bin" FAKE_CURL_MODE="$mode" \
    WORKSPACE_PATH="$(cd "$TRIGGER_DIR/../.." && pwd)" \
    WORKSPACE_RAG_PORT=9999 bash "$TRIGGER_DIR/handler.sh" health \
    > "$TEST_TMP/$mode.out" 2>&1; then
    echo "FAIL: $mode health response returned success" >&2
    exit 1
  fi
done

echo "rag handler tests: PASS"
