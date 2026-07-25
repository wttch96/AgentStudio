"""持久化 Agent 的默认工作目录，并提供本机目录浏览。"""

from __future__ import annotations

import json
from pathlib import Path
from threading import RLock

from app.services.config_reader import ConfigReader


class WorkspaceSettings:
    """工作空间根目录配置。文件为 .agent-studio/workspace.yaml。"""

    def __init__(
        self,
        config_reader: ConfigReader | None = None,
        default_root: Path | None = None,
    ) -> None:
        self.config_reader = config_reader
        self.default_root = (default_root or Path.cwd()).resolve()
        self._lock = RLock()

    def current(self) -> Path:
        with self._lock:
            if self.config_reader:
                data = self.config_reader.read_setting("workspace")
                if data:
                    try:
                        return self._validate(str(data["path"]))
                    except (KeyError, ValueError):
                        pass
            return self.default_root

    def update(self, value: str) -> Path:
        root = self._validate(value)
        with self._lock:
            if self.config_reader:
                self.config_reader.write_setting("workspace", {"path": str(root)})
        return root

    def browse(self, value: str | None = None) -> dict[str, object]:
        root = self._validate(value) if value else self.current()
        directories: list[dict[str, str]] = []
        files: list[dict[str, str]] = []
        try:
            children = sorted(
                root.iterdir(),
                key=lambda item: (not item.is_dir(), item.name.lower()),
            )
            for item in children:
                if item.name.startswith("."):
                    continue
                if item.is_dir():
                    directories.append({"name": item.name, "path": str(item)})
                elif item.is_file():
                    suffix = item.suffix.lower()
                    if suffix in (".md", ".markdown", ".txt", ".json", ".yaml", ".yml", ".py", ".js", ".ts", ".vue", ".html", ".css", ".toml", ".cfg", ".ini", ".env"):
                        files.append({"name": item.name, "path": str(item)})
                if len(directories) >= 300:
                    break
        except PermissionError:
            directories = []
            files = []
        parent = root.parent if root.parent != root else None
        return {
            "current": str(root),
            "parent": str(parent) if parent else None,
            "directories": directories,
            "files": files,
        }

    @staticmethod
    def _validate(value: str) -> Path:
        root = Path(value).expanduser().resolve()
        if not root.exists():
            raise ValueError(f"工作根目录不存在: {root}")
        if not root.is_dir():
            raise ValueError(f"工作根目录不是文件夹: {root}")
        return root
