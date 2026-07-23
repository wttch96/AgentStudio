"""动态 Agent 注册表 —— 从 project_agents 表加载，支持多项目。"""

from __future__ import annotations

import json
from typing import Any

from app.storage.sqlite_store import SQLiteStore


class AgentProfile:
    """运行时 Agent 配置快照。"""
    __slots__ = ("id", "name", "display_name", "description", "agent_type",
                 "tools", "skills", "prompt", "sub_dir", "is_required")

    def __init__(self, agent_id: str = "", name: str = "", display_name: str = "", description: str = "",
                 agent_type: str = "", tools: list[str] = None, skills: list[str] = None,
                 prompt: str = "", sub_dir: str = "", is_required: bool = False):
        self.id = agent_id
        self.name = name
        self.display_name = display_name
        self.description = description
        self.agent_type = agent_type
        self.tools = tuple(tools) if tools else ()
        self.skills = tuple(skills) if skills else ()
        self.prompt = prompt
        self.sub_dir = sub_dir
        self.is_required = is_required


class AgentRegistry:
    """从 SQLite 加载 Agent 配置。"""

    def __init__(self, store: SQLiteStore) -> None:
        self.store = store
        self._cache: dict[str, dict[str, AgentProfile]] = {}  # project_id -> {name: profile}

    def load_project_agents(self, project_id: str) -> dict[str, AgentProfile]:
        """加载项目所有 Agent。缓存到内存，配置变更后需调用 invalidate()。"""
        if project_id in self._cache:
            return self._cache[project_id]

        with self.store._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM project_agents WHERE project_id = ? ORDER BY sort_order",
                (project_id,),
            ).fetchall()

        profiles = {}
        for row in rows:
            r = dict(row)
            tools = json.loads(r.get("tools", "[]")) if isinstance(r.get("tools"), str) else r.get("tools", [])
            skills = json.loads(r.get("skills", "[]")) if isinstance(r.get("skills"), str) else r.get("skills", [])
            profiles[r["name"]] = AgentProfile(
                agent_id=r["id"],
                name=r["name"],
                display_name=r["display_name"],
                description=r.get("description", ""),
                agent_type=r["agent_type"],
                tools=tools,
                skills=skills,
                prompt=r["system_prompt"],
                sub_dir=r.get("sub_dir", ""),
                is_required=bool(r.get("is_required", False)),
            )

        self._cache[project_id] = profiles
        return profiles

    def get(self, project_id: str = "", agent_name: str = "") -> AgentProfile:
        if not project_id:
            result = []
            with self.store._connect() as conn:
                rows = conn.execute("SELECT DISTINCT project_id FROM project_agents").fetchall()
                for row in rows:
                    profiles = self.load_project_agents(row["project_id"])
                    for p in profiles.values():
                        if p.agent_type in ("brain", "rag"):
                            continue
                        result.append({
                            "id": p.id, "name": p.name, "display_name": p.display_name,
                            "description": p.description, "agent_type": p.agent_type,
                            "tools": list(p.tools), "skills": list(p.skills),
                            "skill_count": len(p.skills), "is_required": p.is_required,
                            "sub_dir": p.sub_dir, "project_id": row["project_id"],
                        })
            return result
        profiles = self.load_project_agents(project_id)
        if agent_name not in profiles:
            raise ValueError(f"Agent '{agent_name}' not found in project {project_id}")
        return profiles[agent_name]

    def list_public(self, project_id: str = "") -> list[dict[str, Any]]:
        if not project_id:
            result = []
            with self.store._connect() as conn:
                rows = conn.execute("SELECT DISTINCT project_id FROM project_agents").fetchall()
                for row in rows:
                    profiles = self.load_project_agents(row["project_id"])
                    for p in profiles.values():
                        result.append({
                            "name": p.name, "display_name": p.display_name,
                            "description": p.description, "agent_type": p.agent_type,
                            "tools": list(p.tools), "skills": list(p.skills),
                            "skill_count": len(p.skills), "is_required": p.is_required,
                            "sub_dir": p.sub_dir, "project_id": row["project_id"],
                        })
            return result
        profiles = self.load_project_agents(project_id)
        return [
            {
                "id": p.id,
                "name": p.name,
                "display_name": p.display_name,
                "description": p.description,
                "agent_type": p.agent_type,
                "tools": list(p.tools),
                "skills": list(p.skills),
                "skill_count": len(p.skills),
                "is_required": p.is_required,
                "sub_dir": p.sub_dir,
            }
            for p in profiles.values()
            if p.agent_type not in ("brain", "rag")
        ]

    def invalidate(self, project_id: str) -> None:
        self._cache.pop(project_id, None)
