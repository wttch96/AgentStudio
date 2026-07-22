#!/usr/bin/env bash
# 停止一键启动脚本创建的本地进程。
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "${PROJECT_DIR}/scripts/stop-local.sh"

