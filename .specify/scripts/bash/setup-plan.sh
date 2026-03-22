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

spec_file="${feature_dir}/spec.md"
plan_file="${feature_dir}/plan.md"

if [[ ! -f "${plan_file}" ]]; then
  cp "${repo_root}/.specify/templates/plan-template.md" "${plan_file}"
fi

if [[ "${json}" == true ]]; then
  FEATURE_SPEC="${spec_file}" IMPL_PLAN="${plan_file}" SPECS_DIR="${feature_dir}" BRANCH="${branch_name}" \
    python3 - <<'PY'
import json
import os

print(json.dumps({
    "FEATURE_SPEC": os.environ["FEATURE_SPEC"],
    "IMPL_PLAN": os.environ["IMPL_PLAN"],
    "SPECS_DIR": os.environ["SPECS_DIR"],
    "BRANCH": os.environ["BRANCH"],
}, ensure_ascii=False))
PY
else
  echo "FEATURE_SPEC=${spec_file}"
  echo "IMPL_PLAN=${plan_file}"
  echo "SPECS_DIR=${feature_dir}"
  echo "BRANCH=${branch_name}"
fi
