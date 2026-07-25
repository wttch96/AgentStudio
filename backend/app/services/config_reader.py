"""文件优先的配置读写层。

所有用户配置以 .agent-studio/ YAML 文件为主源，数据库仅作运行时缓存。
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

import yaml


class ConfigReader:
    """读取 .workspace/.agent-studio/ 目录下的 YAML 配置文件。"""

    def __init__(self, workspace_root: Path | str) -> None:
        self.root = Path(workspace_root) / ".workspace" / ".agent-studio"
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

    def load_project(self) -> dict[str, Any]:
        with self._lock:
            return self._read_yaml(self.root / "project.yaml")

    def save_project(self, data: dict[str, Any]) -> None:
        with self._lock:
            self._ensure_dirs()
            self._write_yaml(self.root / "project.yaml", data)

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
        tmpl_dir = self.root.parent.parent / "templates" / "agents"
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
        """首次启动时将 SQLite 配置迁移到 .agent-studio/ 文件。

        注意：projects/project_agents/project_skills/skill_templates 等表已移除，
        配置数据以 .workspace/.agent-studio/ 下 YAML 文件为唯一数据源。
        此方法保留用于迁移 configs 表中的遗留设置项。
        """
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
