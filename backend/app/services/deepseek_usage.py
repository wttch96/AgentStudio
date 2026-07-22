"""持久化 DeepSeek 响应 token，并按本地配置单价估算费用。"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from app.config import Settings
from app.storage.sqlite_store import SQLiteStore


class DeepSeekUsageService:
    def __init__(self, settings: Settings, store: SQLiteStore) -> None:
        self.settings = settings
        self.store = store

    def record(self, response: Any, *, phase: str, run_id: str | None) -> None:
        usage = getattr(response, "usage", None)
        if usage is None:
            return
        values = usage.model_dump() if hasattr(usage, "model_dump") else vars(usage)
        prompt = int(values.get("prompt_tokens") or 0)
        cache_hit = int(values.get("prompt_cache_hit_tokens") or 0)
        cache_miss = int(values.get("prompt_cache_miss_tokens") or max(prompt - cache_hit, 0))
        completion = int(values.get("completion_tokens") or 0)
        total = int(values.get("total_tokens") or prompt + completion)
        million = Decimal("1000000")
        cost = (
            Decimal(cache_hit) * Decimal(str(self.settings.deepseek_cache_hit_price))
            + Decimal(cache_miss) * Decimal(str(self.settings.deepseek_cache_miss_price))
            + Decimal(completion) * Decimal(str(self.settings.deepseek_output_price))
        ) / million
        self.store.append_deepseek_usage(
            {
                "run_id": run_id,
                "phase": phase,
                "model": getattr(response, "model", None) or self.settings.deepseek_model,
                "prompt_tokens": prompt,
                "cache_hit_tokens": cache_hit,
                "cache_miss_tokens": cache_miss,
                "completion_tokens": completion,
                "total_tokens": total,
                "estimated_cost_usd": float(cost),
                "occurred_at": datetime.now().astimezone().isoformat(),
            }
        )

    def summary(self) -> dict[str, Any]:
        now = datetime.now().astimezone()
        today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        month = today.replace(day=1)
        return {
            "local": True,
            "estimated": True,
            "model": self.settings.deepseek_model,
            "today": self.store.summarize_deepseek_usage(today.isoformat()),
            "month": self.store.summarize_deepseek_usage(month.isoformat()),
            "all_time": self.store.summarize_deepseek_usage(),
            "pricing_usd_per_million": {
                "cache_hit": self.settings.deepseek_cache_hit_price,
                "cache_miss": self.settings.deepseek_cache_miss_price,
                "output": self.settings.deepseek_output_price,
            },
        }
