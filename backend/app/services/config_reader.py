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
                templates.append(self._read_yaml(f))
            except Exception:
                pass
        return templates

    # ------------------------------------------------------------------
    # Migration helpers
    # ------------------------------------------------------------------

    def migrate_from_db(self, store) -> dict[str, int]:
        """首次启动时将 SQLite 数据迁移到 .agent-studio/ 文件。返回统计信息。"""
        stats = {"projects": 0, "agents": 0, "skills": 0, "settings": 0}
        if self.root.joinpath("project.yaml").exists():
            return stats  # Already migrated

        self._ensure_dirs()
        with self._lock:
            try:
                with store._connect() as conn:
                    # Project
                    projects = conn.execute("SELECT * FROM projects").fetchall()
                    for row in projects:
                        p = dict(row)
                        self._write_yaml(self.root / "project.yaml", {
                            "name": p.get("name", ""),
                            "description": p.get("description", ""),
                            "root_dir": p.get("root_dir", ""),
                        })
                        stats["projects"] += 1

                        # Agents for this project
                        agents = conn.execute(
                            "SELECT * FROM project_agents WHERE project_id = ? ORDER BY sort_order",
                            (p["id"],),
                        ).fetchall()
                        for a_row in agents:
                            a = dict(a_row)
                            agent_data = {
                                "name": a.get("name", ""),
                                "display_name": a.get("display_name", ""),
                                "description": a.get("description", ""),
                                "agent_type": a.get("agent_type", "claude"),
                                "sub_dir": a.get("sub_dir", ""),
                                "system_prompt": a.get("system_prompt", ""),
                                "tools": json.loads(a.get("tools", "[]")),
                                "skills": json.loads(a.get("skills", "[]")),
                                "sort_order": a.get("sort_order", 0),
                            }
                            self._write_yaml(self.agents_dir / f"{a['name']}.yaml", agent_data)
                            stats["agents"] += 1

                        # Project skills
                        pskills = conn.execute(
                            "SELECT * FROM project_skills WHERE project_id = ?",
                            (p["id"],),
                        ).fetchall()
                        for s_row in pskills:
                            s = dict(s_row)
                            self._write_yaml(self.skills_dir / f"{s['name']}.yaml", {
                                "name": s.get("name", ""),
                                "description": s.get("description", ""),
                                "content": s.get("content", ""),
                            })
                            stats["skills"] += 1

                    # Settings (brain, workspace, scheduler, memory)
                    configs = conn.execute("SELECT * FROM configs").fetchall()
                    for c_row in configs:
                        c = dict(c_row)
                        try:
                            data = json.loads(c["value"])
                            self._write_yaml(self.root / f"{c['key']}.yaml", data)
                            stats["settings"] += 1
                        except Exception:
                            pass

            except Exception as e:
                stats["_error"] = str(e)

        return stats
