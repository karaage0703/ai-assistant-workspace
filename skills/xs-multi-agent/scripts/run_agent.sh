#!/usr/bin/env bash
set -euo pipefail

TEMP_PATHS=()
cleanup_temp_paths() {
  if ((${#TEMP_PATHS[@]})); then
    rm -f -- "${TEMP_PATHS[@]}"
  fi
}
trap cleanup_temp_paths EXIT
trap 'cleanup_temp_paths; exit 130' HUP INT TERM

load_agent_env() {
  local env_file="${MULTI_AGENT_ENV_FILE:-}"

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
      ANTHROPIC_API_KEY|CLAUDE_CODE_MAX_BUDGET_USD)
        if [[ -z "${!key:-}" ]]; then
          export "$key=$value"
        fi
        ;;
    esac
  done < "$env_file"
}

usage() {
  cat <<'EOF'
Usage: run_agent.sh <agent-id> <prompt-file> <target-workspace>

Runs one available external agent in a short, foreground, read-oriented mode.
Use check_agents.sh before dispatching. If the task may outlive the current
turn, use the host environment's scheduler or completion trigger.

agent-id: codex | claude | grok | cursor | antigravity

target-workspace is required. Pass the smallest directory that contains the
material needed for this task; do not expose the coordinator workspace by
default.

The command returns non-zero when the CLI exits successfully but its output is
empty, interrupted, or contains a known runtime blocker. Set
MULTI_AGENT_MIN_OUTPUT_BYTES for tasks that require a substantial report.
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

if [[ $# -ne 3 ]]; then
  usage >&2
  exit 2
fi

agent="$1"
prompt_file="$2"
workspace="$3"

if [[ ! -f "$prompt_file" ]]; then
  echo "prompt file not found: $prompt_file" >&2
  exit 2
fi
if [[ ! -d "$workspace" ]]; then
  echo "target workspace not found: $workspace" >&2
  exit 2
fi
workspace="$(cd "$workspace" && pwd -P)"

prompt="$(cat "$prompt_file")"

validate_output() {
  local agent_id="$1"
  local output_file="$2"
  local min_bytes="${MULTI_AGENT_MIN_OUTPUT_BYTES:-1}"
  local output_bytes

  output_bytes="$(wc -c < "$output_file" | tr -d '[:space:]')"
  if [[ ! "$min_bytes" =~ ^[0-9]+$ ]]; then
    printf 'MULTI_AGENT_MIN_OUTPUT_BYTES must be a non-negative integer: %s\n' "$min_bytes" >&2
    return 2
  fi
  if (( output_bytes < min_bytes )); then
    printf '%s result rejected: %s bytes, expected at least %s\n' \
      "$agent_id" "$output_bytes" "$min_bytes" >&2
    return 70
  fi
  if ! grep -q '[^[:space:]]' "$output_file"; then
    printf '%s result rejected: output is blank or whitespace-only\n' "$agent_id" >&2
    return 70
  fi

  if grep -Eiq \
    '^[[:space:]]*ERROR[[:space:]].*(tool_error:|error_kind.*(tool_output_error|parse_failure)|failed to watch root|kind: MaxFilesWatch)|^turn interrupted[[:space:]]*$|^[[:alnum:]_-]+ produced no output[[:space:]]*$' \
    "$output_file"; then
    printf '%s result rejected: runtime failure marker found\n' "$agent_id" >&2
    tail -20 "$output_file" >&2
    return 70
  fi
  if grep -Eiq \
    '^(error:[[:space:]]*)?(authentication required|not logged in|api key missing|quota exceeded|resource_exhausted|429 too many requests|you.ve hit your usage limit)' \
    "$output_file"; then
    printf '%s result rejected: authentication or quota blocker found\n' "$agent_id" >&2
    tail -20 "$output_file" >&2
    return 77
  fi

  if grep -Eiq \
    '^(error:[[:space:]]*)?(permission denied|approval required|sandbox denied|調査できませんでした[。]?)$' \
    "$output_file"; then
    printf '%s result rejected: capability/permission blocker found\n' "$agent_id" >&2
    tail -20 "$output_file" >&2
    return 77
  fi
}

run_and_validate() {
  local agent_id="$1"
  shift
  local output_file
  local diagnostic_file
  output_file="$(mktemp "${TMPDIR:-/tmp}/multi-agent-result.XXXXXX")"
  diagnostic_file="$(mktemp "${TMPDIR:-/tmp}/multi-agent-diagnostic.XXXXXX")"
  TEMP_PATHS+=("$output_file" "$diagnostic_file")
  local rc=0

  "$@" > "$output_file" 2> "$diagnostic_file" || rc=$?
  if [[ "$rc" -ne 0 ]]; then
    printf '%s failed with exit code %s\n' "$agent_id" "$rc" >&2
    tail -40 "$diagnostic_file" >&2
    tail -20 "$output_file" >&2
    rm -f "$output_file" "$diagnostic_file"
    return "$rc"
  fi
  if validate_output "$agent_id" "$output_file"; then
    :
  else
    rc=$?
    if [[ -s "$diagnostic_file" ]]; then
      printf '%s diagnostic tail:\n' "$agent_id" >&2
      tail -20 "$diagnostic_file" >&2
    fi
    rm -f "$output_file" "$diagnostic_file"
    return "$rc"
  fi

  cat "$output_file"
  rm -f "$output_file" "$diagnostic_file"
}

run_codex() {
  local result_file
  local diagnostic_file
  result_file="$(mktemp "${TMPDIR:-/tmp}/codex-last-message.XXXXXX")"
  diagnostic_file="$(mktemp "${TMPDIR:-/tmp}/codex-diagnostic.XXXXXX")"
  TEMP_PATHS+=("$result_file" "$diagnostic_file")
  local rc=0

  codex exec \
    --skip-git-repo-check \
    --sandbox read-only \
    --cd "$workspace" \
    --output-last-message "$result_file" \
    - < "$prompt_file" > "$diagnostic_file" 2>&1 || rc=$?

  if [[ "$rc" -ne 0 ]]; then
    printf 'codex failed with exit code %s\n' "$rc" >&2
    tail -40 "$diagnostic_file" >&2
    rm -f "$result_file" "$diagnostic_file"
    return "$rc"
  fi
  if validate_output codex "$result_file"; then
    :
  else
    rc=$?
    printf 'codex diagnostic tail:\n' >&2
    tail -40 "$diagnostic_file" >&2
    rm -f "$result_file" "$diagnostic_file"
    return "$rc"
  fi

  cat "$result_file"
  rm -f "$result_file" "$diagnostic_file"
}

run_antigravity_print() {
  local cmd="$1"
  local log_file
  local diagnostic_file
  log_file="$(mktemp "${TMPDIR:-/tmp}/antigravity-run-agent.XXXXXX.log")"
  diagnostic_file="$(mktemp "${TMPDIR:-/tmp}/antigravity-diagnostic.XXXXXX")"
  TEMP_PATHS+=("$log_file" "$diagnostic_file")

  local output
  local rc=0
  output="$(
    cd "$workspace"
    "$cmd" \
      --log-file "$log_file" \
      --add-dir "$workspace" \
      --mode plan \
      --sandbox \
      --model "${MULTI_AGENT_ANTIGRAVITY_MODEL:-gemini-3.1-pro-low}" \
      -p "$prompt" 2> "$diagnostic_file"
  )" || rc=$?

  if [[ "$rc" -ne 0 ]]; then
    printf '%s\n' "$output"
    tail -40 "$diagnostic_file" >&2
    if [[ -s "$log_file" ]]; then
      printf 'antigravity diagnostic tail:\n' >&2
      tail -40 "$log_file" >&2
    fi
    rm -f "$log_file" "$diagnostic_file"
    return "$rc"
  fi

  if [[ "${output//[[:space:]]/}" == "FAIL" ]]; then
    printf 'antigravity returned FAIL. log: %s\n' "$log_file" >&2
    grep -Ei \
      'not logged into Antigravity|not authenticated|auth.*failed|failed to read file|invalid tool call|model unreachable|agent executor error|RESOURCE_EXHAUSTED|Individual quota reached|code 429' \
      "$log_file" | tail -10 >&2 || true
    rm -f "$log_file" "$diagnostic_file"
    return 70
  fi

  if [[ -n "$output" ]]; then
    local output_file
    output_file="$(mktemp "${TMPDIR:-/tmp}/antigravity-result.XXXXXX")"
    TEMP_PATHS+=("$output_file")
    printf '%s\n' "$output" > "$output_file"
    if validate_output antigravity "$output_file"; then
      cat "$output_file"
      rm -f "$output_file" "$log_file" "$diagnostic_file"
      return 0
    else
      rc=$?
      rm -f "$output_file" "$log_file" "$diagnostic_file"
      return "$rc"
    fi
  fi

  if [[ ! -s "$log_file" ]]; then
    printf 'antigravity produced no output and no log: %s\n' "$log_file" >&2
    rm -f "$log_file" "$diagnostic_file"
    return 70
  fi

  if grep -Eq 'RESOURCE_EXHAUSTED|Individual quota reached|code 429' "$log_file"; then
    printf 'antigravity failed: quota exhausted or rate limited. log: %s\n' "$log_file" >&2
    grep -E 'RESOURCE_EXHAUSTED|Individual quota reached|code 429|Resets in' "$log_file" | tail -5 >&2
    rm -f "$log_file" "$diagnostic_file"
    return 75
  fi

  if grep -Eiq 'not logged into Antigravity|not authenticated|auth.*failed' "$log_file"; then
    printf 'antigravity failed: authentication problem. log: %s\n' "$log_file" >&2
    grep -Ei 'not logged into Antigravity|not authenticated|auth.*failed' "$log_file" | tail -5 >&2
    rm -f "$log_file" "$diagnostic_file"
    return 77
  fi

  if grep -Eiq 'model unreachable|agent executor error' "$log_file"; then
    printf 'antigravity failed: model unreachable. log: %s\n' "$log_file" >&2
    grep -Ei 'model unreachable|agent executor error' "$log_file" | tail -5 >&2
    rm -f "$log_file" "$diagnostic_file"
    return 70
  fi

  printf 'antigravity produced no output. log: %s\n' "$log_file" >&2
  tail -40 "$log_file" >&2
  rm -f "$log_file" "$diagnostic_file"
  return 70
}

case "$agent" in
  codex)
    command -v codex >/dev/null
    run_codex
    ;;
  claude)
    command -v claude >/dev/null
    load_agent_env
    args=(
      -p "$prompt"
      --add-dir "$workspace"
      --tools "Read,Glob,Grep,WebFetch,WebSearch"
      --allowedTools "Read,Glob,Grep,WebFetch,WebSearch"
      --permission-mode dontAsk
      --safe-mode
    )
    if [[ -n "${CLAUDE_CODE_MAX_BUDGET_USD:-}" ]]; then
      args+=(--max-budget-usd "$CLAUDE_CODE_MAX_BUDGET_USD")
    fi
    (
      cd "$workspace"
      run_and_validate claude claude "${args[@]}"
    )
    ;;
  grok)
    command -v grok >/dev/null
    run_and_validate grok grok \
      -p "$prompt" \
      --cwd "$workspace" \
      --permission-mode plan \
      --output-format plain \
      --no-memory \
      --no-subagents \
      --tools "Read,Glob,Grep,WebFetch,WebSearch"
    ;;
  cursor)
    command -v cursor-agent >/dev/null
    run_and_validate cursor cursor-agent \
      --print \
      --mode=ask \
      --model auto \
      --trust \
      --workspace "$workspace" \
      "$prompt"
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
