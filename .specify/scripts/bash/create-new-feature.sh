#!/usr/bin/env bash

set -euo pipefail

json=false
number=""
short_name=""
description=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --json)
      json=true
      shift
      ;;
    --number)
      number="${2:-}"
      shift 2
      ;;
    --short-name)
      short_name="${2:-}"
      shift 2
      ;;
    *)
      description="$1"
      shift
      ;;
  esac
done

if [[ -z "$number" || -z "$short_name" || -z "$description" ]]; then
  echo "usage: $0 [--json] --number <n> --short-name <name> \"description\"" >&2
  exit 1
fi

repo_root="$(git rev-parse --show-toplevel)"
feature_id="$(printf "%03d" "$number")-${short_name}"
branch_name="codex/${feature_id}"
feature_dir="${repo_root}/specs/${feature_id}"
spec_file="${feature_dir}/spec.md"

mkdir -p "${feature_dir}/checklists"

current_branch="$(git branch --show-current)"
if [[ "${current_branch}" != "${branch_name}" ]]; then
  if git show-ref --verify --quiet "refs/heads/${branch_name}"; then
    git checkout "${branch_name}" >/dev/null
  else
    git checkout -b "${branch_name}" >/dev/null
  fi
fi

if [[ ! -f "${spec_file}" ]]; then
  cp "${repo_root}/.specify/templates/spec-template.md" "${spec_file}"
fi

if [[ "${json}" == true ]]; then
  BRANCH_NAME="${branch_name}" FEATURE_DIR="${feature_dir}" SPEC_FILE="${spec_file}" DESCRIPTION="${description}" \
    python3 - <<'PY'
import json
import os

print(json.dumps({
    "BRANCH_NAME": os.environ["BRANCH_NAME"],
    "FEATURE_DIR": os.environ["FEATURE_DIR"],
    "SPEC_FILE": os.environ["SPEC_FILE"],
    "DESCRIPTION": os.environ["DESCRIPTION"],
}, ensure_ascii=False))
PY
else
  echo "BRANCH_NAME=${branch_name}"
  echo "FEATURE_DIR=${feature_dir}"
  echo "SPEC_FILE=${spec_file}"
fi
