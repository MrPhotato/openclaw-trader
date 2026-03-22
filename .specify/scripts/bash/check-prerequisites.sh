#!/usr/bin/env bash

set -euo pipefail

json=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --json)
      json=true
      shift
      ;;
    *)
      shift
      ;;
  esac
done

repo_root="$(git rev-parse --show-toplevel)"
branch_name="$(git branch --show-current)"
feature_dir=""

if [[ "${branch_name}" =~ ^codex/([0-9]{3}-.*)$ ]]; then
  candidate="${repo_root}/specs/${BASH_REMATCH[1]}"
  if [[ -d "${candidate}" ]]; then
    feature_dir="${candidate}"
  fi
fi

if [[ -z "${feature_dir}" ]]; then
  latest="$(find "${repo_root}/specs" -maxdepth 1 -mindepth 1 -type d 2>/dev/null | sort | tail -n 1 || true)"
  feature_dir="${latest}"
fi

if [[ -z "${feature_dir}" || ! -d "${feature_dir}" ]]; then
  echo "No feature directory found under specs/" >&2
  exit 1
fi

doc_names=()
for name in spec.md plan.md tasks.md research.md data-model.md quickstart.md; do
  if [[ -f "${feature_dir}/${name}" ]]; then
    doc_names+=("${name}")
  fi
done

available_docs_raw=""
if [[ ${#doc_names[@]} -gt 0 ]]; then
  available_docs_raw="$(printf '%s\n' "${doc_names[@]}")"
fi

FEATURE_DIR="${feature_dir}" AVAILABLE_DOCS_RAW="${available_docs_raw}" python3 - <<'PY'
import json
import os

print(json.dumps({
    "FEATURE_DIR": os.environ["FEATURE_DIR"],
    "AVAILABLE_DOCS": [line for line in os.environ.get("AVAILABLE_DOCS_RAW", "").splitlines() if line],
}, ensure_ascii=False))
PY
