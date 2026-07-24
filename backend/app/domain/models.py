"""跨模型、图执行器和 HTTP API 共用的结构化领域模型。"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal
import uuid

from pydantic import BaseModel, Field, model_validator





class DagTask(BaseModel):
    """DeepSeek 生成、LangGraph 执行的最小任务单元。"""

    id: str = Field(pattern=r"^[a-zA-Z0-9_-]+$")
    title: str = Field(min_length=1, max_length=120)
    objective: str = Field(min_length=1, max_length=4000)
    agent: str  # 动态 agent 名称，由项目配置决定
    depends_on: list[str] = Field(default_factory=list)
    write_scope: list[str] = Field(default_factory=list)


class TaskDag(BaseModel):
    """有向无环任务图。校验阶段拒绝未知依赖、重复 ID 和循环。"""

    summary: str = Field(min_length=1, max_length=1000)
    coordination_contract: str = Field(default="", max_length=12_000)
    tasks: list[DagTask] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def validate_graph(self) -> "TaskDag":
        ids = [task.id for task in self.tasks]
        if len(ids) != len(set(ids)):
            raise ValueError("任务 ID 不能重复")

        known = set(ids)
        for task in self.tasks:
            unknown = set(task.depends_on) - known
            if unknown:
                raise ValueError(f"任务 {task.id} 引用了未知依赖: {sorted(unknown)}")
            if task.id in task.depends_on:
                raise ValueError(f"任务 {task.id} 不能依赖自身")

        visiting: set[str] = set()
        visited: set[str] = set()
        dependency_map = {task.id: task.depends_on for task in self.tasks}

        def visit(task_id: str) -> None:
            if task_id in visiting:
                raise ValueError("任务依赖中存在循环")
            if task_id in visited:
                return
            visiting.add(task_id)
            for dependency in dependency_map[task_id]:
                visit(dependency)
            visiting.remove(task_id)
            visited.add(task_id)

        for task_id in ids:
            visit(task_id)
        return self


class AgentResult(BaseModel):
    """Claude 专业 Agent 完成节点后返回给调度器的标准结果。"""

    task_id: str
    agent: str
    status: Literal["completed", "failed", "cancelled", "skipped"]
    summary: str
    changed_files: list[str] = Field(default_factory=list)
    provides: list[str] = Field(
        default_factory=list,
        description="Agent 声明产出的资源/能力标识，供下游 Agent 通过依赖筛选消费",
    )
    error: str | None = None
    started_at: str | None = Field(
        default=None, description="Agent 开始执行的 ISO 8601 时间戳"
    )
    duration_ms: int | None = Field(
        default=None, description="Agent 执行耗时（毫秒），status 为终态时有值"
    )


class RunEvent(BaseModel):
    """前端消费的统一事件；sequence 由 SQLite 按 run 单调递增。"""

    run_id: str
    sequence: int = 0
    type: str
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    agent_id: str | None = None
    task_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class CreateRunRequest(BaseModel):
    objective: str = Field(min_length=2, max_length=20_000)
    parent_run_id: str | None = Field(default=None, min_length=1, max_length=100)


# ==================== 分层记忆模型 ====================

class MemoryLevel(str, Enum):
    AGENT = 'agent'
    PLANNER = 'planner'
    SESSION = 'session'
    PROJECT = 'project'


class MemoryRecord(BaseModel):
    """单条记忆记录"""
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    run_id: str
    conversation_id: str
    level: MemoryLevel
    agent_id: str | None = None
    task_id: str | None = None
    phase: str = Field(description='planning | execution | synthesis')
    summary: str = Field(max_length=4000)
    structured_data: dict[str, Any] | None = None
    token_count_before: int = 0
    token_count_after: int = 0
    importance: float = Field(default=0.5, ge=0.0, le=1.0)
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class AgentMemoryState(BaseModel):
    """Agent 的完整记忆状态"""
    agent_id: str
    conversation_id: str
    recent_message_count: int = 0
    summary_count: int = 0
    extracted_facts: dict[str, Any] = Field(default_factory=dict)
    token_budget: int = 32000
    last_updated: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class PlannerMemoryState(BaseModel):
    """主脑�