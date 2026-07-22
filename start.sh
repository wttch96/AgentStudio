#!/usr/bin/env bash
# 根目录快捷入口；具体逻辑保持在 scripts/ 中，方便后续扩展而不让单个脚本膨胀。
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "${PROJECT_DIR}/scripts/start-local.sh"

