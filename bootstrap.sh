#!/usr/bin/env bash
# ============================================================
# Agent Studio Bootstrap — 自举沙箱管理脚本
# ============================================================
# 将已提交的 main 分支快照复制到 .sandbox 沙箱目录中隔离运行，
# 然后把本地工作区切换到 dev 分支继续开发。沙箱与开发环境互不干扰。
#
# 用法:
#   ./bootstrap.sh             一键自举（setup → start）
#   ./bootstrap.sh setup       从 main 强制重建沙箱，并切换本地到 dev
#   ./bootstrap.sh start       在沙箱内启动服务
#   ./bootstrap.sh stop        停止沙箱内服务
#   ./bootstrap.sh restart     重启沙箱服务
#   ./bootstrap.sh destroy     删除沙箱目录
#   ./bootstrap.sh status      查看沙箱状态
# ============================================================
set -euo pipefail

# —— 路径常量 ——
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SANDBOX_DIR="${PROJECT_DIR}/.sandbox"
BOOTSTRAP_NAME="$(basename "${BASH_SOURCE[0]}")"
SANDBOX_SOURCE_BRANCH="main"
LOCAL_DEVELOPMENT_BRANCH="dev"

# —— 颜色 ——
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# —— 辅助函数 ——
success() { echo -e "${GREEN}[bootstrap]${NC} $*"; }
warn()    { echo -e "${YELLOW}[bootstrap]${NC} $*"; }
error()   { echo -e "${RED}[bootstrap]${NC} $*" >&2; }
info()    { echo -e "${CYAN}[bootstrap]${NC} $*"; }
die()     { error "$*"; exit 1; }

# —— 显示帮助 ——
show_help() {
  sed -n '/^# 用法:/,/^# ====/p' "${BASH_SOURCE[0]}" | sed 's/^# //'
  echo
  echo "子命令:"
  echo "  setup      从 main 强制重建沙箱，并切换本地工作区到 dev"
  echo "  start      在沙箱内启动前后端服务"
  echo "  stop       停止沙箱内服务"
  echo "  restart    停止后重新启动"
  echo "  destroy    删除 .sandbox 目录"
  echo "  status     查看沙箱状态（是否存在、服务是否运行）"
  echo
  echo "不带参数默认执行: setup → start"
}

# —— Git 分支检查 ——
require_source_branch() {
  command -v git >/dev/null 2>&1 || die "缺少必需命令：git"
  command -v tar >/dev/null 2>&1 || die "缺少必需命令：tar"
  if ! git -C "${PROJECT_DIR}" show-ref --verify --quiet \
    "refs/heads/${SANDBOX_SOURCE_BRANCH}"; then
    die "缺少稳定分支 ${SANDBOX_SOURCE_BRANCH}，无法创建沙箱。"
  fi
}

# —— 从 main 快照创建沙箱 ——
copy_to_sandbox() {
  require_source_branch
  local source_commit
  source_commit="$(git -C "${PROJECT_DIR}" rev-parse "${SANDBOX_SOURCE_BRANCH}")"
  info "从 ${SANDBOX_SOURCE_BRANCH} (${source_commit:0:12}) 创建 .sandbox …"

  rm -rf "${SANDBOX_DIR}"
  mkdir -p "${SANDBOX_DIR}"

  git -C "${PROJECT_DIR}" archive "${SANDBOX_SOURCE_BRANCH}" \
    | tar -x -C "${SANDBOX_DIR}"

  # .env 始终复制；本地没有时由示例生成，允许以演示模式完成自举。
  if [[ -f "${PROJECT_DIR}/.env" ]]; then
    cp "${PROJECT_DIR}/.env" "${SANDBOX_DIR}/.env"
    success "已复制本地 .env。"
  elif [[ -f "${SANDBOX_DIR}/.env.example" ]]; then
    cp "${SANDBOX_DIR}/.env.example" "${SANDBOX_DIR}/.env"
    warn "本地 .env 不存在，已从 .env.example 创建演示模式配置。"
  else
    die "本地没有 .env，main 快照中也没有 .env.example。"
  fi
  chmod 600 "${SANDBOX_DIR}/.env" 2>/dev/null || true

  printf 'source_branch=%s\nsource_commit=%s\ncreated_at=%s\n' \
    "${SANDBOX_SOURCE_BRANCH}" \
    "${source_commit}" \
    "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" \
    > "${SANDBOX_DIR}/.bootstrap-meta"
  success "main 沙箱快照创建完成。"
}

# —— 本地工作区切换到 dev ——
switch_local_to_dev() {
  local current_branch
  current_branch="$(git -C "${PROJECT_DIR}" branch --show-current)"
  if [[ "${current_branch}" == "${LOCAL_DEVELOPMENT_BRANCH}" ]]; then
    success "本地工作区已位于 ${LOCAL_DEVELOPMENT_BRANCH} 分支。"
    return 0
  fi

  info "将本地工作区从 ${current_branch:-detached HEAD} 切换到 ${LOCAL_DEVELOPMENT_BRANCH} …"
  if git -C "${PROJECT_DIR}" show-ref --verify --quiet \
    "refs/heads/${LOCAL_DEVELOPMENT_BRANCH}"; then
    git -C "${PROJECT_DIR}" switch "${LOCAL_DEVELOPMENT_BRANCH}" \
      || die "无法切换到 dev；请检查本地修改是否与 dev 分支冲突。main 沙箱已保留。"
  else
    git -C "${PROJECT_DIR}" switch -c "${LOCAL_DEVELOPMENT_BRANCH}" \
      "${SANDBOX_SOURCE_BRANCH}" \
      || die "无法从 main 创建 dev 分支。main 沙箱已保留。"
  fi
  success "本地开发分支：${LOCAL_DEVELOPMENT_BRANCH}"
}

# —— 检查沙箱是否存在 ——
require_sandbox() {
  if [[ ! -d "${SANDBOX_DIR}" ]]; then
    die "沙箱目录不存在。请先执行: ./${BOOTSTRAP_NAME} setup"
  fi
}

# —— 读取 PID 文件 ——
read_pid() {
  local pid_file="$1"
  if [[ -f "${pid_file}" ]]; then
    tr -cd '0-9' < "${pid_file}"
  fi
}

# —— 检查进程是否存活（支持 Linux/macOS/Windows） ——
is_running() {
  local pid="$1"
  [[ -z "${pid}" ]] && return 1

  # Unix: kill -0 对 Cygwin/MSYS 进程有效，对原生 Windows 进程无效
  kill -0 "${pid}" 2>/dev/null && return 0

  # Windows 原生进程回退：通过 PowerShell 查询
  if _has_powershell; then
    powershell -NoProfile -Command \
      "Get-Process -Id ${pid} -ErrorAction Stop" >/dev/null 2>&1 && return 0
  fi

  return 1
}

# —— 是否有 PowerShell 可用 ——
_has_powershell() {
  command -v powershell &>/dev/null || [[ -f "$(which powershell 2>/dev/null || echo '')" ]]
}

# —— 获取进程命令行（截断至 100 字符） ——
proc_cmdline() {
  local pid="$1"
  [[ -z "${pid}" ]] && return 1

  # Linux /proc
  if [[ -f "/proc/${pid}/cmdline" ]]; then
    tr '\0' ' ' < "/proc/${pid}/cmdline" 2>/dev/null | sed 's/[[:space:]]\+$//' | cut -c1-100
    return 0
  fi

  # macOS / BSD
  local out
  out="$(ps -p "${pid}" -o command= 2>/dev/null || true)"
  out="$(echo "${out}" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//' | cut -c1-100)"
  if [[ -n "${out}" ]]; then
    echo "${out}"
    return 0
  fi

  # Windows PowerShell
  if _has_powershell; then
    out="$(powershell -NoProfile -Command \
      "Get-Process -Id ${pid} -ErrorAction SilentlyContinue | Select-Object -ExpandProperty CommandLine" 2>/dev/null || true)"
    out="$(echo "${out}" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//' | cut -c1-100)"
    if [[ -n "${out}" ]]; then
      echo "${out}"
      return 0
    fi
    # 回退：只获取进程名
    out="$(powershell -NoProfile -Command \
      "Get-Process -Id ${pid} -ErrorAction SilentlyContinue | Select-Object -ExpandProperty ProcessName" 2>/dev/null || true)"
    out="$(echo "${out}" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
    if [[ -n "${out}" ]]; then
      echo "[${out}] (命令行不可用)"
      return 0
    fi
  fi
  return 1
}

# —— 获取进程运行时长 ——
proc_uptime() {
  local pid="$1"
  [[ -z "${pid}" ]] && return 1

  # Linux: ps etime
  local elapsed
  elapsed="$(ps -p "${pid}" -o etime= 2>/dev/null | tr -d ' ')"
  if [[ -n "${elapsed}" ]]; then
    echo "${elapsed}"
    return 0
  fi

  # macOS
  elapsed="$(ps -p "${pid}" -o lstart= 2>/dev/null | sed 's/^[[:space:]]*//')"
  if [[ -n "${elapsed}" ]]; then
    echo "since ${elapsed}"
    return 0
  fi

  # Windows PowerShell
  if _has_powershell; then
    local start_time
    start_time="$(powershell -NoProfile -Command \
      "Get-Process -Id ${pid} -ErrorAction SilentlyContinue | Select-Object -ExpandProperty StartTime | Get-Date -Format 'yyyy-MM-dd HH:mm:ss'" 2>/dev/null || true)"
    start_time="$(echo "${start_time}" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
    if [[ -n "${start_time}" ]]; then
      echo "since ${start_time}"
      return 0
    fi
  fi
  return 1
}

# —— 验证 PID 是否属于预期服务类型 (python / node) ——
pid_matches_service() {
  local pid="$1"
  local expected="$2"  # python | node
  local cmdline
  cmdline="$(proc_cmdline "${pid}" 2>/dev/null || true)"
  if [[ -z "${cmdline}" ]]; then
    return 1
  fi
  case "${expected}" in
    python) echo "${cmdline}" | grep -qi 'python' ;;
    node)   echo "${cmdline}" | grep -qi 'node' ;;
    *)      return 1 ;;
  esac
}

# —— 格式化显示单个服务状态 ——
# 参数: $1=服务名(backend/frontend), $2=预期类型(python/node)
print_service_status() {
  local name="$1"
  local svc_type="$2"
  local run_dir="${SANDBOX_DIR}/.run"
  local pid_file="${run_dir}/${name}.pid"
  local pid=""

  if [[ -f "${pid_file}" ]]; then
    pid="$(tr -cd '0-9' < "${pid_file}")"
  fi

  if [[ -n "${pid}" ]] && is_running "${pid}"; then
    # 进程存活，验证是否属于预期服务
    local cmdline uptime
    cmdline="$(proc_cmdline "${pid}" 2>/dev/null || true)"
    uptime="$(proc_uptime "${pid}" 2>/dev/null || true)"

    echo -e "  ${name}:  ${GREEN}运行中${NC}"
    echo    "           PID:      ${pid}"
    [[ -n "${uptime}" ]]  && echo "           运行时长: ${uptime}"
    [[ -n "${cmdline}" ]] && echo "           命令:     ${cmdline}"

    # 验证 PID 是否匹配预期服务类型
    if ! pid_matches_service "${pid}" "${svc_type}"; then
      echo -e "           ${YELLOW}⚠ 警告: 该 PID 似乎不属于 ${svc_type} 进程${NC}"
    fi
  elif [[ -f "${pid_file}" ]]; then
    # PID 文件存在但进程已死 — 僵尸 PID
    echo -e "  ${name}:  ${RED}已停止${NC}  (PID 文件残留: ${pid:-无}, 进程已退出)"
  else
    # 无 PID 文件 — 从未启动
    echo -e "  ${name}:  ${RED}未启动${NC}  (无 PID 文件)"
  fi
}

# —— setup: 强制重建沙箱 ——
cmd_setup() {
  if [[ -d "${SANDBOX_DIR}" ]]; then
    warn "检测到现有沙箱，正在删除…"
    # 先尝试停止沙箱内可能还在跑的服务
    cmd_stop 2>/dev/null || true
    rm -rf "${SANDBOX_DIR}"
  fi
  copy_to_sandbox
  switch_local_to_dev
  success "沙箱已就绪: ${SANDBOX_DIR}"
}

# —— start: 在沙箱内启动服务 ——
cmd_start() {
  require_sandbox
  info "在沙箱内启动 Agent Studio …"
  cd "${SANDBOX_DIR}"
  exec bash start.sh
}

# —— stop: 停止沙箱内服务 ——
cmd_stop() {
  require_sandbox
  info "停止沙箱内服务…"
  cd "${SANDBOX_DIR}"
  if [[ -f "stop.sh" ]]; then
    bash stop.sh
  else
    # fallback: 直接按 PID 停止
    local run_dir="${SANDBOX_DIR}/.run"
    for name in backend frontend; do
      local pid
      pid="$(read_pid "${run_dir}/${name}.pid" || echo "")"
      if is_running "${pid}"; then
        kill "${pid}" 2>/dev/null || true
        for _ in {1..20}; do
          is_running "${pid}" || break
          sleep 0.1
        done
        info "已停止 ${name} (PID ${pid})"
      fi
    done
  fi
  success "沙箱服务已停止。"
}

# —— restart: 停止后重新启动 ——
cmd_restart() {
  cmd_stop
  sleep 1
  cmd_start
}

# —— destroy: 删除沙箱 ——
cmd_destroy() {
  if [[ ! -d "${SANDBOX_DIR}" ]]; then
    warn "沙箱目录不存在，无需删除。"
    return 0
  fi
  warn "正在销毁沙箱…"
  cmd_stop 2>/dev/null || true
  rm -rf "${SANDBOX_DIR}"
  success "沙箱已销毁。"
}

# —— status: 查看沙箱状态 ——
cmd_status() {
  echo "════════════════════════════════════════"
  echo "  Agent Studio 沙箱状态"
  echo "════════════════════════════════════════"

  # 沙箱目录
  if [[ -d "${SANDBOX_DIR}" ]]; then
    echo -e "  沙箱目录:  ${GREEN}存在${NC}  (${SANDBOX_DIR})"
    if [[ -f "${SANDBOX_DIR}/.bootstrap-meta" ]]; then
      local source_branch source_commit
      source_branch="$(sed -n 's/^source_branch=//p' "${SANDBOX_DIR}/.bootstrap-meta")"
      source_commit="$(sed -n 's/^source_commit=//p' "${SANDBOX_DIR}/.bootstrap-meta")"
      echo "  稳定快照:  ${source_branch:-未知} @ ${source_commit:0:12}"
    fi

    # 计算目录大小
    local size
    size="$(du -sh "${SANDBOX_DIR}" 2>/dev/null | cut -f1 || echo "未知")"
    echo "  目录大小:  ${size}"

    # 最后 setup 时间（取最老的文件修改时间作为近似）
    local mtime
    mtime="$(stat -c '%Y' "${SANDBOX_DIR}" 2>/dev/null || stat -f '%m' "${SANDBOX_DIR}" 2>/dev/null || echo "0")"
    if [[ "${mtime}" != "0" ]]; then
      echo "  创建时间:  $(date -d "@${mtime}" '+%Y-%m-%d %H:%M:%S' 2>/dev/null || date -r "${mtime}" '+%Y-%m-%d %H:%M:%S' 2>/dev/null || echo "未知")"
    fi
  else
    echo -e "  沙箱目录:  ${RED}不存在${NC}"
    echo "════════════════════════════════════════"
    return 0
  fi

  # 服务进程状态
  echo "  ──────────────────────────────────"
  echo "  服务进程:"
  print_service_status backend python
  print_service_status frontend node

  # 端口占用检查
  echo "  ──────────────────────────────────"
  echo "  端口监听:"
  # 收集运行中服务的 PID 用于端口匹配
  local run_dir="${SANDBOX_DIR}/.run"
  local bk_pid fe_pid
  bk_pid="$(cat "${run_dir}/backend.pid" 2>/dev/null | tr -cd '0-9' || echo "")"
  fe_pid="$(cat "${run_dir}/frontend.pid" 2>/dev/null | tr -cd '0-9' || echo "")"
  is_running "${bk_pid}" || bk_pid=""
  is_running "${fe_pid}" || fe_pid=""

  local runtime_env="${run_dir}/runtime.env"
  local port_env="${SANDBOX_DIR}/.env"
  [[ -f "${runtime_env}" ]] && port_env="${runtime_env}"
  local backend_port frontend_port
  backend_port="$(
    sed -n 's/^BACKEND_PORT=//p' "${port_env}" 2>/dev/null | tail -1
  )"
  frontend_port="$(
    sed -n 's/^FRONTEND_PORT=//p' "${port_env}" 2>/dev/null | tail -1
  )"
  backend_port="${backend_port:-5000}"
  frontend_port="${frontend_port:-5173}"
  local port_labels="${backend_port}:backend:${bk_pid} ${frontend_port}:frontend:${fe_pid}"
  for entry in ${port_labels}; do
    local port="${entry%%:*}"
    local rest="${entry#*:}"
    local label="${rest%%:*}"
    local expected_pid="${rest##*:}"

    local listener
    listener=""
    if command -v lsof >/dev/null 2>&1; then
      listener="$(lsof -nP -iTCP:"${port}" -sTCP:LISTEN 2>/dev/null | tail -n +2 | head -1 || true)"
    fi
    if [[ -z "${listener}" ]]; then
      listener="$(netstat -ano 2>/dev/null | grep ":${port} " | grep LISTEN | head -1 || true)"
    fi
    if [[ -z "${listener}" ]] && command -v ss >/dev/null 2>&1; then
      listener="$(ss -tlnp 2>/dev/null | grep ":${port} " | head -1 || true)"
    fi

    if [[ -n "${listener}" ]]; then
      # 检查监听 PID 是否匹配
      if [[ -n "${expected_pid}" ]] && echo "${listener}" | grep -q "${expected_pid}"; then
        echo -e "    :${port} → ${GREEN}${listener}${NC}"
      else
        echo -e "    :${port} → ${listener}"
        if [[ -n "${expected_pid}" ]]; then
          echo -e "           ${YELLOW}⚠ 监听 PID 与 ${label} PID 文件不匹配${NC}"
        fi
      fi
    else
      echo -e "    :${port} → ${RED}无监听${NC}"
    fi
  done

  echo "════════════════════════════════════════"
}

# —— 主入口 ——
main() {
  local cmd="${1:-}"

  case "${cmd}" in
    setup)
      cmd_setup
      ;;
    start)
      cmd_start
      ;;
    stop)
      cmd_stop
      ;;
    restart)
      cmd_restart
      ;;
    destroy)
      cmd_destroy
      ;;
    status)
      cmd_status
      ;;
    help|--help|-h)
      show_help
      ;;
    "")
      # 默认：一键自举
      info "一键自举模式: setup → start"
      echo ""
      cmd_setup
      echo ""
      cmd_start
      ;;
    *)
      error "未知子命令: ${cmd}"
      echo ""
      show_help
      exit 1
      ;;
  esac
}

main "$@"
