"""显式依赖容器，避免在各模块散布全局单例。"""

from dataclasses import dataclass

from app.agents.claude_executor import ClaudeAgentExecutor
from app.agents.registry import AgentRegistry
from app.agents.skill_registry import SkillRegistry
from app