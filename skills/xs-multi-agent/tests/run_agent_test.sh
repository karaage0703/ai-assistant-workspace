#!/usr/bin/env bash
set -euo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TEST_TMP="$(mktemp -d)"
trap 'rm -rf "$TEST_TMP"' EXIT

FAKE_BIN="$TEST_TMP/bin"
mkdir -p "$FAKE_BIN"
RUN_TMP="$TEST_TMP/runtime"
mkdir -p "$RUN_TMP"
PROMPT_FILE="$TEST_TMP/prompt.txt"
printf '調査して結果を返してください。\n' > "$PROMPT_FILE"

cat > "$FAKE_BIN/codex" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
output_file=""
printf '%s\n' "$@" > "${FAKE_CODEX_ARGS_FILE:?}"
while (($#)); do
  if [[ "$1" == "--output-last-message" ]]; then
    output_file="$2"
    shift 2
  else
    shift
  fi
done
printf '大量の診断ログ\n%.0s' {1..10000}
printf 'Codexの検証済み最終回答です。\n' > "$output_file"
EOF

cat > "$FAKE_BIN/claude" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$PWD" > "${FAKE_CLAUDE_CWD_FILE:?}"
printf '%s\n' "$@" > "${FAKE_CLAUDE_ARGS_FILE:?}"
if [[ "${FAKE_CLAUDE_MODE:-failure}" == "success" ]]; then
  printf 'Claudeの検証済み回答です。必要な根拠と結論を含みます。\n'
  exit 0
fi
printf '調査できませんでした。\n\n## ブロッカー\nrequires approval のため遮断されています。\n'
EOF

cat > "$FAKE_BIN/grok" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$@" > "${FAKE_GROK_ARGS_FILE:?}"
case "${FAKE_GROK_MODE:-failure}" in
  failure)
    printf 'ERROR failed to watch root: Error { kind: MaxFilesWatch }\n'
    ;;
  tool_error)
    printf 'レビューを開始します。\nERROR tool_error: tool_output_error error_kind=parse_failure\n'
    ;;
  whitespace)
    printf '   \n\t\n'
    ;;
  auth)
    printf 'Authentication required. Please log in.\n'
    ;;
  stderr_only)
    printf 'unknown diagnostic emitted only on stderr\n' >&2
    ;;
  success)
    printf 'Grokの検証済み回答です。tool_error: と turn interrupted を説明に含みます。\n'
    ;;
  review_terms)
    printf 'レビュー対象には「ブロッカー」と requires approval の記述がありますが、調査は完了しました。\n'
    ;;
esac
EOF

cat > "$FAKE_BIN/cursor-agent" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$@" > "${FAKE_CURSOR_ARGS_FILE:?}"
printf 'Cursorの検証済み回答です。\n'
EOF

cat > "$FAKE_BIN/agy" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$PWD" > "${FAKE_ANTIGRAVITY_CWD_FILE:?}"
printf '%s\n' "$@" > "${FAKE_ANTIGRAVITY_ARGS_FILE:?}"
if [[ "${FAKE_ANTIGRAVITY_MODE:-success}" == "fail" ]]; then
  printf 'FAIL\n'
  exit 0
fi
printf 'Antigravityの検証済み回答です。\n'
EOF

chmod +x "$FAKE_BIN"/*

run_agent() {
  PATH="$FAKE_BIN:$PATH" MULTI_AGENT_ENV_FILE="$TEST_TMP/missing.env" \
    TMPDIR="$RUN_TMP" \
    FAKE_CODEX_ARGS_FILE="$TEST_TMP/codex.args" \
    FAKE_CLAUDE_CWD_FILE="$TEST_TMP/claude.cwd" \
    FAKE_CLAUDE_ARGS_FILE="$TEST_TMP/claude.args" \
    FAKE_GROK_ARGS_FILE="$TEST_TMP/grok.args" \
    FAKE_CURSOR_ARGS_FILE="$TEST_TMP/cursor.args" \
    FAKE_ANTIGRAVITY_CWD_FILE="$TEST_TMP/antigravity.cwd" \
    FAKE_ANTIGRAVITY_ARGS_FILE="$TEST_TMP/antigravity.args" \
    "$SKILL_DIR/scripts/run_agent.sh" "$@"
}

if run_agent codex "$PROMPT_FILE" > "$TEST_TMP/missing.out" 2> "$TEST_TMP/missing.err"; then
  echo "FAIL: missing target workspace was accepted" >&2
  exit 1
fi
grep -q 'target-workspace' "$TEST_TMP/missing.err"

codex_output="$(run_agent codex "$PROMPT_FILE" "$TEST_TMP")"
[[ "$codex_output" == "Codexの検証済み最終回答です。" ]]
[[ "${#codex_output}" -lt 100 ]]
grep -Fxq -- '--sandbox' "$TEST_TMP/codex.args"
grep -Fxq -- 'read-only' "$TEST_TMP/codex.args"

if run_agent claude "$PROMPT_FILE" "$TEST_TMP" > "$TEST_TMP/claude.out" 2> "$TEST_TMP/claude.err"; then
  echo "FAIL: Claude blocker was accepted" >&2
  exit 1
fi
grep -q 'capability/permission blocker' "$TEST_TMP/claude.err"

claude_output="$(FAKE_CLAUDE_MODE=success run_agent claude "$PROMPT_FILE" "$TEST_TMP")"
[[ "$claude_output" == "Claudeの検証済み回答です。必要な根拠と結論を含みます。" ]]
[[ "$(cat "$TEST_TMP/claude.cwd")" == "$TEST_TMP" ]]
grep -Fxq -- '--permission-mode' "$TEST_TMP/claude.args"
grep -Fxq -- 'dontAsk' "$TEST_TMP/claude.args"
grep -Fxq -- '--safe-mode' "$TEST_TMP/claude.args"

if run_agent grok "$PROMPT_FILE" "$TEST_TMP" > "$TEST_TMP/grok.out" 2> "$TEST_TMP/grok.err"; then
  echo "FAIL: Grok watch failure was accepted" >&2
  exit 1
fi
grep -q 'runtime failure marker' "$TEST_TMP/grok.err"

if FAKE_GROK_MODE=tool_error run_agent grok "$PROMPT_FILE" "$TEST_TMP" \
  > "$TEST_TMP/grok-tool-error.out" 2> "$TEST_TMP/grok-tool-error.err"; then
  echo "FAIL: Grok tool error log was accepted" >&2
  exit 1
fi
grep -q 'runtime failure marker' "$TEST_TMP/grok-tool-error.err"

if FAKE_GROK_MODE=whitespace run_agent grok "$PROMPT_FILE" "$TEST_TMP" \
  > "$TEST_TMP/grok-whitespace.out" 2> "$TEST_TMP/grok-whitespace.err"; then
  echo "FAIL: whitespace-only Grok output was accepted" >&2
  exit 1
fi
grep -q 'whitespace-only' "$TEST_TMP/grok-whitespace.err"

if FAKE_GROK_MODE=auth run_agent grok "$PROMPT_FILE" "$TEST_TMP" \
  > "$TEST_TMP/grok-auth.out" 2> "$TEST_TMP/grok-auth.err"; then
  echo "FAIL: Grok authentication blocker was accepted" >&2
  exit 1
fi
grep -q 'authentication or quota blocker' "$TEST_TMP/grok-auth.err"

if FAKE_GROK_MODE=stderr_only run_agent grok "$PROMPT_FILE" "$TEST_TMP" \
  > "$TEST_TMP/grok-stderr-only.out" 2> "$TEST_TMP/grok-stderr-only.err"; then
  echo "FAIL: stderr-only Grok output was accepted" >&2
  exit 1
fi
grep -q 'expected at least' "$TEST_TMP/grok-stderr-only.err"

grok_output="$(FAKE_GROK_MODE=success run_agent grok "$PROMPT_FILE" "$TEST_TMP")"
[[ "$grok_output" == "Grokの検証済み回答です。tool_error: と turn interrupted を説明に含みます。" ]]
review_output="$(FAKE_GROK_MODE=review_terms run_agent grok "$PROMPT_FILE" "$TEST_TMP")"
[[ "$review_output" == *"調査は完了しました"* ]]
grep -Fxq -- '--no-memory' "$TEST_TMP/grok.args"
grep -Fxq -- '--no-subagents' "$TEST_TMP/grok.args"

cursor_output="$(run_agent cursor "$PROMPT_FILE" "$TEST_TMP")"
[[ "$cursor_output" == "Cursorの検証済み回答です。" ]]
grep -Fxq -- '--trust' "$TEST_TMP/cursor.args"
grep -Fxq -- '--model' "$TEST_TMP/cursor.args"
grep -Fxq -- 'auto' "$TEST_TMP/cursor.args"
grep -Fxq -- "$TEST_TMP" "$TEST_TMP/cursor.args"

antigravity_output="$(run_agent antigravity "$PROMPT_FILE" "$TEST_TMP")"
[[ "$antigravity_output" == "Antigravityの検証済み回答です。" ]]
[[ "$(cat "$TEST_TMP/antigravity.cwd")" == "$TEST_TMP" ]]
grep -Fxq -- '--add-dir' "$TEST_TMP/antigravity.args"
grep -Fxq -- "$TEST_TMP" "$TEST_TMP/antigravity.args"
grep -Fxq -- '--mode' "$TEST_TMP/antigravity.args"
grep -Fxq -- 'plan' "$TEST_TMP/antigravity.args"
grep -Fxq -- '--sandbox' "$TEST_TMP/antigravity.args"
grep -Fxq -- '--model' "$TEST_TMP/antigravity.args"
grep -Fxq -- 'gemini-3.1-pro-low' "$TEST_TMP/antigravity.args"
if compgen -G "$RUN_TMP/antigravity-run-agent.*.log" >/dev/null; then
  echo "FAIL: successful Antigravity log was not cleaned up" >&2
  exit 1
fi

if FAKE_ANTIGRAVITY_MODE=fail run_agent antigravity "$PROMPT_FILE" "$TEST_TMP" \
  > "$TEST_TMP/antigravity-fail.out" 2> "$TEST_TMP/antigravity-fail.err"; then
  echo "FAIL: Antigravity FAIL response was accepted" >&2
  exit 1
fi
grep -q 'returned FAIL' "$TEST_TMP/antigravity-fail.err"

if (
  export MULTI_AGENT_MIN_OUTPUT_BYTES=500
  run_agent antigravity "$PROMPT_FILE" "$TEST_TMP"
) > "$TEST_TMP/antigravity-short.out" 2> "$TEST_TMP/antigravity-short.err"; then
  echo "FAIL: short Antigravity result was accepted" >&2
  exit 1
fi
grep -q 'expected at least 500' "$TEST_TMP/antigravity-short.err"

if (
  export MULTI_AGENT_MIN_OUTPUT_BYTES=500
  export FAKE_GROK_MODE=success
  run_agent grok "$PROMPT_FILE" "$TEST_TMP"
) > "$TEST_TMP/short.out" 2> "$TEST_TMP/short.err"; then
  echo "FAIL: short research result was accepted" >&2
  exit 1
fi
grep -q 'expected at least 500' "$TEST_TMP/short.err"

echo "run_agent tests: PASS"
