"""结构化执行计划、任务与审查模型。

与现有 DagTask / TaskDag / AgentResult 兼容，通过转换方法互操作。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from app.domain.models import AgentResult, DagTask, ReviewDecision, TaskDag


# ── 产物 ──────────────────────────────────────────────────────────────


class Artifact(BaseModel):
    """Agent 产出的文件或数据产物。"""

    type: str = Field(description="产物类型，如 file / blackboard_key / report")
    path_or_id: str = Field(description="文件路径或存储键")
    description: str = Field(default="", description="产物说明")


# ── 决策记录 ──────────────────────────────────────────────────────────


class Decision(BaseModel):
    """Agent 执行过程中的关键决策。"""

    decision: str = Field(description="决策内容")
    reason: str = Field(description="决策理由")


# ── 增强任务 ──────────────────────────────────────────────────────────


class AgentTask(BaseModel):
    """增强型任务定义 — 在 DagTask 基础上增加验收标准、输入/输出契约等。

    提供 to_dag_task() 向下兼容转换。
    """

    id: str = Field(pattern=r"^[a-zA-Z0-9_-]+$")
    title: str = Field(min_length=1, max_length=120)
    objective: str = Field(min_length=1, max_length=4000)
    agent: str
    depends_on: list[str] = Field(default_factory=list)
    write_scope: list[str] = Field(default_factory=list)
    context: dict[str, Any] = Field(default_factory=dict)
    inputs: list[dict[str, Any]] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)

    # ── 增强字段 ──
    acceptance_criteria: list[str] = Field(
        default_factory=list,
        description="可验证的验收条件，每项应可明确判断是否通过",
    )
    expected_outputs: list[str] = Field(
        default_factory=list,
        description="预期的输出产物描述列表",
    )
    allowed_tools: list[str] = Field(
        default_factory=list,
        description="显式允许的工具列表；空列表表示无额外限制",
    )
    forbidden_actions: list[str] = Field(
        default_factory=list,
        description="明确禁止的操作",
    )
    priority: int = Field(default=0, ge=0, le=10)
    max_iterations: int = Field(default=3, ge=1, le=20)
    status: Literal[
        "backlog", "ready", "in_progress", "blocked", "review", "completed", "failed", "cancelled"
    ] = "backlog"

    def to_dag_task(self) -> DagTask:
        """向下转换为现有 DagTask（丢弃增强字段）。"""
        return DagTask(
            id=self.id,
            title=self.title,
            objective=self.objective,
            agent=self.agent,
            depends_on=self.depends_on,
            write_scope=self.write_scope,
            context=self.context,
            inputs=self.inputs,
            constraints=self.constraints,
            expected_outputs=self.expected_outputs,
            acceptance_criteria=self.acceptance_criteria,
            allowed_tools=self.allowed_tools,
            forbidden_actions=self.forbidden_actions,
            priority=self.priority,
            max_iterations=self.max_iterations,
            status=self.status,
        )

    @classmethod
    def from_dag_task(cls, task: DagTask, **kwargs: Any) -> "AgentTask":
        """从 DagTask 升级，可选覆盖增强字段。"""
        data = dict(
            id=task.id,
            title=task.title,
            objective=task.objective,
            agent=task.agent,
            depends_on=task.depends_on,
            write_scope=task.write_scope,
            context=task.context,
            inputs=task.inputs,
            constraints=task.constraints,
            expected_outputs=task.expected_outputs,
            acceptance_criteria=task.acceptance_criteria,
            allowed_tools=task.allowed_tools,
            forbidden_actions=task.forbidden_actions,
            priority=task.priority,
            max_iterations=task.max_iterations,
            status=task.status,
        )
        data.update(kwargs)
        return cls(**data)


# ── 执行计划 ──────────────────────────────────────────────────────────


class ExecutionPlan(BaseModel):
    """结构化执行计划，由主脑生成并经校验节点验证。"""

    goal: str = Field(min_length=1, max_length=4000, description="用户目标的精炼描述")
    request_type: Literal[
        "direct_answer",
        "retrieval",
        "file_operation",
        "coding",
        "document_processing",
        "planning",
        "mixed",
    ] = "mixed"

    assumptions: list[str] = Field(default_factory=list, description="规划时的假设")
    constraints: list[str] = Field(default_factory=list, description="必须遵守的约束")

    tasks: list[AgentTask] = Field(default_factory=list, max_length=20)

    execution_strategy: Literal[
        "direct", "single_agent", "sequential", "parallel", "hybrid"
    ] = "hybrid"

    summary: str = Field(default="", max_length=1000, description="计划摘要")
    coordination_contract: str = Field(default="", max_length=12000)

    version: int = Field(default=1, ge=1, description="计划版本，每次重新规划递增")
    max_replan_iterations: int = Field(default=3, ge=1, le=10)

    review_strategy: Literal["after_each_wave", "after_all", "none"] = "after_each_wave"

    @model_validator(mode="after")
    def validate_graph(self) -> "ExecutionPlan":
        ids = [t.id for t in self.tasks]
        if len(ids) != len(set(ids)):
            raise ValueError("任务 ID 不能重复")

        known = set(ids)
        for task in self.tasks:
            unknown = set(task.depends_on) - known
            if unknown:
                raise ValueError(f"任务 {task.id} 引用了未知依赖: {sorted(unknown)}")
            if task.id in task.depends_on:
                raise ValueError(f"任务 {task.id} 不能依赖自身")

        # 循环检测
        visiting: set[str] = set()
        visited: set[str] = set()
        dep_map = {t.id: t.depends_on for t in self.tasks}

        def visit(tid: str) -> None:
            if tid in visiting:
                raise ValueError("任务依赖中存在循环")
            if tid in visited:
                return
            visiting.add(tid)
            for d in dep_map[tid]:
                visit(d)
            visiting.remove(tid)
            visited.add(tid)

        for tid in ids:
            visit(tid)
        return self

    def to_task_dag(self) -> TaskDag:
        """向下转换为现有 TaskDag。"""
        return TaskDag(
            summary=self.summary or self.goal[:200],
            coordination_contract=self.coordination_contract,
            tasks=[t.to_dag_task() for t in self.tasks],
        )

    def ready_task_ids(self) -> list[str]:
        """返回所有依赖已满足的任务 ID（基于当前计划内部状态）。"""
        completed: set[str] = {
            t.id for t in self.tasks if t.status == "completed"
        }
        ready: list[str] = []
        for t in self.tasks:
            if t.status not in ("backlog", "ready"):
                continue
            if all(d in completed for d in t.depends_on):
                ready.append(t.id)
        return ready


# ── 审查结果 ──────────────────────────────────────────────────────────


class ReviewResult(BaseModel):
    """审查节点对单个任务结果的判定。"""

    task_id: str
    status: ReviewDecision
    passed_criteria: list[str] = Field(default_factory=list)
    failed_criteria: list[str] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list, description="发现的问题")
    risks: list[str] = Field(default_factory=list, description="识别的风险")
    revision_instructions: list[str] = Field(
        default_factory=list, description="需要修改时给 Agent 的具体指示"
    )


# ── 增强的 Agent 结果 ──────────────────────────────────────────────


class EnhancedAgentResult(BaseModel):
    """增强型 Agent 执行结果 — 包含结构化产物、决策和验证信息。

    与 AgentResult 兼容：提供 to_agent_result() 和 from_agent_result() 转换。
    """

    task_id: str
    agent: str
    status: Literal["completed", "partially_completed", "blocked", "failed", "need_review"]
    summary: str = ""

    artifacts: list[Artifact] = Field(default_factory=list)
    changes: list[str] = Field(default_factory=list, description="修改的文件列表")
    decisions: list[Decision] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    dependencies_discovered: list[str] = Field(default_factory=list)

    verification_performed: list[str] = Field(default_factory=list)
    verification_not_performed: list[str] = Field(default_factory=list)
    verification_result: Literal["passed", "failed", "partial", "not_run"] = "not_run"

    board_updates: list[dict[str, Any]] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)

    review_decision: ReviewDecision | None = None
    review_feedback: str = ""

    error: str | None = None
    started_at: str | None = None
    duration_ms: int | None = None

    def to_agent_result(self) -> AgentResult:
        """向下转换为现有 AgentResult。"""
        status_map = {
            "completed": "completed",
            "partially_completed": "completed",
            "need_review": "completed",
            "blocked": "failed",
            "failed": "failed",
        }
        mapped = status_map.get(self.status, "failed")
        return AgentResult(
            task_id=self.task_id,
            agent=self.agent,
            status=mapped,  # type: ignore[arg-type]
            summary=self.summary[:6000],
            changed_files=self.changes,
            artifacts=[a.model_dump() for a in self.artifacts],
            decisions=[d.model_dump() for d in self.decisions],
            assumptions=self.assumptions,
            risks=self.risks,
            dependencies_discovered=self.dependencies_discovered,
            verification_performed=self.verification_performed,
            verification_not_performed=self.verification_not_performed,
            verification_result=self.verification_result,
            next_actions=self.next_actions,
            provides=[a.path_or_id for a in self.artifacts if a.type == "blackboard_key"],
            error=self.error,
            started_at=self.started_at,
            duration_ms=self.duration_ms,
        )

    @classmethod
    def from_agent_result(cls, result: AgentResult) -> "EnhancedAgentResult":
        """从现有 AgentResult 升级。"""
        status_map = {
            "completed": "completed",
            "failed": "failed",
            "cancelled": "failed",
            "skipped": "failed",
        }
        return cls(
            task_id=result.task_id,
            agent=result.agent,
            status=status_map.get(result.status, "failed"),  # type: ignore[arg-type]
            summary=result.summary,
            changes=result.changed_files,
            artifacts=[Artifact.model_validate(a) for a in result.artifacts],
            decisions=[Decision.model_validate(d) for d in result.decisions],
            assumptions=result.assumptions,
            risks=result.risks,
            dependencies_discovered=result.dependencies_discovered,
            verification_performed=result.verification_performed,
            verification_not_performed=result.verification_not_performed,
            verification_result=result.verification_result,
            next_actions=result.next_actions,
            error=result.error,
            started_at=result.started_at,
            duration_ms=result.duration_ms,
        )


# ── Agent 选择结果 ─────────────────────────────────────────────────────


class SelectionResult(BaseModel):
    """Agent 选择器的评分结果。"""

    agent_name: str
    matched_capabilities: list[str] = Field(default_factory=list)
    missing_capabilities: list[str] = Field(default_factory=list)
    selection_reason: str = ""
    score: float = Field(default=0.0, ge=0.0, le=1.0)
