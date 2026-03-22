#!/usr/bin/env bash

set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
agent_type="${1:-all}"
target_dir="${repo_root}/.specify/agent-context"
target_file="${target_dir}/last-update.md"

mkdir -p "${target_dir}"
cat > "${target_file}" <<EOF
# Agent Context Update

- 更新时间：$(date -u +"%Y-%m-%dT%H:%M:%SZ")
- 目标 Agent：${agent_type}
- 说明：当前仓库使用本地 speckit 初始化骨架；后续如需接入更完整的 agent context 模板，可在此目录扩展。
EOF

echo "${target_file}"
