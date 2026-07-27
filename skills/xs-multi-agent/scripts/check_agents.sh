#!/usr/bin/env bash
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE="${WORKSPACE_PATH:-$(cd "$SCRIPT_DIR/../../.." && pwd)}"
STATE_DIR="${STATE_DIR:-${WORKSPACE_PATH:-$HOME}/.xangi}"
CONFIG_PATH="${MULTI_AGENT_CONFIG:-$STATE_DIR/multi-agent/agents.json}"
SMOKE=true
READY_AGENTS=""
USABLE_AGENTS=""

for arg in "$@"; do
  case "$arg" in
    --smoke) SMOKE=true ;;
    --no-smoke) SMOKE=false ;;
    -h|--help)
      cat <<'EOF'
Usage: check_agents.sh [--smoke|--no-smoke]

Creates or updates $STATE_DIR/multi-agent/agents.json.

Default runs a tiny prompt for each installed external agent, so it can catch
login/quota/runtime failures and save ready/usable agents.
--no-smoke checks command presence and version only.
EOF
      exit 0
      ;;
    *)
      echo "unknown option: $arg" >&2
      exit 2
      ;;
  esac
done

mkdir -p "$(dirname "$CONFIG_PATH")"

json_escape() {
  local s="${1-}"
  s="${s//\\/\\\\}"
  s="${s//\"/\\\"}"
  s="${s//$'\033'/\\u001b}"
  s="${s//$'\b'/\\b}"
  s="${s//$'\f'/\\f}"
  s="${s//$'\n'/\\n}"
  s="${s//$'\r'/\\r}"
  s="${s//$'\t'/\\t}"
  printf '%s' "$s"
}

first_command() {
  local candidate
  for candidate in "$@"; do
    if command -v "$candidate" >/dev/null 2>&1; then
      command -v "$candidate"
      return 0
    fi
  done
  return 1
}

version_of() {
  local cmd="$1"
  local version_arg="${2:---version}"
  timeout 5s "$cmd" "$version_arg" 2>&1 | head -1 | tr -d '\r' || true
}

append_json_string() {
  local var_name="$1"
  local value="$2"
  local current="${!var_name}"
  local escaped
  escaped="$(json_escape "$value")"
  if [[ -n "$current" ]]; then
    printf -v "$var_name" '%s, "%s"' "$current" "$escaped"
  else
    printf -v "$var_name" '"%s"' "$escaped"
  fi
}

agent_json() {
  local id="$1"
  local name="$2"
  local available="$3"
  local ready="$4"
  local recommended="$5"
  local command_path="$6"
  local version="$7"
  local invocation="$8"
  local status="$9"
  local notes="${10}"
  local scope="${11:-persistent_cli}"
  local volatile="${12:-false}"
  local include_in_sets="${13:-true}"
  local provider_family="${14:-unknown}"

  if [[ "$include_in_sets" == true && "$ready" == true ]]; then
    append_json_string READY_AGENTS "$id"
    if [[ "$recommended" == true ]]; then
      append_json_string USABLE_AGENTS "$id"
    fi
  fi

  cat <<EOF
    {
      "id": "$(json_escape "$id")",
      "name": "$(json_escape "$name")",
      "available": $available,
      "ready": $ready,
      "recommended": $recommended,
      "command": "$(json_escape "$command_path")",
      "version": "$(json_escape "$version")",
      "invocation": "$(json_escape "$invocation")",
      "status": "$(json_escape "$status")",
      "provider_family": "$(json_escape "$provider_family")",
      "scope": "$(json_escape "$scope")",
      "volatile": $volatile,
      "notes": "$(json_escape "$notes")"
    }
EOF
}

smoke_agent() {
  local id="$1"
  local prompt_file
  local smoke_workspace
  prompt_file="$(mktemp)"
  smoke_workspace="$(mktemp -d)"
  mkdir -p "$smoke_workspace/skills/xs-multi-agent"
  cp "$SCRIPT_DIR/../SKILL.md" "$smoke_workspace/skills/xs-multi-agent/SKILL.md"
  local smoke_token
  smoke_token="CHECK_AGENTS_$(od -An -N16 -tx1 /dev/urandom | tr -d '[:space:]')"
  printf '%s\n' "$smoke_token" > "$smoke_workspace/skills/xs-multi-agent/.smoke-token"
  printf 'ワークスペース内の skills/xs-multi-agent/.smoke-token を読み、その内容だけを1行で返してください。読めない場合は FAIL と返してください。\n' > "$prompt_file"
  local output
  local rc=0
  output="$(timeout 60s "$SCRIPT_DIR/run_agent.sh" "$id" "$prompt_file" "$smoke_workspace" 2>&1)" || rc=$?
  rm -f "$prompt_file"
  rm -rf "$smoke_workspace"
  local compact_output
  compact_output="$(printf '%s' "$output" | tr -d '[:space:]')"
  if [[ "$rc" -eq 0 && "$compact_output" == "$smoke_token" ]]; then
    printf 'ok'
  else
    output="$(printf '%s' "$output" | tail -5 | tr '\n' ' ' | cut -c 1-240)"
    printf 'fail:%s' "$output"
  fi
}

probe() {
  local id="$1"
  local name="$2"
  local candidates_csv="$3"
  local version_arg="$4"
  local recommended_if_found="$5"
  local invocation="$6"
  local status_if_found="$7"
  local notes_if_found="$8"
  local missing_notes="$9"
  local provider_family="${10:-unknown}"

  local old_ifs="$IFS"
  IFS=','
  read -r -a candidates <<< "$candidates_csv"
  IFS="$old_ifs"

  local cmd_path=""
  if cmd_path="$(first_command "${candidates[@]}")"; then
    local version
    version="$(version_of "$cmd_path" "$version_arg")"
    local ready="null"
    local recommended="$recommended_if_found"
    local status="$status_if_found"
    local notes="$notes_if_found"
    if [[ "$SMOKE" == true ]]; then
      local smoke
      smoke="$(smoke_agent "$id")"
      if [[ "$smoke" == ok ]]; then
        ready=true
        notes="$notes Smoke probe passed."
      else
        ready=false
        recommended=false
        status="limited"
        notes="$notes Smoke probe failed: ${smoke#fail:}"
      fi
    fi
    agent_json "$id" "$name" true "$ready" "$recommended" "$cmd_path" "$version" "$invocation" "$status" "$notes" \
      "persistent_cli" false true "$provider_family"
  else
    agent_json "$id" "$name" false false false "" "" "$invocation" "missing" "$missing_notes" \
      "persistent_cli" false true "$provider_family"
  fi
}

generated_at="$(date -Iseconds)"
host="$(hostname 2>/dev/null || echo unknown)"

tmp="$(mktemp)"
{
  cat <<EOF
{
  "schema_version": 2,
  "generated_at": "$(json_escape "$generated_at")",
  "workspace": "$(json_escape "$WORKSPACE")",
  "state_dir": "$(json_escape "$STATE_DIR")",
  "host": "$(json_escape "$host")",
  "smoke_checked": $SMOKE,
  "agents": [
EOF

  agent_json \
    "self" \
    "Current AI session" \
    true \
    true \
    true \
    "" \
    "" \
    "answer directly in the current turn" \
    "available" \
    "Always available in the current turn only. Use as coordinator and final integrator, but do not persist as an external usable agent." \
    "current_turn" \
    true \
    false \
    "current-session"

  printf ',\n'
  probe "codex" "Codex CLI" "codex" "--version" true \
    "codex exec --skip-git-repo-check --sandbox read-only --cd <workspace> - < <prompt-file>" \
    "available" \
    "Strong for code review, design, debugging, and implementation planning." \
    "codex command not found" \
    "openai"

  printf ',\n'
  probe "claude" "Claude Code" "claude" "--version" true \
    "cd <target-workspace> && claude -p <prompt> --safe-mode --tools/--allowedTools Read,Glob,Grep,WebFetch,WebSearch --permission-mode dontAsk [--max-budget-usd <usd>]" \
    "available" \
    "Good for broad reasoning, writing, and code review. Watch quota and avoid recursive long jobs." \
    "claude command not found" \
    "anthropic"

  printf ',\n'
  probe "grok" "Grok CLI" "grok" "--version" true \
    "grok -p <prompt> --cwd <workspace> --permission-mode plan --no-memory --no-subagents --tools Read,Glob,Grep,WebFetch,WebSearch --output-format plain" \
    "available" \
    "Useful as another coding/reasoning perspective. Prefer plan mode unless edits are explicitly delegated." \
    "grok command not found" \
    "xai"

  printf ',\n'
  probe "cursor" "Cursor Agent" "cursor-agent" "--version" true \
    "cursor-agent --print --mode=ask --workspace <workspace> <prompt>" \
    "available" \
    "Good for codebase Q&A and plan-mode review. Use ask/plan mode by default." \
    "cursor-agent command not found" \
    "unknown"

  printf ',\n'
  antigravity_model="${MULTI_AGENT_ANTIGRAVITY_MODEL:-gemini-3.1-pro-low}"
  antigravity_family="unknown"
  if [[ "$antigravity_model" == gemini-* ]]; then
    antigravity_family="google"
  fi
  probe "antigravity" "Antigravity CLI" "agy,antigravity" "--version" true \
    "agy -p <prompt> --model ${antigravity_model} --mode plan --sandbox" \
    "available" \
    "Use when smoke probe passes. Empty stdout and quota errors are treated as failures." \
    "agy/antigravity command not found" \
    "$antigravity_family"

  cat <<EOF
  ],
  "ready_agents": [$READY_AGENTS],
  "usable_agents": [$USABLE_AGENTS]
}
EOF
} > "$tmp"

if ! jq empty "$tmp" >/dev/null 2>&1; then
  printf 'generated agents config is invalid JSON; refusing to replace %s\n' "$CONFIG_PATH" >&2
  rm -f "$tmp"
  exit 70
fi

mv "$tmp" "$CONFIG_PATH"
printf '%s\n' "$CONFIG_PATH"
