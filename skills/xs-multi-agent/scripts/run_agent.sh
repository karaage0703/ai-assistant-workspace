#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE="${WORKSPACE_PATH:-$(cd "$SCRIPT_DIR/../../.." && pwd)}"

load_agent_env() {
  local env_file="${XANGI_ENV_FILE:-}"
  if [[ -z "$env_file" ]]; then
    if [[ -f "$WORKSPACE/.env" ]]; then
      env_file="$WORKSPACE/.env"
    elif [[ -f "$HOME/.xangi/.env" ]]; then
      env_file="$HOME/.xangi/.env"
    fi
  fi

  [[ -n "$env_file" && -f "$env_file" ]] || return 0

  local line key value
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line#"${line%%[![:space:]]*}"}"
    line="${line%"${line##*[![:space:]]}"}"
    [[ -z "$line" || "$line" == \#* || "$line" != *=* ]] && continue

    key="${line%%=*}"
    value="${line#*=}"
    key="${key%"${key##*[![:space:]]}"}"
    value="${value#"${value%%[![:space:]]*}"}"
    value="${value%"${value##*[![:space:]]}"}"
    if [[ "$value" == \"*\" && "$value" == *\" ]]; then
      value="${value:1:${#value}-2}"
    elif [[ "$value" == \'*\' && "$value" == *\' ]]; then
      value="${value:1:${#value}-2}"
    fi

    case "$key" in
      ANTHROPIC_API_KEY|CLAUDE_CODE_BARE|CLAUDE_CODE_MAX_BUDGET_USD)
        if [[ -z "${!key:-}" ]]; then
          export "$key=$value"
        fi
        ;;
    esac
  done < "$env_file"
}

usage() {
  cat <<'EOF'
Usage: run_agent.sh <agent-id> <prompt-file> [workspace]

Runs one available external agent in a short, foreground, read-oriented mode.
Use check_agents.sh before dispatching, and use xangi schedule/trigger if the
task may outlive the current turn.

agent-id: codex | claude | grok | cursor | antigravity
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" || $# -lt 2 ]]; then
  usage
  exit 0
fi

agent="$1"
prompt_file="$2"
workspace="${3:-$WORKSPACE}"

if [[ ! -f "$prompt_file" ]]; then
  echo "prompt file not found: $prompt_file" >&2
  exit 2
fi

prompt="$(cat "$prompt_file")"

run_antigravity_print() {
  local cmd="$1"
  local log_file
  log_file="$(mktemp "${TMPDIR:-/tmp}/antigravity-run-agent.XXXXXX.log")"

  local output
  local rc=0
  output="$("$cmd" --log-file "$log_file" -p "$prompt" 2>&1)" || rc=$?

  if [[ "$rc" -ne 0 ]]; then
    printf '%s\n' "$output"
    if [[ -s "$log_file" ]]; then
      printf 'antigravity log: %s\n' "$log_file" >&2
      tail -40 "$log_file" >&2
    fi
    return "$rc"
  fi

  if [[ -n "$output" ]]; then
    printf '%s\n' "$output"
    return 0
  fi

  if [[ ! -s "$log_file" ]]; then
    printf 'antigravity produced no output and no log: %s\n' "$log_file" >&2
    return 70
  fi

  if grep -Eq 'RESOURCE_EXHAUSTED|Individual quota reached|code 429' "$log_file"; then
    printf 'antigravity failed: quota exhausted or rate limited. log: %s\n' "$log_file" >&2
    grep -E 'RESOURCE_EXHAUSTED|Individual quota reached|code 429|Resets in' "$log_file" | tail -5 >&2
    return 75
  fi

  if grep -Eiq 'not logged into Antigravity|not authenticated|auth.*failed' "$log_file"; then
    printf 'antigravity failed: authentication problem. log: %s\n' "$log_file" >&2
    grep -Ei 'not logged into Antigravity|not authenticated|auth.*failed' "$log_file" | tail -5 >&2
    return 77
  fi

  if grep -Eiq 'model unreachable|agent executor error' "$log_file"; then
    printf 'antigravity failed: model unreachable. log: %s\n' "$log_file" >&2
    grep -Ei 'model unreachable|agent executor error' "$log_file" | tail -5 >&2
    return 70
  fi

  printf 'antigravity produced no output. log: %s\n' "$log_file" >&2
  tail -40 "$log_file" >&2
  return 70
}

case "$agent" in
  codex)
    command -v codex >/dev/null
    codex exec --skip-git-repo-check --sandbox danger-full-access --cd "$workspace" - < "$prompt_file"
    ;;
  claude)
    command -v claude >/dev/null
    load_agent_env
    args=(-p "$prompt" --add-dir "$workspace")
    if [[ "${CLAUDE_CODE_BARE:-}" == "true" ]]; then
      args+=(--bare)
    fi
    if [[ -n "${CLAUDE_CODE_MAX_BUDGET_USD:-}" ]]; then
      args+=(--max-budget-usd "$CLAUDE_CODE_MAX_BUDGET_USD")
    fi
    claude "${args[@]}"
    ;;
  grok)
    command -v grok >/dev/null
    grok -p "$prompt" --cwd "$workspace" --permission-mode plan --output-format plain
    ;;
  cursor)
    command -v cursor-agent >/dev/null
    cursor-agent --print --mode=ask --workspace "$workspace" "$prompt"
    ;;
  antigravity)
    if command -v agy >/dev/null 2>&1; then
      run_antigravity_print agy
    elif command -v antigravity >/dev/null 2>&1; then
      run_antigravity_print antigravity
    else
      echo "agy/antigravity command not found" >&2
      exit 127
    fi
    ;;
  self)
    echo "self is the current session; answer directly instead of using run_agent.sh" >&2
    exit 2
    ;;
  *)
    echo "unknown agent: $agent" >&2
    usage >&2
    exit 2
    ;;
esac
