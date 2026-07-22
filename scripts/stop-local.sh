#!/usr/bin/env bash
# 仅停止 .run/*.pid 中记录且仍属于当前用户的两个精确进程。
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_DIR="${PROJECT_DIR}/.run"

stop_one() {
  local name="$1"
  local pid_file="${RUN_DIR}/${name}.pid"
  [[ -f "${pid_file}" ]] || return 0

  local pid
  pid="$(tr -cd '0-9' < "${pid_file}")"
  if [[ -n "${pid}" ]] && kill -0 "${pid}" 2>/dev/null; then
    kill "${pid}" 2>/dev/null || true
    for _ in {1..20}; do
      kill -0 "${pid}" 2>/dev/null || break
      sleep 0.1
    done
  fi
  rm -f "${pid_file}"
}

stop_one backend
stop_one frontend
echo "本地服务已停止。"

