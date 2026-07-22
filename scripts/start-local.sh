#!/usr/bin/env bash
# 安装缺失依赖并同时启动 Flask 与 Vue。所有监听地址都固定为 127.0.0.1。
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="${PROJECT_DIR}/backend"
FRONTEND_DIR="${PROJECT_DIR}/frontend"
RUN_DIR="${PROJECT_DIR}/.run"
VENV_DIR="${BACKEND_DIR}/.venv"

mkdir -p "${RUN_DIR}"

if [[ -f "${PROJECT_DIR}/.env" ]]; then
  # shellcheck disable=SC1091
  set -a
  source "${PROJECT_DIR}/.env"
  set +a
fi

BACKEND_HOST="${BACKEND_HOST:-127.0.0.1}"
BACKEND_PORT="${BACKEND_PORT:-5000}"
FRONTEND_HOST="${FRONTEND_HOST:-127.0.0.1}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"

case "${BACKEND_HOST}" in
  127.0.0.1|localhost|::1) ;;
  *) echo "拒绝启动：BACKEND_HOST 必须是本机回环地址。" >&2; exit 1 ;;
esac
case "${FRONTEND_HOST}" in
  127.0.0.1|localhost|::1) ;;
  *) echo "拒绝启动：FRONTEND_HOST 必须是本机回环地址。" >&2; exit 1 ;;
esac

if [[ ! -x "${VENV_DIR}/bin/python" ]]; then
  echo "[setup] 创建 Python 虚拟环境…"
  python3 -m venv "${VENV_DIR}"
fi

if [[ ! -f "${VENV_DIR}/.dependencies-ready" || "${BACKEND_DIR}/pyproject.toml" -nt "${VENV_DIR}/.dependencies-ready" ]]; then
  echo "[setup] 安装后端依赖…"
  # macOS 上部分独立 Python 发行版没有连接系统钥匙串。certifi 随现有
  # Python 环境提供 Mozilla CA 集合，显式传给 pip 可继续保持严格 TLS 校验。
  PIP_CA_BUNDLE="$("${VENV_DIR}/bin/python" -c 'import certifi; print(certifi.where())')"
  PIP_CERT="${PIP_CA_BUNDLE}" "${VENV_DIR}/bin/python" -m pip install --quiet --upgrade pip
  PIP_CERT="${PIP_CA_BUNDLE}" "${VENV_DIR}/bin/python" -m pip install --quiet -e "${BACKEND_DIR}[dev]"
  touch "${VENV_DIR}/.dependencies-ready"
fi

if [[ ! -d "${FRONTEND_DIR}/node_modules" || "${FRONTEND_DIR}/package.json" -nt "${FRONTEND_DIR}/node_modules" ]]; then
  echo "[setup] 安装前端依赖…"
  npm --prefix "${FRONTEND_DIR}" install --silent
fi

cleanup() {
  "${PROJECT_DIR}/scripts/stop-local.sh" >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

echo "[start] 启动后端 http://${BACKEND_HOST}:${BACKEND_PORT}"
(
  cd "${BACKEND_DIR}"
  exec "${VENV_DIR}/bin/python" run.py
) >"${RUN_DIR}/backend.log" 2>&1 &
BACKEND_PID=$!
echo "${BACKEND_PID}" > "${RUN_DIR}/backend.pid"

echo "[start] 启动前端 http://${FRONTEND_HOST}:${FRONTEND_PORT}"
(
  cd "${FRONTEND_DIR}"
  exec npm run dev -- --host "${FRONTEND_HOST}" --port "${FRONTEND_PORT}" --strictPort
) >"${RUN_DIR}/frontend.log" 2>&1 &
FRONTEND_PID=$!
echo "${FRONTEND_PID}" > "${RUN_DIR}/frontend.pid"

# 等待子进程完成初始化；提前退出时直接展示日志，避免给出一个不可用地址。
for _ in {1..40}; do
  if ! kill -0 "${BACKEND_PID}" 2>/dev/null; then
    echo "后端启动失败：" >&2
    tail -n 30 "${RUN_DIR}/backend.log" >&2
    exit 1
  fi
  if ! kill -0 "${FRONTEND_PID}" 2>/dev/null; then
    echo "前端启动失败：" >&2
    tail -n 30 "${RUN_DIR}/frontend.log" >&2
    exit 1
  fi
  if curl --silent --fail "http://${BACKEND_HOST}:${BACKEND_PORT}/health" >/dev/null 2>&1 \
    && curl --silent --fail "http://${FRONTEND_HOST}:${FRONTEND_PORT}" >/dev/null 2>&1; then
    break
  fi
  sleep 0.25
done

echo
echo "Agent Studio 已启动：http://${FRONTEND_HOST}:${FRONTEND_PORT}"
echo "按 Ctrl+C 同时停止前后端。日志位于 ${RUN_DIR}。"
echo

# wait 能让脚本持续拥有两个进程，并确保 Ctrl+C 时 trap 可靠清理。
wait "${BACKEND_PID}" "${FRONTEND_PID}"
