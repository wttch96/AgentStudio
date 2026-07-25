"""动态 Agent 注册表 —— 从 .agent-studio/agents/*.yaml 文件加载。"""

from __future__ import annotations

from typing import Any

from app.storage.sqlite_store import SQLiteStore


class AgentProfile:
    """运行时 Agent 配置快照。"""
    __slots__ = ("id", "name", "display_name", "description", "agent_type",
                 "tools", "skills", "prompt", "sub_dir", "is_required")

    def __init__(self, agent_id: str = "", name: str = "", display_name: str = "", description: str = "",
                 agent_type: str = "", tools: list[str] = None, skills: list[str] = None,
                 prompt: str = "", sub_dir: str = "", is_required: bool = False):
        self.id = agent_id or name
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
    """从文件系统加载 Agent 配置。"""

    def __init__(self, store: SQLiteStore, config_reader=None) -> None:
        self.store = store
        self.config_reader = config_reader
        self._cache: dict[str, dict[str, AgentProfile]] = {}  # project_id -> {name: profile}

    def _load_from_files(self) -> dict[str, AgentProfile]:
        """从 .agent-studio/agents/ 加载所有 Agent。"""
        if not self.config_reader:
            return {}
        agents = self.config_reader.list_agents()
        profiles = {}
        for a in agents:
            name = a.get("name", "")
            if not name:
                continue
            profiles[name] = AgentProfile(
                agent_id=name,
                name=name,
                display_name=a.get("display_name", name),
                description=a.get("description", ""),
                agent_type=a.get("agent_type", "claude"),
                tools=a.get("tools", []),
                skills=a.get("skills", []),
                prompt=a.get("system_prompt", ""),
                sub_dir=a.get("sub_dir", ""),
                is_required=a.get("is_required", False),
            )
        return profiles

    def load_project_agents(self, project_id: str) -> dict[str, AgentProfile]:
        """加载项目所有 Agent。缓存到内存。"""
        if project_id in self._cache:
            return self._cache[project_id]
        profiles = self._load_from_files()
        self._cache[project_id] = profiles
        return profiles

    def get(self, project_id: str = "", agent_name: str = "") -> AgentProfile:
        """查找指定 Agent。无 project_id 时从文件加载。"""
        profiles = self._load_from_files() if not project_id else self.load_project_agents(project_id)
        if agent_name not in profiles:
            raise ValueError(f"Agent '{agent_name}' not found")
        return profiles[agent_name]

    def list_public(self, project_id: str = "") -> list[dict[str, Any]]:
        """列出所有公开 Agent（排除 brain/deepseek 类型）。"""
        profiles = self._load_from_files() if not project_id else self.load_project_agents(project_id)
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
            if p.agent_type not in ("brain", "deepseek")
        ]

    def invalidate(self, project_id: str) -> None:
        self._cache.pop(project_id, None)
