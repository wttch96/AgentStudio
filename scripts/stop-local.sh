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
    local out
    out="$(ps -p "${pid}" -o command= 2>/dev/null || true)" && { printf '%s
' "${out}"; return; }
    # Cygwin/MinGW fallback: skip header + first 7 columns, keep COMMAND
    ps -p "${pid}" 2>/dev/null | awk 'NR>1{for(i=1;i<=7;i++) $i=""; sub(/^[[:space:]]+/, ""); print}' || true
  fi
}

belongs_to_current_user() {
  local pid="$1"
  local owner
  owner="$(ps -p "${pid}" -o uid= 2>/dev/null | tr -d '[:space:]' || true)"
  if [[ -z "${owner}" ]]; then
    # Cygwin/MinGW fallback: numeric UID is the 6th field in default ps output
    owner="$(ps -p "${pid}" 2>/dev/null | awk 'NR>1{print $6}' || true)"
  fi
  [[ -n "${owner}" && "${owner}" == "$(id -u)" ]]
}

matches_service() {
  local name="$1"
  local pid="$2"
  local cmdline
  cmdline="$(proc_cmdline "${pid}")"
  case "${name}" in
    backend)
      [[ "${cmdline}" == *"run.py"* ]]
      ;;
    frontend)
      [[ "${cmdline}" == *"${PROJECT_DIR}/frontend/node_modules/vite/bin/vite.js"* ]]
      ;;
    *)
      return 1
      ;;
  esac
}

matches_start_identity() {
  local name="$1"
  local pid="$2"
  local started_file="${RUN_DIR}/${name}.started"
  if [[ ! -f "${started_file}" ]]; then
    # 缺少 .started 文件（可能被清理或上次启动失败）：回退到服务名检查
    matches_service "${name}" "${pid}"
    return
  fi
  local expected actual
  expected="$(<"${started_file}")"
  # 令牌格式（Cygwin/MinGW 回退）：文件由当前脚本创建，文件存在即验证通过
  if [[ "${expected}" == token:* ]]; then
    return 0
  fi
  # 原生 lstart 格式：验证进程启动时间匹配
  actual="$(ps -p "${pid}" -o lstart= 2>/dev/null | sed 's/^[[:space:]]*//;s/[[:space:]]*$//' || true)"
  [[ -n "${actual}" && "${actual}" == "${expected}" ]]
}

stop_one() {
  local name="$1"
  local pid_file="${RUN_DIR}/${name}.pid"
  [[ -f "${pid_file}" ]] || return 0

  local pid
  pid="$(tr -cd '0-9' < "${pid_file}")"
  if [[ -z "${pid}" ]]; then
    rm -f "${pid_file}" "${RUN_DIR}/${name}.started"
    return 0
  fi

  if kill -0 "${pid}" 2>/dev/null; then
    if ! belongs_to_current_user "${pid}" \
      || ! matches_start_identity "${name}" "${pid}" \
      || ! matches_service "${name}" "${pid}"; then
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
  rm -f "${pid_file}" "${RUN_DIR}/${name}.started"
}

STATUS=0
stop_one backend || STATUS=1
stop_one frontend || STATUS=1
if [[ "${STATUS}" == "0" ]]; then
  rm -f "${RUN_DIR}/runtime.env"
  [[ "${QUIET}" == "1" ]] || echo "本地服务已停止。"
elif [[ "${QUIET}" != "1" ]]; then
  echo "部分服务未停止，请检查上述安全校验错误。" >&2
fi
exit "${STATUS}"
