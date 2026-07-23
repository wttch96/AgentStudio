"""持久化 Agent 的默认工作目录，并提供本机目录浏览。"""

from __future__ import annotations

import json
from pathlib import Path
from threading import RLock


class WorkspaceSettings:
    def __init__(self, config_path: Path | None = None, default_root: Path | None = None,
                 store=None, config_key: str = "workspace") -> None:
        self.config_path = config_path
        self.default_root = (default_root or Path.cwd()).resolve()
        self.store = store
        self.config_key = config_key
        self._lock = RLock()

    def current(self) -> Path:
        with self._lock:
            if self.store:
                self.store.migrate_config_from_file(self.config_key, str(self.config_path)) if self.config_path else None
                data = self.store.get_config(self.config_key)
                if data:
                    try:
                        return self._validate(str(data["workspace_root"]))
                    except (KeyError, ValueError):
                        pass
            if self.config_path and self.config_path.exists():
                try:
                    payload = json.loads(self.config_path.read_text(encoding="utf-8"))
                    return self._validate(str(payload["workspace_root"]))
                except (KeyError, ValueError, OSError, json.JSONDecodeError):
                    pass
            return self.default_root

    def update(self, value: str) -> Path:
        root = self._validate(value)
        with self._lock:
            if self.store:
                self.store.set_config(self.config_key, {"workspace_root": str(root)})
            elif self.config_path:
                self.config_path.parent.mkdir(parents=True, exist_ok=True)
                temporary = self.config_path.with_suffix(".json.tmp")
                temporary.write_text(
                    json.dumps({"workspace_root": str(root)}, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                temporary.replace(self.config_path)
        return root

    def browse(self, value: str | None = None) -> dict[str, object]:
        root = self._validate(value) if value else self.current()
        directories: list[dict[str, str]] = []
        try:
            children = sorted(
                (item for item in root.iterdir() if item.is_dir()),
                key=lambda item: item.name.lower(),
            )
            directories = [
                {"name": item.name, "path": str(item)} for item in children[:300]
            ]
        except PermissionError:
            directories = []
        parent = root.parent if root.parent != root else None
        return {
            "current": str(root),
            "parent": str(parent) if parent else None,
            "directories": directories,
        }

    @staticmethod
    def _validate(value: str) -> Path:
        root = Path(value).expanduser().resolve()
        if not root.exists():
            raise ValueError(f"工作根目录不存在: {root}")
        if not root.is_dir():
            raise ValueError(f"工作根目录不是文件夹: {root}")
        return root
