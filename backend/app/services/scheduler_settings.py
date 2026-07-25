"""持久化 LangGraph 调度参数。文件为 .agent-studio/scheduler.yaml。"""

from __future__ import annotations

from pathlib import Path
from threading import RLock

from app.domain.configuration import SchedulerConfiguration
from app.services.config_reader import ConfigReader


class SchedulerSettings:
    def __init__(
        self,
        config_reader: ConfigReader | None = None,
        defaults: SchedulerConfiguration | None = None,
    ) -> None:
        self.config_reader = config_reader
        self.defaults = defaults or SchedulerConfiguration()
        self._lock = RLock()

    def current(self, project_id: str = "") -> SchedulerConfiguration:
        with self._lock:
            if self.config_reader:
                reader = self.config_reader.for_project(project_id) if project_id else self.config_reader
                data = reader.read_setting("scheduler")
                if data:
                    return SchedulerConfiguration.model_validate(data)
            return self.defaults.model_copy()

    def update(self, configuration: SchedulerConfiguration, project_id: str = "") -> SchedulerConfiguration:
        with self._lock:
            if self.config_reader:
                reader = self.config_reader.for_project(project_id) if project_id else self.config_reader
                reader._ensure_dirs()
                reader.write_setting("scheduler", configuration.model_dump())
        return configuration.model_copy()
