"""持久化记忆系统配置。文件为 .agent-studio/memory.yaml。"""

from __future__ import annotations

from pathlib import Path
from threading import RLock

from app.domain.configuration import MemoryConfiguration
from app.services.config_reader import ConfigReader


DEFAULT_MEMORY_CONFIG = MemoryConfiguration(
    compress_trigger_tokens=8000,
    compress_keep_recent=20,
    summarizer_model="deepseek-v4-pro",
    max_conversation_turns=100,
    session_archive_after_hours=24,
    importance_decay_rate=0.95,
)


class MemorySettings:
    """持久化记忆配置，文件为 .agent-studio/memory.yaml。"""

    def __init__(self, config_reader: ConfigReader | None = None) -> None:
        self.config_reader = config_reader
        self._lock = RLock()

    def current(self, project_id: str = "") -> MemoryConfiguration:
        with self._lock:
            if self.config_reader:
                reader = self.config_reader.for_project(project_id) if project_id else self.config_reader
                data = reader.read_setting("memory")
                if data:
                    return MemoryConfiguration.model_validate(data)
            return DEFAULT_MEMORY_CONFIG.model_copy()

    def default(self) -> MemoryConfiguration:
        return DEFAULT_MEMORY_CONFIG.model_copy()

    def update(self, configuration: MemoryConfiguration, project_id: str = "") -> MemoryConfiguration:
        with self._lock:
            if self.config_reader:
                reader = self.config_reader.for_project(project_id) if project_id else self.config_reader
                reader._ensure_dirs()
                reader.write_setting("memory", configuration.model_dump())
        return configuration.model_copy()
