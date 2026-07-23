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


class BrainConfiguration(BaseModel):
    """DeepSeek 主脑的可编辑行为提示词；结构化输出约束由代码另行追加。"""

    planning_prompt: str = Field(min_length=50, max_length=50_000)
    summary_prompt: str = Field(min_length=20, max_length=30_000)


class SchedulerConfiguration(BaseModel):
    """每次新运行读取一次的 LangGraph 与 Agent 执行限制。"""

    max_concurrent_agents: int = Field(ge=1, le=8)
    recursion_limit: int = Field(ge=10, le=500)
    agent_max_turns: int = Field(ge=1, le=100)
    agent_timeout_seconds: int = Field(ge=30, le=7200)



class MemoryConfiguration(BaseModel):
    """记忆系统可编辑配置；新增 run 读取，改动实时生效。"""

    agent_sliding_window: int = Field(default=20, ge=5, le=100)
    planner_sliding_window: int = Field(default=40, ge=10, le=200)
    compress_trigger_tokens: int = Field(default=8000, ge=2000, le=50000)
    compress_keep_recent: int = Field(default=20, ge=5, le=50)
    summarizer_model: str = Field(default='deepseek-chat', min_length=1, max_length=100)
    max_conversation_turns: int = Field(default=100, ge=10, le=1000)
    session_archive_after_hours: int = Field(default=24, ge=1, le=720)
    importance_decay_rate: float = Field(default=0.95, ge=0.5, le=1.0)
