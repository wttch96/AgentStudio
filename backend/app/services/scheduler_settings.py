"""持久化 LangGraph 调度参数，并为每次运行提供不可变配置快照。"""

from __future__ import annotations

import json
from pathlib import Path
from threading import RLock

from app.domain.configuration import SchedulerConfiguration


class SchedulerSettings:
    def __init__(
        self,
        config_path: Path,
        defaults: SchedulerConfiguration,
    ) -> None:
        self.config_path = config_path
        self.defaults = defaults
        self._lock = RLock()

    def current(self) -> SchedulerConfiguration:
        with self._lock:
            if not self.config_path.exists():
                return self.defaults.model_copy()
            try:
                payload = json.loads(self.config_path.read_text(encoding="utf-8"))
                return SchedulerConfiguration.model_validate(payload)
            except (OSError, ValueError, json.JSONDecodeError):
                return self.defaults.model_copy()

    def update(self, configuration: SchedulerConfiguration) -> SchedulerConfiguration:
        with self._lock:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.config_path.with_suffix(".json.tmp")
            temporary.write_text(
                json.dumps(configuration.model_dump(), ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            temporary.replace(self.config_path)
        return configuration.model_copy()
