"""页面配置中心使用的输入模型。

名称只允许安全的短横线标识符，避免页面输入被解释成任意文件路径。
"""

from pydantic import BaseModel, Field, field_validator, model_validator


SAFE_NAME_PATTERN = r"^[a-z][a-z0-9-]{1,63}$"


class AgentUpdate(BaseModel):
    description: str = Field(min_length=1, max_length=500)
    tools: list[str] = Field(default_factory=list, max_length=30)
    skills: list[str] = Field(default_factory=list, max_length=30)
    prompt: str = Field(min_length=10, max_length=30_000)

    @field_validator("tools", "skills")
    @classmethod
    def unique_items(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("列表中不能包含重复项")
        return value

    @model_validator(mode="after")
    def skill_tool_is_required(self) -> "AgentUpdate":
        if self.skills and "Skill" not in self.tools:
            raise ValueError("关联 Skill 时必须保留 Skill 工具")
        return self


class SkillCreate(BaseModel):
    name: str = Field(pattern=SAFE_NAME_PATTERN)
    description: str = Field(min_length=1, max_length=500)
    content: str = Field(min_length=10, max_length=50_000)


class SkillUpdate(BaseModel):
    description: str = Field(min_length=1, max_length=500)
    content: str = Field(min_length=10, max_length=50_000)


class WorkspaceUpdate(BaseModel):
    path: str = Field(min_length=1, max_length=4096)


class SchedulerConfiguration(BaseModel):
    """每次新运行读取一次的 LangGraph 与 Agent 执行限制。"""

    max_concurrent_agents: int = Field(ge=1, le=8)
    recursion_limit: int = Field(ge=10, le=500)
    agent_max_turns: int = Field(ge=1, le=100)
    agent_timeout_seconds: int = Field(ge=30, le=7200)
