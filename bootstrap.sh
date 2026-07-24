#!/usr/bin/env bash
# ============================================================
# Agent Studio Bootstrap — 自举沙箱管理脚本
# ============================================================
# 将当前 Git 干净状态的代码复制到 .sandbox 沙箱目录中隔离
# 运行。所有服务在沙箱内启动，与开发环境互不干扰。
#
# 用法:
#   ./bootstrap.sh             一键自举（setup → start）
#   ./bootstrap.sh setup       强制重建沙箱（需 Git 干净）
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
  echo "  setup      强制重建沙箱（检查 Git 干净，删除旧沙箱，重新复制）"
  echo "  start      在沙箱内启动前后端服务"
  echo "  stop       停止沙箱内服务"
  echo "  restart    停止后重新启动"
  echo "  destroy    删除 .sandbox 目录"
  echo "  status     查看沙箱状态（是否存在、服务是否运行）"
  echo
  echo "不带参数默认执行: setup → start"
}

# —— Git 干净检查 ——
check_git_clean() {
  info "检查 Git 工作区状态…"
  local dirty
  dirty="$(cd "${PROJECT_DIR}" && git status --porcelain 2>/dev/null || true)"

  # 过滤掉 .sandbox/ 下的变更（沙箱自身不应阻止自举）
  dirty="$(echo "${dirty}" | grep -v '^[? ].*\.sandbox/' || true)"

  if [[ -n "${dirty}" ]]; then
    error "Git 工作区不干净！自举需要干净的 Git 状态以确保代码快照一致。"
    echo ""
    echo "  当前有未提交的变更:"
    echo "${dirty}" | while read -r line; do
      echo "    ${line}"
    done
    echo ""
    echo "  请先处理以上变更（提交或暂存），再执行自举。"
    die "自举中止：工作区不干净。"
  fi
  success "Git 工作区干净。"
}

# —— 复制文件到沙箱 ——
copy_to_sandbox() {
  info "复制项目文件到 .sandbox …"

  rm -rf "${SANDBOX_DIR}"
  mkdir -p "${SANDBOX_DIR}"

  local copied=0
  local skipped=0

  # 1) 复制所有 Git 追踪的文件
  cd "${PROJECT_DIR}"
  while IFS= read -r file; do
    # 跳过 bootstrap.sh 自身
    if [[ "${file}" == "${BOOTSTRAP_NAME}" ]]; then
      skipped=$((skipped + 1))
      continue
    fi
    # 跳过 .sandbox 目录下的任何内容（理论上 git ls-files 不会输出）
    if [[ "${file}" == .sandbox/* || "${file}" == ".sandbox" ]]; then
      skipped=$((skipped + 1))
      continue
    fi

    local dest="${SANDBOX_DIR}/${file}"
    mkdir -p "$(dirname "${dest}")"
    cp "${file}" "${dest}"
    copied=$((copied + 1))
  done < <(git ls-files)

  # 2) 复制 .env（如果存在），这是运行时必需的非追踪文件
  if [[ -f "${PROJECT_DIR}/.env" ]]; then
    cp "${PROJECT_DIR}/.env" "${SANDBOX_DIR}/.env"
    info "已复制 .env（运行时环境变量）"
  else
    warn ".env 不存在，沙箱将缺少 API Key 等环境变量。"
    warn "请确保在沙箱内手动创建 .env 或通过其他方式提供环境变量。"
  fi

  # 3) 复制 .claude/ 目录（如果存在且被 gitignore 排除但实际需要）
  # 注意：git ls-files 已经包含了被追踪的 .claude/ 下的文件
  # 如果有未被追踪但需要的 .claude 文件，可以在这里补充

  success "沙箱创建完成：${copied} 个文件已复制，${skipped} 个文件已跳过。"
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
  check_git_clean
  if [[ -d "${SANDBOX_DIR}" ]]; then
    warn "检测到现有沙箱，正在删除…"
    # 先尝试停止沙箱内可能还在跑的服务
    cmd_stop 2>/dev/null || true
    rm -rf "${SANDBOX_DIR}"
  fi
  copy_to_sandbox
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

  local port_labels="5000:backend:${bk_pid} 5173:frontend:${fe_pid}"
  for entry in ${port_labels}; do
    local port="${entry%%:*}"
    local rest="${entry#*:}"
    local label="${rest%%:*}"
    local expected_pid="${rest##*:}"

    local listener
    listener="$(netstat -ano 2>/dev/null | grep ":${port} " | grep LISTEN | head -1 || true)"
    if [[ -z "${listener}" ]]; then
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
