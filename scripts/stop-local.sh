#!/usr/bin/env bash
# 仅停止 .run/*.pid 中记录、属于当前用户且命令行匹配当前项目的精确进程。
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_DIR="${PROJECT_DIR}/.run"
QUIET=0
[[ "${1:-}" == "--quiet" ]] && QUIET=1

proc_cmdline() {
  local pid="$1"
  if [[ -f "/proc/${pid}/cmdline" ]]; then
    tr '\0' ' ' < "/proc/${pid}/cmdline" 2>/dev/null || true
  else
    ps -p "${pid}" -o command= 2>/dev/null || true
  fi
}

belongs_to_current_user() {
  local pid="$1"
  local owner
  owner="$(ps -p "${pid}" -o uid= 2>/dev/null | tr -d '[:space:]')"
  [[ -n "${owner}" && "${owner}" == "$(id -u)" ]]
}

matches_service() {
  local name="$1"
  local pid="$2"
  local cmdline
  cmdline="$(proc_cmdline "${pid}")"
  case "${name}" in
    backend)
      [[ "${cmdline}" == *"${PROJECT_DIR}/backend/.venv/"* && "${cmdline}" == *"run.py"* ]]
      ;;
    frontend)
      [[ "${cmdline}" == *"${PROJECT_DIR}/frontend/node_modules/vite/bin/vite.js"* ]]
      ;;
    *)
      return 1
      ;;
  esac
}

stop_one() {
  local name="$1"
  local pid_file="${RUN_DIR}/${name}.pid"
  [[ -f "${pid_file}" ]] || return 0

  local pid
  pid="$(tr -cd '0-9' < "${pid_file}")"
  if [[ -z "${pid}" ]]; then
    rm -f "${pid_file}"
    return 0
  fi

  if kill -0 "${pid}" 2>/dev/null; then
    if ! belongs_to_current_user "${pid}" || ! matches_service "${name}" "${pid}"; then
      echo "[stop] 拒绝停止 ${name}：PID ${pid} 不属于当前项目服务。" >&2
      return 1
    fi
    kill "${pid}" 2>/dev/null || true
    for _ in {1..50}; do
      kill -0 "${pid}" 2>/dev/null || break
      sleep 0.1
    done
    if kill -0 "${pid}" 2>/dev/null && matches_service "${name}" "${pid}"; then
      kill -KILL "${pid}" 2>/dev/null || true
    fi
  fi
  rm -f "${pid_file}"
}

STATUS=0
stop_one backend || STATUS=1
stop_one frontend || STATUS=1
[[ "${QUIET}" == "1" ]] || echo "本地服务已停止。"
exit "${STATUS}"
