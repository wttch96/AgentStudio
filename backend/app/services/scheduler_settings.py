"""持久化 LangGraph 调度参数，并为每次运行提供不可变配置快照。"""

from __future__ import annotations

import json
from pathlib import Path
from threading import RLock

from app.domain.configuration import SchedulerConfiguration


class SchedulerSettings:
    def __init__(
        self,
        config_path: Path | None = None,
        defaults: SchedulerConfiguration | None = None,
        store=None,
        config_key: str = "scheduler",
    ) -> None:
        self.config_path = config_path
        self.defaults = defaults or SchedulerConfiguration()
        self.store = store
        self.config_key = config_key
        self._lock = RLock()

    def current(self) -> SchedulerConfiguration:
        with self._lock:
            if self.store:
                self.store.migrate_config_from_file(self.config_key, str(self.config_path)) if self.config_path else None
                data = self.store.get_config(self.config_key)
                if data:
                    return SchedulerConfiguration.model_validate(data)
            if self.config_path and self.config_path.exists():
                try:
                    payload = json.loads(self.config_path.read_text(encoding="utf-8"))
                    return SchedulerConfiguration.model_validate(payload)
                except (OSError, ValueError, json.JSONDecodeError):
                    pass
            return self.defaults.model_copy()

    def update(self, configuration: SchedulerConfiguration) -> SchedulerConfiguration:
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
