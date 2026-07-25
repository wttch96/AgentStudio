"""文件优先的配置读写层。

所有用户配置以 .workspace/<project-id>/ YAML 文件为主源，数据库仅作运行时缓存。
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

import yaml


class ConfigReader:
    """读取 .workspace/<project-id>/ 目录下的 YAML 配置文件。"""

    def __init__(self, workspace_root: Path | str, project_id: str = "") -> None:
        self.workspace_root = Path(workspace_root)
        self.project_id = project_id
        if project_id:
            self.root = self.workspace_root / ".workspace" / project_id
        else:
            self.root = self.workspace_root / ".workspace" / ".agent-studio"  # 兼容旧默认路径
        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    # Directory helpers
    # ------------------------------------------------------------------

    @property
    def agents_dir(self) -> Path:
        return self.root / "agents"

    @property
    def skills_dir(self) -> Path:
        return self.root / "skills"

    @property
    def flows_dir(self) -> Path:
        return self.root / "flows"

    def _ensure_dirs(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.agents_dir.mkdir(parents=True, exist_ok=True)
        self.skills_dir.mkdir(parents=True, exist_ok=True)
        self.flows_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _read_yaml(path: Path) -> dict:
        if not path.is_file():
            raise FileNotFoundError(str(path))
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    @staticmethod
    def _write_yaml(path: Path, data: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            yaml.safe_dump(data, allow_unicode=True, sort_keys=False, default_flow_style=False),
            encoding="utf-8",
        )

    @staticmethod
    def _read_json(path: Path) -> dict:
        if not path.is_file():
            raise FileNotFoundError(str(path))
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _write_json(path: Path, data: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    # ------------------------------------------------------------------
    # Project
    # ------------------------------------------------------------------

    def list_projects(self) -> list[dict[str, Any]]:
        """扫描 .workspace/ 下所有项目目录，读取各自的 project.yaml。"""
        projects: list[dict[str, Any]] = []
        ws_dir = self.workspace_root / ".workspace"
        if not ws_dir.is_dir():
            return projects
        with self._lock:
            for entry in sorted(ws_dir.iterdir()):
                if not entry.is_dir() or entry.name.startswith("."):
                    continue
                yaml_file = entry / "project.yaml"
                if yaml_file.is_file():
                    try:
                        data = self._read_yaml(yaml_file)
                        if data:
                            # 旧项目可能没有 id 字段，用目录名补齐
                            if "id" not in data:
                                data["id"] = entry.name
                            projects.append(data)
                    except Exception:
                        pass
        return projects

    def load_project(self) -> dict[str, Any]:
        with self._lock:
            return self._read_yaml(self.root / "project.yaml")

    def save_project(self, data: dict[str, Any]) -> None:
        # project.yaml 保存在项目目录根（.workspace/<id>/project.yaml）
        project_yaml = self.root / "project.yaml"
        with self._lock:
            self.root.mkdir(parents=True, exist_ok=True)
            self._write_yaml(project_yaml, data)

    def delete_project(self, project_id: str) -> bool:
        """删除 .workspace/<project_id>/project.yaml，不清除项目目录。"""
        project_yaml = self.workspace_root / ".workspace" / project_id / "project.yaml"
        with self._lock:
            if project_yaml.is_file():
                project_yaml.unlink()
                return True
        return False

    def for_project(self, project_id: str) -> "ConfigReader":
        """为指定项目创建 ConfigReader 实例。"""
        return ConfigReader(self.workspace_root, project_id=project_id)

    # ------------------------------------------------------------------
    # Settings (brain / workspace / scheduler / memory)
    # ------------------------------------------------------------------

    def read_setting(self, key: str) -> dict | None:
        path = self.root / f"{key}.yaml"
        with self._lock:
            if path.is_file():
                return self._read_yaml(path)
        return None

    def write_setting(self, key: str, data: dict) -> None:
        with self._lock:
            self._ensure_dirs()
            self._write_yaml(self.root / f"{key}.yaml", data)

    def read_setting_json(self, key: str) -> dict | None:
        """兼容旧的 JSON 格式配置文件（brain.default.json 等）。"""
        path = self.root / f"{key}.json"
        with self._lock:
            if path.is_file():
                return self._read_json(path)
        return None

    # ------------------------------------------------------------------
    # Agents
    # ------------------------------------------------------------------

    def list_agents(self) -> list[dict[str, Any]]:
        with self._lock:
            if not self.agents_dir.is_dir():
                return []
            agents = []
            for f in sorted(self.agents_dir.glob("*.yaml")):
                try:
                    agents.append(self._read_yaml(f))
                except Exception:
                    pass
            return agents

    def get_agent(self, name: str) -> dict[str, Any]:
        with self._lock:
            return self._read_yaml(self.agents_dir / f"{name}.yaml")

    def save_agent(self, name: str, data: dict[str, Any]) -> None:
        with self._lock:
            self._ensure_dirs()
            data["name"] = name
            self._write_yaml(self.agents_dir / f"{name}.yaml", data)

    def delete_agent(self, name: str) -> None:
        with self._lock:
            path = self.agents_dir / f"{name}.yaml"
            if path.is_file():
                path.unlink()

    # ------------------------------------------------------------------
    # Skills
    # ------------------------------------------------------------------

    def list_skills(self) -> list[dict[str, Any]]:
        with self._lock:
            if not self.skills_dir.is_dir():
                return []
            skills = []
            for f in sorted(self.skills_dir.glob("*.yaml")):
                try:
                    skills.append(self._read_yaml(f))
                except Exception:
                    pass
            return skills

    def get_skill(self, name: str) -> dict[str, Any]:
        with self._lock:
            return self._read_yaml(self.skills_dir / f"{name}.yaml")

    def save_skill(self, name: str, data: dict[str, Any]) -> None:
        with self._lock:
            self._ensure_dirs()
            data["name"] = name
            self._write_yaml(self.skills_dir / f"{name}.yaml", data)

    def delete_skill(self, name: str) -> None:
        with self._lock:
            path = self.skills_dir / f"{name}.yaml"
            if path.is_file():
                path.unlink()

    # ------------------------------------------------------------------
    # Global agent templates (config/templates/agents/*.yaml)
    # ------------------------------------------------------------------

    def list_agent_templates(self) -> list[dict[str, Any]]:
        """从项目根目录 templates/agents/ 加载 Agent 模板。"""
        tmpl_dir = self.workspace_root / "templates" / "agents"
        if not tmpl_dir.is_dir():
            return []
        templates = []
        for f in sorted(tmpl_dir.glob("*.yaml")):
            try:
                data = self._read_yaml(f)
                # 保证 id 字段存在，前端组件依赖此字段
                if "id" not in data:
                    data["id"] = data.get("name", f.stem)
                templates.append(data)
            except Exception:
                pass
        return templates

    # ------------------------------------------------------------------
    # Migration helpers
    # ------------------------------------------------------------------

    def migrate_from_db(self, store) -> dict[str, int]:
        """首次启动时将 SQLite 配置迁移到文件。"""
        stats = {"projects": 0, "agents": 0, "skills": 0, "settings": 0}
        if self.root.joinpath("project.yaml").exists():
            return stats  # Already migrated

        self._ensure_dirs()
        with self._lock:
            try:
                with store._connect() as conn:
                    # 检查 configs 表是否存在（旧版可能有设置数据）
                    try:
                        configs = conn.execute("SELECT * FROM configs").fetchall()
                        for c_row in configs:
                            c = dict(c_row)
                            try:
                                data = json.loads(c["value"])
                                self._write_yaml(self.root / f"{c['key']}.yaml", data)
                                stats["settings"] += 1
                            except Exception:
                                pass
                    except Exception:
                        pass  # configs 表不存在，跳过

            except Exception as e:
                stats["_error"] = str(e)

        return stats
