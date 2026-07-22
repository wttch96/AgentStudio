"""跨模型、图执行器和 HTTP API 共用的结构化领域模型。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


AgentName = Literal[
    "frontend-agent",
    "backend-agent",
    "netty-agent",
]


class DagTask(BaseModel):
    """DeepSeek 生成、LangGraph 执行的最小任务单元。"""

    id: str = Field(pattern=r"^[a-zA-Z0-9_-]+$")
    title: str = Field(min_length=1, max_length=120)
    objective: str = Field(min_length=1, max_length=4000)
    agent: AgentName
    depends_on: list[str] = Field(default_factory=list)
    write_scope: list[str] = Field(default_factory=list)


class TaskDag(BaseModel):
    """有向无环任务图。校验阶段拒绝未知依赖、重复 ID 和循环。"""

    summary: str = Field(min_length=1, max_length=1000)
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
    error: str | None = None


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
