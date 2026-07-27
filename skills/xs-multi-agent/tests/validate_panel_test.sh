#!/usr/bin/env bash
set -euo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TEST_TMP="$(mktemp -d)"
trap 'rm -rf "$TEST_TMP"' EXIT

cat > "$TEST_TMP/agents.json" <<'EOF'
{
  "agents": [
    {"id": "self", "provider_family": "current-session", "ready": true},
    {"id": "codex", "provider_family": "openai", "ready": true},
    {"id": "codex_worker", "provider_family": "openai", "ready": true},
    {"id": "claude", "provider_family": "anthropic", "ready": true},
    {"id": "grok", "provider_family": "xai", "ready": false},
    {"id": "cursor", "provider_family": "unknown", "ready": true}
  ]
}
EOF

printf 'Codex synthesis\n' > "$TEST_TMP/codex.txt"
printf 'Second OpenAI synthesis\n' > "$TEST_TMP/codex-worker.txt"
printf 'Claude synthesis\n' > "$TEST_TMP/claude.txt"
printf '   \n\t\n' > "$TEST_TMP/blank.txt"
printf 'ERROR tool_error: error_kind=parse_failure\n' > "$TEST_TMP/runtime-error.txt"

cat > "$TEST_TMP/same-family.tsv" <<EOF
agent_id	phase	status	role	evidence_path
codex	synthesis	success	integrated review	$TEST_TMP/codex.txt
codex_worker	synthesis	success	counter review	$TEST_TMP/codex-worker.txt
EOF

if "$SKILL_DIR/scripts/validate_panel.sh" "$TEST_TMP/agents.json" "$TEST_TMP/same-family.tsv" >/dev/null 2>&1; then
  echo "FAIL: two agents from one provider family passed" >&2
  exit 1
fi

cat > "$TEST_TMP/two-families.tsv" <<EOF
agent_id	phase	status	role	evidence_path
codex	synthesis	success	integrated review	$TEST_TMP/codex.txt
claude	synthesis	success	counter review	$TEST_TMP/claude.txt
EOF

output="$("$SKILL_DIR/scripts/validate_panel.sh" "$TEST_TMP/agents.json" "$TEST_TMP/two-families.tsv")"
grep -q 'panel contract passed' <<< "$output"

printf 'agent_id\tphase\tstatus\trole\tevidence_path\ncodex\tsynthesis\tsuccess\tintegrated review\t%s\nclaude\tsynthesis\tsuccess\tcounter review\t%s' \
  "$TEST_TMP/codex.txt" "$TEST_TMP/claude.txt" > "$TEST_TMP/no-final-newline.tsv"
"$SKILL_DIR/scripts/validate_panel.sh" \
  "$TEST_TMP/agents.json" "$TEST_TMP/no-final-newline.tsv" >/dev/null

cat > "$TEST_TMP/not-ready.tsv" <<EOF
agent_id	phase	status	role	evidence_path
codex	synthesis	success	integrated review	$TEST_TMP/codex.txt
grok	synthesis	success	counter review	$TEST_TMP/claude.txt
EOF
if "$SKILL_DIR/scripts/validate_panel.sh" "$TEST_TMP/agents.json" "$TEST_TMP/not-ready.tsv" >/dev/null 2>&1; then
  echo "FAIL: not-ready provider passed" >&2
  exit 1
fi

cat > "$TEST_TMP/duplicate-evidence.tsv" <<EOF
agent_id	phase	status	role	evidence_path
codex	synthesis	success	integrated review	$TEST_TMP/codex.txt
claude	synthesis	success	counter review	$TEST_TMP/codex.txt
EOF
if "$SKILL_DIR/scripts/validate_panel.sh" "$TEST_TMP/agents.json" "$TEST_TMP/duplicate-evidence.tsv" >/dev/null 2>&1; then
  echo "FAIL: duplicate evidence passed" >&2
  exit 1
fi

cat > "$TEST_TMP/blank-evidence.tsv" <<EOF
agent_id	phase	status	role	evidence_path
codex	synthesis	success	integrated review	$TEST_TMP/codex.txt
claude	synthesis	success	counter review	$TEST_TMP/blank.txt
EOF
if "$SKILL_DIR/scripts/validate_panel.sh" "$TEST_TMP/agents.json" "$TEST_TMP/blank-evidence.tsv" >/dev/null 2>&1; then
  echo "FAIL: whitespace-only evidence passed" >&2
  exit 1
fi

cat > "$TEST_TMP/runtime-error.tsv" <<EOF
agent_id	phase	status	role	evidence_path
codex	synthesis	success	integrated review	$TEST_TMP/codex.txt
claude	synthesis	success	counter review	$TEST_TMP/runtime-error.txt
EOF
if "$SKILL_DIR/scripts/validate_panel.sh" "$TEST_TMP/agents.json" "$TEST_TMP/runtime-error.tsv" >/dev/null 2>&1; then
  echo "FAIL: runtime-error evidence passed" >&2
  exit 1
fi

printf 'agent_id\tphase\tstatus\trole\tevidence_path\r\ncodex\tsynthesis\tsuccess\tintegrated review\t%s\r\nclaude\tsynthesis\tsuccess\tcounter review\t%s\r\n' \
  "$TEST_TMP/codex.txt" "$TEST_TMP/claude.txt" > "$TEST_TMP/crlf.tsv"
"$SKILL_DIR/scripts/validate_panel.sh" "$TEST_TMP/agents.json" "$TEST_TMP/crlf.tsv" >/dev/null

ln -s "$TEST_TMP/codex.txt" "$TEST_TMP/codex-link.txt"
cat > "$TEST_TMP/symlink-evidence.tsv" <<EOF
agent_id	phase	status	role	evidence_path
codex	synthesis	success	integrated review	$TEST_TMP/codex.txt
claude	synthesis	success	counter review	$TEST_TMP/codex-link.txt
EOF
if "$SKILL_DIR/scripts/validate_panel.sh" "$TEST_TMP/agents.json" "$TEST_TMP/symlink-evidence.tsv" >/dev/null 2>&1; then
  echo "FAIL: symlinked duplicate evidence passed" >&2
  exit 1
fi

cat > "$TEST_TMP/unknown-provider.tsv" <<EOF
agent_id	phase	status	role	evidence_path
codex	synthesis	success	integrated review	$TEST_TMP/codex.txt
cursor	synthesis	success	counter review	$TEST_TMP/claude.txt
EOF

if "$SKILL_DIR/scripts/validate_panel.sh" "$TEST_TMP/agents.json" "$TEST_TMP/unknown-provider.tsv" >/dev/null 2>&1; then
  echo "FAIL: unknown provider counted as independent family" >&2
  exit 1
fi

if "$SKILL_DIR/scripts/validate_panel.sh" --phase >/dev/null 2>&1; then
  echo "FAIL: missing option value was accepted" >&2
  exit 1
else
  rc=$?
  [[ "$rc" -eq 2 ]]
fi

echo "validate_panel tests: PASS"
