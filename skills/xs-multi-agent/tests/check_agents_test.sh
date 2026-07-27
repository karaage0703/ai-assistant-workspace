#!/usr/bin/env bash
set -euo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TEST_TMP="$(mktemp -d)"
trap 'rm -rf "$TEST_TMP"' EXIT

FAKE_BIN="$TEST_TMP/bin"
mkdir -p "$FAKE_BIN"

cat > "$FAKE_BIN/grok" <<'EOF'
#!/usr/bin/env bash
if [[ "${1:-}" == "--version" ]]; then
  printf 'grok test\n'
  exit 0
fi
if [[ "${FAKE_GROK_MODE:-failure}" == "success" ]]; then
  workspace=""
  while (($#)); do
    if [[ "$1" == "--cwd" ]]; then
      workspace="$2"
      break
    fi
    shift
  done
  cat "$workspace/skills/xs-multi-agent/.smoke-token"
  exit 0
fi
if [[ "${FAKE_GROK_MODE:-failure}" == "echo" ]]; then
  printf 'prompt described a smoke token but the agent did not read the file\n'
  exit 0
fi
printf '\033[31mERROR\033[0m failed to watch root: Error { kind: MaxFilesWatch }\n'
EOF
chmod +x "$FAKE_BIN/grok"

for command_name in codex claude cursor-agent agy antigravity; do
  ln -s /bin/false "$FAKE_BIN/$command_name"
done

CONFIG_PATH="$TEST_TMP/agents.json"
PATH="$FAKE_BIN:/usr/bin:/bin" \
  MULTI_AGENT_CONFIG="$CONFIG_PATH" \
  STATE_DIR="$TEST_TMP/state" \
  WORKSPACE_PATH="$TEST_TMP/workspace" \
  bash "$SKILL_DIR/scripts/check_agents.sh" >/dev/null

jq empty "$CONFIG_PATH"
jq -e '.agents[] | select(.id == "grok" and .ready == false)' "$CONFIG_PATH" >/dev/null
jq -er '.agents[] | select(.id == "grok") | .notes' "$CONFIG_PATH" | grep -q 'MaxFilesWatch'

PATH="$FAKE_BIN:/usr/bin:/bin" \
  FAKE_GROK_MODE=success \
  MULTI_AGENT_CONFIG="$CONFIG_PATH" \
  STATE_DIR="$TEST_TMP/state" \
  WORKSPACE_PATH="$TEST_TMP/workspace" \
  bash "$SKILL_DIR/scripts/check_agents.sh" >/dev/null

jq -e '.schema_version == 2' "$CONFIG_PATH" >/dev/null
jq -e '.agents[] | select(.id == "grok" and .ready == true and .provider_family == "xai")' "$CONFIG_PATH" >/dev/null

PATH="$FAKE_BIN:/usr/bin:/bin" \
  FAKE_GROK_MODE=success \
  MULTI_AGENT_ANTIGRAVITY_MODEL=claude-sonnet \
  MULTI_AGENT_CONFIG="$CONFIG_PATH" \
  STATE_DIR="$TEST_TMP/state" \
  WORKSPACE_PATH="$TEST_TMP/workspace" \
  bash "$SKILL_DIR/scripts/check_agents.sh" >/dev/null

jq -e '.agents[] | select(.id == "antigravity" and .provider_family == "unknown")' "$CONFIG_PATH" >/dev/null

PATH="$FAKE_BIN:/usr/bin:/bin" \
  FAKE_GROK_MODE=echo \
  MULTI_AGENT_CONFIG="$CONFIG_PATH" \
  STATE_DIR="$TEST_TMP/state" \
  WORKSPACE_PATH="$TEST_TMP/workspace" \
  bash "$SKILL_DIR/scripts/check_agents.sh" >/dev/null

jq -e '.agents[] | select(.id == "grok" and .ready == false)' "$CONFIG_PATH" >/dev/null

echo "check_agents tests: PASS"
