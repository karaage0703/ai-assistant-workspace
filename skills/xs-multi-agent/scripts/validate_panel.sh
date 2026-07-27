#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: validate_panel.sh [--phase NAME] [--min-success N] [--min-families N] <agents.json> <results.tsv>

Validates that a multi-agent phase has usable evidence from enough successful
external agents and distinct provider families.

results.tsv columns:
  agent_id<TAB>phase<TAB>status<TAB>role<TAB>evidence_path
EOF
}

phase="synthesis"
min_success=2
min_families=2

while (($#)); do
  case "$1" in
    --phase)
      [[ $# -ge 2 ]] || { echo "--phase requires a value" >&2; exit 2; }
      phase="${2:-}"
      shift 2
      ;;
    --min-success)
      [[ $# -ge 2 ]] || { echo "--min-success requires a value" >&2; exit 2; }
      min_success="${2:-}"
      shift 2
      ;;
    --min-families)
      [[ $# -ge 2 ]] || { echo "--min-families requires a value" >&2; exit 2; }
      min_families="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    -*)
      printf 'unknown option: %s\n' "$1" >&2
      usage >&2
      exit 2
      ;;
    *)
      break
      ;;
  esac
done

if [[ $# -ne 2 ]]; then
  usage >&2
  exit 2
fi

agents_json="$1"
results_tsv="$2"

if [[ ! "$min_success" =~ ^[1-9][0-9]*$ || ! "$min_families" =~ ^[1-9][0-9]*$ ]]; then
  echo "minimums must be positive integers" >&2
  exit 2
fi
if [[ ! -f "$agents_json" || ! -f "$results_tsv" ]]; then
  echo "agents config and results manifest are required" >&2
  exit 2
fi

declare -A family_by_agent=()
declare -A ready_by_agent=()
while IFS=$'\t' read -r agent_id provider_family ready; do
  [[ -n "$agent_id" ]] || continue
  family_by_agent["$agent_id"]="$provider_family"
  ready_by_agent["$agent_id"]="$ready"
done < <(jq -r '.agents[] | [.id, (.provider_family // "unknown"), (.ready // false)] | @tsv' "$agents_json")

declare -A successful_agents=()
declare -A successful_families=()
declare -A agent_by_evidence_identity=()
invalid_success=0

while IFS=$'\t' read -r agent_id row_phase status role evidence_path extra || [[ -n "$agent_id" ]]; do
  evidence_path="${evidence_path%$'\r'}"
  [[ -n "$agent_id" && "$agent_id" != "agent_id" && "$agent_id" != \#* ]] || continue
  [[ "$row_phase" == "$phase" && "$status" == "success" ]] || continue

  provider_family="${family_by_agent[$agent_id]:-}"
  if [[ "${ready_by_agent[$agent_id]:-false}" != "true" ]]; then
    printf 'invalid success row: agent=%s was not ready in agents config\n' "$agent_id" >&2
    invalid_success=$((invalid_success + 1))
    continue
  fi
  if [[ -z "$provider_family" || "$provider_family" == "unknown" || "$agent_id" == "self" ]]; then
    printf 'invalid success row: agent=%s has no countable external provider family\n' "$agent_id" >&2
    invalid_success=$((invalid_success + 1))
    continue
  fi
  if [[ -z "$role" || -z "$evidence_path" || ! -s "$evidence_path" ]]; then
    printf 'invalid success row: agent=%s lacks role or non-empty evidence\n' "$agent_id" >&2
    invalid_success=$((invalid_success + 1))
    continue
  fi
  if ! grep -q '[^[:space:]]' "$evidence_path" \
    || grep -Eiq \
      '^[[:space:]]*FAIL[[:space:]]*$|^[[:space:]]*ERROR[[:space:]].*(tool_error:|error_kind.*(tool_output_error|parse_failure)|failed to watch root|kind: MaxFilesWatch)|^turn interrupted[[:space:]]*$|^[[:alnum:]_-]+ produced no output[[:space:]]*$|^(error:[[:space:]]*)?(authentication required|not logged in|api key missing|quota exceeded|resource_exhausted|429 too many requests|you.ve hit your usage limit)|^(error:[[:space:]]*)?(permission denied|approval required|sandbox denied|調査できませんでした[。]?)$' \
      "$evidence_path"; then
    printf 'invalid success row: agent=%s evidence contains no usable result\n' "$agent_id" >&2
    invalid_success=$((invalid_success + 1))
    continue
  fi
  canonical_evidence="$(realpath -e -- "$evidence_path" 2>/dev/null || true)"
  evidence_identity=""
  if [[ -n "$canonical_evidence" ]]; then
    evidence_identity="$(stat -Lc '%d:%i' -- "$canonical_evidence" 2>/dev/null || true)"
  fi
  if [[ -z "$canonical_evidence" || -z "$evidence_identity" ]]; then
    printf 'invalid success row: agent=%s evidence cannot be resolved\n' "$agent_id" >&2
    invalid_success=$((invalid_success + 1))
    continue
  fi
  if [[ -n "${agent_by_evidence_identity[$evidence_identity]:-}" ]]; then
    printf 'invalid success row: agents=%s,%s reuse evidence=%s\n' \
      "${agent_by_evidence_identity[$evidence_identity]}" "$agent_id" "$canonical_evidence" >&2
    invalid_success=$((invalid_success + 1))
    continue
  fi

  successful_agents["$agent_id"]=1
  successful_families["$provider_family"]=1
  agent_by_evidence_identity["$evidence_identity"]="$agent_id"
done < "$results_tsv"

success_count="${#successful_agents[@]}"
family_count="${#successful_families[@]}"

printf 'phase=%s successful_agents=%s provider_families=%s invalid_success_rows=%s\n' \
  "$phase" "$success_count" "$family_count" "$invalid_success"

if (( invalid_success > 0 || success_count < min_success || family_count < min_families )); then
  printf 'panel contract failed: need success>=%s and families>=%s\n' \
    "$min_success" "$min_families" >&2
  exit 1
fi

printf 'panel contract passed\n'
