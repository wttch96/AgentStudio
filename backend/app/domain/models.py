"""跨模型、图执行器和 HTTP API 共用的结构化领域模型。"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal, TypeAlias

from pydantic import BaseModel, Field, model_validator





class DagTask(BaseModel):
    """DeepSeek 生成、LangGraph 执行的最小任务单元。"""

    id: str = Field(pattern=r"^[a-zA-Z0-9_-]+$")
    title: str = Field(min_length=1, max_length=120)
    objective: str = Field(min_length=1, max_length=4000)
    agent: str  # 动态 agent 名称，由项目配置决定
    depends_on: list[str] = Field(default_factory=list)
    write_scope: list[str] = Field(default_factory=list)
    context: dict[str, Any] = Field(default_factory=dict)
    inputs: list[dict[str, Any]] = Field(default_factory=list)
    expected_outputs: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    allowed_tools: list[str] = Field(default_factory=list)
    forbidden_actions: list[str] = Field(default_factory=list)
    priority: int = Field(default=0, ge=0, le=10)
    max_iterations: int = Field(default=3, ge=1, le=20)
    status: Literal[
        "backlog", "ready", "in_progress", "blocked", "review",
        "completed", "failed", "cancelled",
    ] = "backlog"


class TaskDag(BaseModel):
    """有向无环任务图。校验阶段拒绝未知依赖、重复 ID 和循环。"""

    summary: str = Field(min_length=1, max_length=1000)
    coordination_contract: str = Field(default="", max_length=12_000)
    tasks: list[DagTask] = Field(default_factory=list, min_length=0, max_length=20)

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


# ── 审查决策枚举 ──


class ReviewDecision(str, Enum):
    ACCEPTED = "accepted"
    ACCEPTED_WITH_RISKS = "accepted_with_risks"
    REVISION_REQUIRED = "revision_required"
    REJECTED = "rejected"
    BLOCKED = "blocked"

    # Compatibility aliases for code written during the schema migration.
    ACCEPT = ACCEPTED
    ACCEPT_WITH_RISKS = ACCEPTED_WITH_RISKS


class AgentResult(BaseModel):
    """Claude 专业 Agent 完成节点后返回给调度器的标准结果。"""

    task_id: str
    agent: str
    status: Literal[
        "completed", "partially_completed", "blocked", "need_review",
        "failed", "cancelled", "skipped",
    ]
    summary: str
    changed_files: list[str] = Field(default_factory=list)
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    decisions: list[dict[str, Any]] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    dependencies_discovered: list[str] = Field(default_factory=list)
    verification_performed: list[str] = Field(default_factory=list)
    verification_not_performed: list[str] = Field(default_factory=list)
    verification_result: Literal["passed", "failed", "partial", "not_run"] = "not_run"
    next_actions: list[str] = Field(default_factory=list)
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
    project_id: str | None = Field(default=None)
    mode: str | None = Field(default=None, description="运行模式: auto / interactive / plan")


class ChatRunRequest(BaseModel):
    """交互模式下向主脑发送对话消息。"""
    message: str = Field(min_length=1, max_length=10_000)


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
    """主脑的完整记忆状态"""
    conversation_id: str
    task_history_count: int = 0
    decision_log: list[dict[str, Any]] = Field(default_factory=list)
    agent_capability_notes: dict[str, Any] = Field(default_factory=dict)
    project_structure_notes: dict[str, Any] = Field(default_factory=dict)
    contract_history: list[str] = Field(default_factory=list)
    last_updated: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


# ==================== 中断机制模型 ====================

class InterruptTarget(str, Enum):
    ALL = 'all'
    AGENT = 'agent'
    PLANNER = 'planner'
    TASK = 'task'


class InterruptAction(str, Enum):
    PAUSE = 'pause'
    INJECT = 'inject'
    REPLAN = 'replan'
    ABORT = 'abort'
    RESUME = 'resume'


class InterruptCommand(BaseModel):
    """用户发送的中断指令"""
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    run_id: str
    target: InterruptTarget
    action: InterruptAction
    target_agent: str | None = None
    target_task: str | None = None
    instruction: str = ''
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class InterruptDecision(BaseModel):
    """中断处理决策"""
    command_id: str
    decision: Literal['apply', 'discard', 'defer']
    modified_instruction: str = ''
    target_nodes: list[str] = Field(default_factory=list)


class KnowledgeEntry(BaseModel):
    """知识库条目"""
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    title: str = Field(min_length=1, max_length=500)
    content: str = Field(min_length=1, max_length=50000)
    category: str = Field(default="general")
    tags: list[str] = Field(default_factory=list)
    source: str = ""
    score: float = 0.0
    expires_at: str | None = None
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class KnowledgeRelation(BaseModel):
    """知识关联"""
    source_id: str
    target_id: str
    relation_type: str  # api_example / error_handling / dependency / related


class KnowledgeFeedback(BaseModel):
    """知识反馈"""
    entry_id: str
    feedback: Literal["up", "down"]


# ==================== 多项目模型 ====================

class Project(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    name: str = Field(min_length=1, max_length=100)
    root_dir: str = Field(min_length=1, max_length=4096)
    description: str = ""
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class ProjectAgent(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    project_id: str
    name: str = Field(pattern=r"^[a-z][a-z0-9-]{1,63}$")
    display_name: str = Field(min_length=1, max_length=100)
    description: str = ""
    template_id: str | None = None
    role: str = Field(default="implementation_agent", min_length=1, max_length=100)
    agent_type: Literal["brain", "rag", "claude", "file-ops", "chat", "todo", "blackboard", "doc-diff"] = "claude"
    sub_dir: str = ""
    system_prompt: str = Field(min_length=10, max_length=30000)
    skills: list[str] = Field(default_factory=list)
    model: str = ""
    is_required: bool = False
    sort_order: int = 0
    # ── 增强 Agent 配置字段（全部可选，向后兼容）──
    capabilities: list[str] = Field(default_factory=list, description="Agent 擅长的能力领域")
    limitations: list[str] = Field(default_factory=list, description="已知限制，不可逾越")
    preferred_tasks: list[str] = Field(default_factory=list, description="偏好的任务关键词/类型")
    forbidden_tasks: list[str] = Field(default_factory=list, description="绝对禁止的任务关键词/类型，优先级高于 preferred_tasks")
    input_contract: dict[str, str] = Field(default_factory=dict, description="期望的输入结构说明")
    output_contract: dict[str, str] = Field(default_factory=dict, description="期望的输出结构说明")
    dependencies_info: list[str] = Field(default_factory=list, description="运行时前置依赖说明（如特定服务、SDK 版本）")
    priority: int = Field(default=0, ge=0, le=10, description="调度优先级，数值越高越优先")
    max_iterations: int = Field(default=3, ge=1, le=20, description="单个任务最大重试/返工次数")


class AgentTemplate(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    name: str = Field(min_length=1, max_length=64)
    display_name: str = Field(min_length=1, max_length=100)
    description: str = ""
    category: str = Field(default="other")
    agent_type: str = "claude"
    default_sub_dir: str = ""
    default_prompt: str = Field(min_length=10, max_length=30000)
    default_skills: list[str] = Field(default_factory=list)
    is_builtin: bool = True


class CreateProjectRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    project_name: str | None = Field(
        default=None,
        pattern=r"^[a-z][a-z0-9-]{1,63}$",
        description="用于 .workspace/<project_name>/ 的稳定目录名",
    )
    root_dir: str = Field(min_length=1, max_length=4096)
    description: str = ""


# ==================== Blackboard 黑板系统模型 ====================


class BlackboardEntry(BaseModel):
    """单条黑板键值对，带 CAS 版本号用于并发冲突检测。"""

    key: str
    value: Any
    updated_by: str  # agent name or "system"
    updated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    version: int = 1  # monotonic counter for CAS conflict detection


class BlackboardState(BaseModel):
    """一次运行中的完整黑板快照。"""

    run_id: str
    entries: dict[str, BlackboardEntry] = Field(default_factory=dict)
    revision: int = 0  # 任意 key 写入时自增


class BlackboardWriteRequest(BaseModel):
    """Agent 对黑板发起的一次写入请求。"""

    key: str = Field(min_length=1, max_length=256)
    value: Any
    expected_version: int | None = None  # None = 无条件写入


# ==================== Todo 任务跟踪模型 ====================


class TodoItem(BaseModel):
    """运行级别的待办项，由主脑自动生成或用户手动添加。"""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    parent_task_id: str | None = None
    title: str = ""
    content: str = Field(min_length=1, max_length=500)
    objective: str = ""
    assigned_to: str | None = None
    status: Literal[
        "backlog", "ready", "pending", "in_progress", "blocked",
        "review", "completed", "failed", "cancelled",
    ] = "pending"
    depends_on: list[str] = Field(default_factory=list)
    context: dict[str, Any] = Field(default_factory=dict)
    inputs: list[dict[str, Any]] = Field(default_factory=list)
    expected_outputs: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    decisions: list[dict[str, Any]] = Field(default_factory=list)
    blockers: list[dict[str, Any]] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    verification: dict[str, Any] = Field(default_factory=dict)
    updated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    completed_at: str | None = None
