"""动态 Agent 注册表 —— 从 .workspace/<project>/agents/*.yaml 加载。"""

from __future__ import annotations

from typing import Any

from app.storage.sqlite_store import SQLiteStore


class AgentProfile:
    """运行时 Agent 配置快照。"""
    __slots__ = ("id", "name", "display_name", "description", "role", "agent_type",
                 "skills", "prompt", "sub_dir", "is_required", "model",
                 "capabilities", "limitations", "preferred_tasks", "forbidden_tasks",
                 "input_contract", "output_contract", "dependencies_info",
                 "priority", "max_iterations")

    def __init__(self, agent_id: str = "", name: str = "", display_name: str = "", description: str = "",
                 role: str = "implementation_agent",
                 agent_type: str = "", skills: list[str] = None,
                 prompt: str = "", sub_dir: str = "", is_required: bool = False, model: str = None,
                 capabilities: list[str] = None, limitations: list[str] = None,
                 preferred_tasks: list[str] = None, forbidden_tasks: list[str] = None,
                 input_contract: dict[str, str] = None, output_contract: dict[str, str] = None,
                 dependencies_info: list[str] = None,
                 priority: int = 0, max_iterations: int = 3):
        self.id = agent_id or name
        self.name = name
        self.display_name = display_name
        self.description = description
        self.role = role
        self.agent_type = agent_type
        self.skills = tuple(skills) if skills else ()
        self.prompt = prompt
        self.sub_dir = sub_dir
        self.is_required = is_required
        self.model = model
        self.capabilities = tuple(capabilities) if capabilities else ()
        self.limitations = tuple(limitations) if limitations else ()
        self.preferred_tasks = tuple(preferred_tasks) if preferred_tasks else ()
        self.forbidden_tasks = tuple(forbidden_tasks) if forbidden_tasks else ()
        self.input_contract = dict(input_contract) if input_contract else {}
        self.output_contract = dict(output_contract) if output_contract else {}
        self.dependencies_info = tuple(dependencies_info) if dependencies_info else ()
        self.priority = priority
        self.max_iterations = max_iterations


class AgentRegistry:
    """从文件系统加载 Agent 配置。"""

    def __init__(self, store: SQLiteStore, config_reader=None) -> None:
        self.store = store
        self.config_reader = config_reader
        self._cache: dict[str, dict[str, AgentProfile]] = {}  # project_id -> {name: profile}

    def _load_from_files(self, project_id: str = "") -> dict[str, AgentProfile]:
        """从当前或指定项目的 agents/ 目录加载所有 Agent。"""
        if not self.config_reader:
            return {}
        reader = self.config_reader.for_project(project_id) if project_id else self.config_reader.current()
        agents = reader.list_agents()
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
                role=a.get("role", "implementation_agent"),
                agent_type=a.get("agent_type", "claude"),
                skills=a.get("skills", []),
                prompt=a.get("system_prompt", ""),
                sub_dir=a.get("sub_dir", ""),
                is_required=a.get("is_required", False),
                model=a.get("model"),
                capabilities=a.get("capabilities", []),
                limitations=a.get("limitations", []),
                preferred_tasks=a.get("preferred_tasks", []),
                forbidden_tasks=a.get("forbidden_tasks", []),
                input_contract=a.get("input_contract", {}),
                output_contract=a.get("output_contract", {}),
                dependencies_info=a.get("dependencies_info", []),
                priority=a.get("priority", 0),
                max_iterations=a.get("max_iterations", 3),
            )
        return profiles

    def load_project_agents(self, project_id: str) -> dict[str, AgentProfile]:
        """加载项目所有 Agent。缓存到内存。"""
        if project_id in self._cache:
            return self._cache[project_id]
        profiles = self._load_from_files(project_id)
        self._cache[project_id] = profiles
        return profiles

    def get(self, project_id: str = "", agent_name: str = "") -> AgentProfile:
        """查找指定 Agent。无 project_id 时从文件加载。"""
        profiles = self._load_from_files(project_id) if not project_id else self.load_project_agents(project_id)
        if agent_name not in profiles:
            raise ValueError(f"Agent '{agent_name}' not found")
        return profiles[agent_name]

    def list_public(self, project_id: str = "") -> list[dict[str, Any]]:
        """列出所有公开 Agent（排除 brain/deepseek 类型）。"""
        profiles = self._load_from_files(project_id) if not project_id else self.load_project_agents(project_id)
        return [
            {
                "id": p.id,
                "name": p.name,
                "display_name": p.display_name,
                "description": p.description,
                "role": p.role,
                "agent_type": p.agent_type,
                "skills": list(p.skills),
                "skill_count": len(p.skills),
                "is_required": p.is_required,
                "sub_dir": p.sub_dir,
                "capabilities": list(p.capabilities),
                "limitations": list(p.limitations),
                "preferred_tasks": list(p.preferred_tasks),
                "forbidden_tasks": list(p.forbidden_tasks),
                "priority": p.priority,
                "max_iterations": p.max_iterations,
                "input_contract": p.input_contract,
                "output_contract": p.output_contract,
                "dependencies_info": list(p.dependencies_info),
            }
            for p in profiles.values()
            if p.agent_type not in ("brain", "deepseek")
        ]

    def invalidate(self, project_id: str) -> None:
        self._cache.pop(project_id, None)
