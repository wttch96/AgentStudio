"""持久化记忆系统配置，模式与 BrainSettings / SchedulerSettings 一致。"""

from __future__ import annotations

import json
from pathlib import Path
from threading import RLock

from app.domain.configuration import MemoryConfiguration


DEFAULT_MEMORY_CONFIG = MemoryConfiguration(
    compress_trigger_tokens=8000,
    compress_keep_recent=20,
    summarizer_model="deepseek-chat",
    max_conversation_turns=100,
    session_archive_after_hours=24,
    importance_decay_rate=0.95,
)


class MemorySettings:
    """持久化记忆配置，每次运行读取一次。"""

    def __init__(self, config_path: Path | None = None, store=None,
                 config_key: str = "memory") -> None:
        self.config_path = config_path
        self.store = store
        self.config_key = config_key
        self._lock = RLock()

    def current(self) -> MemoryConfiguration:
        with self._lock:
            if self.store:
                self.store.migrate_config_from_file(self.config_key, str(self.config_path)) if self.config_path else None
                data = self.store.get_config(self.config_key)
                if data:
                    return MemoryConfiguration.model_validate(data)
            if self.config_path and self.config_path.exists():
                try:
                    payload = json.loads(self.config_path.read_text(encoding="utf-8"))
                    return MemoryConfiguration.model_validate(payload)
                except (OSError, ValueError, json.JSONDecodeError):
                    pass
            return DEFAULT_MEMORY_CONFIG.model_copy()

    def default(self) -> MemoryConfiguration:
        return DEFAULT_MEMORY_CONFIG.model_copy()

    def update(self, configuration: MemoryConfiguration) -> MemoryConfiguration:
        with self._lock:
            if self.store:
                self.store.set_config(self.config_key, configuration.model_dump())
            elif self.config_path:
                self.config_path.parent.mkdir(parents=True, exist_ok=True)
                temporary = self.config_path.with_suffix(".json.tmp")
                temporary.write_text(
                    json.dumps(configuration.model_dump(), ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                temporary.replace(self.config_path)
        return configuration.model_copy()
