#!/usr/bin/env bash
# 安装缺失依赖并同时启动 Flask 与 Vue。所有监听地址都固定为本机回环地址。
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="${PROJECT_DIR}/backend"
FRONTEND_DIR="${PROJECT_DIR}/frontend"
RUN_DIR="${PROJECT_DIR}/.run"
VENV_DIR="${BACKEND_DIR}/.venv"

if [[ "$(uname -s)" == MINGW* || "$(uname -s)" == MSYS* || "$(uname -s)" == CYGWIN* ]]; then
  VENV_PYTHON="${VENV_DIR}/Scripts/python.exe"
  PYTHON3_CMD="${PYTHON3_CMD:-python}"
else
  VENV_PYTHON="${VENV_DIR}/bin/python"
  PYTHON3_CMD="${PYTHON3_CMD:-python3}"
fi

die() {
  echo "[error] $*" >&2
  exit 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || die "缺少必需命令：$1"
}

check_python_version() {
  "${PYTHON3_CMD}" -c '
import sys
if sys.version_info < (3, 11):
    raise SystemExit(f"需要 Python >= 3.11，当前为 {sys.version.split()[0]}")
'
}

check_node_version() {
  node -e '
const [major, minor] = process.versions.node.split(".").map(Number);
if (!((major === 20 && minor >= 19) || major >= 22)) {
  console.error(`需要 Node ^20.19.0 或 >=22.12.0，当前为 ${process.versions.node}`);
  process.exit(1);
}
'
}

require_command "${PYTHON3_CMD}"
require_command node
require_command npm
require_command curl
check_python_version
check_node_version

mkdir -p "${RUN_DIR}"

# 调用方显式传入的端口优先于 .env，方便 CI、自举沙箱和并行开发实例使用。
OVERRIDE_BACKEND_HOST="${BACKEND_HOST-}"
OVERRIDE_BACKEND_PORT="${BACKEND_PORT-}"
OVERRIDE_FRONTEND_HOST="${FRONTEND_HOST-}"
OVERRIDE_FRONTEND_PORT="${FRONTEND_PORT-}"
if [[ -f "${PROJECT_DIR}/.env" ]]; then
  # shellcheck disable=SC1091
  set -a
  source "${PROJECT_DIR}/.env"
  set +a
fi
[[ -n "${OVERRIDE_BACKEND_HOST}" ]] && BACKEND_HOST="${OVERRIDE_BACKEND_HOST}"
[[ -n "${OVERRIDE_BACKEND_PORT}" ]] && BACKEND_PORT="${OVERRIDE_BACKEND_PORT}"
[[ -n "${OVERRIDE_FRONTEND_HOST}" ]] && FRONTEND_HOST="${OVERRIDE_FRONTEND_HOST}"
[[ -n "${OVERRIDE_FRONTEND_PORT}" ]] && FRONTEND_PORT="${OVERRIDE_FRONTEND_PORT}"

BACKEND_HOST="${BACKEND_HOST:-127.0.0.1}"
BACKEND_PORT="${BACKEND_PORT:-5000}"
FRONTEND_HOST="${FRONTEND_HOST:-127.0.0.1}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"

case "${BACKEND_HOST}" in
  127.0.0.1|localhost|::1) ;;
  *) die "BACKEND_HOST 必须是本机回环地址。" ;;
esac
case "${FRONTEND_HOST}" in
  127.0.0.1|localhost|::1) ;;
  *) die "FRONTEND_HOST 必须是本机回环地址。" ;;
esac
[[ "${BACKEND_PORT}" =~ ^[0-9]+$ ]] || die "BACKEND_PORT 必须是数字。"
[[ "${FRONTEND_PORT}" =~ ^[0-9]+$ ]] || die "FRONTEND_PORT 必须是数字。"
BACKEND_URL_HOST="${BACKEND_HOST}"
FRONTEND_URL_HOST="${FRONTEND_HOST}"
[[ "${BACKEND_HOST}" == "::1" ]] && BACKEND_URL_HOST="[::1]"
[[ "${FRONTEND_HOST}" == "::1" ]] && FRONTEND_URL_HOST="[::1]"

if [[ ! -x "${VENV_PYTHON}" ]]; then
  echo "[setup] 创建 Python 虚拟环境…"
  "${PYTHON3_CMD}" -m venv "${VENV_DIR}"
fi

BACKEND_SIGNATURE="$(
  "${VENV_PYTHON}" - "${BACKEND_DIR}/pyproject.toml" <<'PY'
import hashlib
import pathlib
import sys

digest = hashlib.sha256()
for value in sys.argv[1:]:
    digest.update(pathlib.Path(value).read_bytes())
digest.update(sys.version.encode())
print(digest.hexdigest())
PY
)"
BACKEND_MARKER="${VENV_DIR}/.dependencies-ready"
if [[ ! -f "${BACKEND_MARKER}" || "$(<"${BACKEND_MARKER}")" != "${BACKEND_SIGNATURE}" ]]; then
  echo "[setup] 安装后端依赖…"
  PIP_CA_BUNDLE="$("${VENV_PYTHON}" -c 'import certifi; print(certifi.where())' 2>/dev/null || echo "")"
  (
    cd "${BACKEND_DIR}"
    if [[ -n "${PIP_CA_BUNDLE}" ]]; then
      PIP_CERT="${PIP_CA_BUNDLE}" "${VENV_PYTHON}" -m pip install --upgrade pip --no-input
      PIP_CERT="${PIP_CA_BUNDLE}" "${VENV_PYTHON}" -m pip install -e ".[dev]" --no-input
    else
      "${VENV_PYTHON}" -m pip install --upgrade pip --no-input
      "${VENV_PYTHON}" -m pip install -e ".[dev]" --no-input
    fi
  )
  printf '%s\n' "${BACKEND_SIGNATURE}" > "${BACKEND_MARKER}"
fi

FRONTEND_SIGNATURE="$(
  node - "${FRONTEND_DIR}/package.json" "${FRONTEND_DIR}/package-lock.json" <<'JS'
const crypto = require("node:crypto");
const fs = require("node:fs");
const files = process.argv.slice(2).filter(file => fs.existsSync(file));
const hash = crypto.createHash("sha256");
for (const file of files) hash.update(fs.readFileSync(file));
hash.update(process.version);
process.stdout.write(hash.digest("hex"));
JS
)"
FRONTEND_MARKER="${FRONTEND_DIR}/node_modules/.dependencies-ready"
if [[ ! -f "${FRONTEND_MARKER}" || "$(<"${FRONTEND_MARKER}")" != "${FRONTEND_SIGNATURE}" ]]; then
  echo "[setup] 安装前端依赖…"
  if [[ -f "${FRONTEND_DIR}/package-lock.json" ]]; then
    npm --prefix "${FRONTEND_DIR}" ci --loglevel error
  else
    npm --prefix "${FRONTEND_DIR}" install --loglevel error
  fi
  printf '%s\n' "${FRONTEND_SIGNATURE}" > "${FRONTEND_MARKER}"
fi

# 清理本项目上一次遗留且能够验证归属的 PID 文件。
if ! "${PROJECT_DIR}/scripts/stop-local.sh" --quiet; then
  die "检测到无法验证归属的 PID 文件，请人工检查 ${RUN_DIR}。"
fi

cleanup() {
  "${PROJECT_DIR}/scripts/stop-local.sh" --quiet >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

record_process_identity() {
  local name="$1"
  local pid="$2"
  local started
  started="$(ps -p "${pid}" -o lstart= 2>/dev/null | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
  [[ -n "${started}" ]] || die "无法读取 ${name} 进程启动时间。"
  printf '%s\n' "${started}" > "${RUN_DIR}/${name}.started"
}

printf 'BACKEND_HOST=%s\nBACKEND_PORT=%s\nFRONTEND_HOST=%s\nFRONTEND_PORT=%s\n' \
  "${BACKEND_HOST}" \
  "${BACKEND_PORT}" \
  "${FRONTEND_HOST}" \
  "${FRONTEND_PORT}" \
  > "${RUN_DIR}/runtime.env"

echo "[start] 启动后端 http://${BACKEND_URL_HOST}:${BACKEND_PORT}"
(
  cd "${BACKEND_DIR}"
  exec "${VENV_PYTHON}" run.py
) >"${RUN_DIR}/backend.log" 2>&1 &
BACKEND_PID=$!
printf '%s\n' "${BACKEND_PID}" > "${RUN_DIR}/backend.pid"
record_process_identity backend "${BACKEND_PID}"

echo "[start] 启动前端 http://${FRONTEND_URL_HOST}:${FRONTEND_PORT}"
(
  cd "${FRONTEND_DIR}"
  exec node "${FRONTEND_DIR}/node_modules/vite/bin/vite.js" \
    --host "${FRONTEND_HOST}" \
    --port "${FRONTEND_PORT}" \
    --strictPort
) >"${RUN_DIR}/frontend.log" 2>&1 &
FRONTEND_PID=$!
printf '%s\n' "${FRONTEND_PID}" > "${RUN_DIR}/frontend.pid"
record_process_identity frontend "${FRONTEND_PID}"

READY=0
for _ in {1..120}; do
  if ! kill -0 "${BACKEND_PID}" 2>/dev/null; then
    echo "后端启动失败（日志：${RUN_DIR}/backend.log）：" >&2
    tail -n 30 "${RUN_DIR}/backend.log" >&2
    exit 1
  fi
  if ! kill -0 "${FRONTEND_PID}" 2>/dev/null; then
    echo "前端启动失败（日志：${RUN_DIR}/frontend.log）：" >&2
    tail -n 30 "${RUN_DIR}/frontend.log" >&2
    exit 1
  fi
  if curl --silent --fail "http://${BACKEND_URL_HOST}:${BACKEND_PORT}/health" >/dev/null 2>&1 \
    && curl --silent --fail "http://${FRONTEND_URL_HOST}:${FRONTEND_PORT}" >/dev/null 2>&1; then
    READY=1
    break
  fi
  sleep 0.25
done

if [[ "${READY}" != "1" ]]; then
  echo "服务在 30 秒内未通过健康检查。" >&2
  echo "后端日志：${RUN_DIR}/backend.log" >&2
  tail -n 20 "${RUN_DIR}/backend.log" >&2 || true
  echo "前端日志：${RUN_DIR}/frontend.log" >&2
  tail -n 20 "${RUN_DIR}/frontend.log" >&2 || true
  exit 1
fi

echo
echo "Agent Studio 已启动：http://${FRONTEND_URL_HOST}:${FRONTEND_PORT}"
echo "按 Ctrl+C 同时停止前后端。日志位于 ${RUN_DIR}。"
echo

# 兼容 macOS 自带 Bash 3：轮询两个精确子进程，任一退出就结束并由 trap 清理另一个。
while kill -0 "${BACKEND_PID}" 2>/dev/null && kill -0 "${FRONTEND_PID}" 2>/dev/null; do
  sleep 0.5
done

EXIT_CODE=0
if ! kill -0 "${BACKEND_PID}" 2>/dev/null; then
  wait "${BACKEND_PID}" || EXIT_CODE=$?
  [[ "${EXIT_CODE}" == "0" ]] || tail -n 30 "${RUN_DIR}/backend.log" >&2
else
  wait "${FRONTEND_PID}" || EXIT_CODE=$?
  [[ "${EXIT_CODE}" == "0" ]] || tail -n 30 "${RUN_DIR}/frontend.log" >&2
fi
exit "${EXIT_CODE}"
