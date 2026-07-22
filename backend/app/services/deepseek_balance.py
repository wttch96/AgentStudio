"""查询 DeepSeek 官方账户余额，绝不向前端暴露 API Key。"""

from __future__ import annotations

import time
from threading import RLock
from typing import Any

import httpx

from app.config import Settings


class DeepSeekBalanceService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._lock = RLock()
        self._cache: tuple[float, dict[str, Any]] | None = None

    def current(self, *, refresh: bool = False) -> dict[str, Any]:
        if not self.settings.deepseek_api_key:
            return {
                "configured": False,
                "available": False,
                "infos": [],
                "error": "DeepSeek API Key 未配置",
            }
        with self._lock:
            if not refresh and self._cache and time.monotonic() - self._cache[0] < 60:
                return self._cache[1]

        try:
            # httpx 使用随包维护的 CA 证书集合，避免 macOS 上独立 Python 环境
            # 缺少系统根证书时，urllib 对正常 HTTPS 站点误报证书校验失败。
            response = httpx.get(
                f"{self.settings.deepseek_base_url.rstrip('/')}/user/balance",
                headers={
                    "Accept": "application/json",
                    "Authorization": f"Bearer {self.settings.deepseek_api_key}",
                },
                timeout=15,
            )
            response.raise_for_status()
            payload = response.json()
            result = {
                "configured": True,
                "available": bool(payload.get("is_available")),
                "infos": payload.get("balance_infos", []),
                "error": None,
            }
        except (httpx.HTTPError, ValueError) as error:
            result = {
                "configured": True,
                "available": False,
                "infos": [],
                "error": f"{type(error).__name__}: {str(error) or repr(error)}",
            }
        with self._lock:
            self._cache = (time.monotonic(), result)
        return result
