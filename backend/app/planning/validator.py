"""任务计划校验器。

在执行计划进入调度前校验其合法性。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.agents.registry import AgentRegistry
from app.planning.execution_plan import AgentTask, ExecutionPlan


@dataclass
class ValidationResult:
    """计划校验结果。"""

    is_valid: bool
    errors: list[str] = field(default_factory=list)    # 阻断性问题
    warnings: list[str] = field(default_factory=list)   # 建议性问题
    ready_task_ids: list[str] = field(default_factory=list)
    backlog_task_ids: list[str] = field(default_factory=list)


class PlanValidator:
    """校验 ExecutionPlan 的结构完整性和逻辑合法性。

    校验项目:
        1. task_id 不得重复
        2. Agent ID 必须存在
        3. 依赖任务必须存在
        4. 不允许循环依赖
        5. 每个任务应有验收标准
        6. forbidden_tasks 命中检查
        7. 必需工具检查
        8. 计算 ready/backlog 任务
    """

    def __init__(
        self,
        agent_registry: AgentRegistry | None = None,
        project_id: str = "",
    ) -> None:
        self._registry = agent_registry
        self._project_id = project_id

    def validate(self, plan: ExecutionPlan) -> ValidationResult:
        """校验执行计划。"""
        result = ValidationResult(is_valid=True)

        task_ids = [t.id for t in plan.tasks]
        task_by_id = {t.id: t for t in plan.tasks}

        # 1. 重复 ID 检查
        if len(task_ids) != len(set(task_ids)):
            dupes = {tid for tid in task_ids if task_ids.count(tid) > 1}
            result.errors.append(f"重复的 task_id: {dupes}")
            result.is_valid = False

        # 2-3. Agent 和依赖存在性检查
        agent_ids: set[str] = set()
        if self._registry and self._project_id:
            try:
                profiles = self._registry.load_project_agents(self._project_id)
                agent_ids = set(profiles.keys())
            except Exception:
                pass

        known_ids = set(task_ids)
        for task in plan.tasks:
            # Agent 存在性
            if agent_ids and task.agent not in agent_ids:
                result.errors.append(f"任务 {task.id}: Agent '{task.agent}' 不存在")
                result.is_valid = False

            # 依赖存在性
            unknown = set(task.depends_on) - known_ids
            if unknown:
                result.errors.append(f"任务 {task.id} 引用了未知依赖: {sorted(unknown)}")
                result.is_valid = False

            # 自依赖
            if task.id in task.depends_on:
                result.errors.append(f"任务 {task.id} 不能依赖自身")
                result.is_valid = False

        # 4. 循环依赖检查 (DFS)
        if result.is_valid:
            self._check_cycles(task_by_id, result)

        # 5. 验收标准检查
        for task in plan.tasks:
            if not task.acceptance_criteria:
                result.warnings.append(
                    f"任务 {task.id} ('{task.title}') 缺少验收标准"
                )

        # 6. forbidden_tasks 检查
        if self._registry and self._project_id:
            self._check_forbidden_tasks(plan, result)

        # 7. 工具检查
        if self._registry and self._project_id:
            self._check_required_tools(plan, result)

        # 8. 计算 ready/backlog
        if result.is_valid:
            ready, backlog = self._compute_status(task_by_id)
            result.ready_task_ids = ready
            result.backlog_task_ids = backlog

        return result

    def auto_fix(self, plan: ExecutionPlan, result: ValidationResult) -> ExecutionPlan:
        """尝试自动修复可修复的问题。

        当前支持:
            - 缺少验收标准: 从 objective 中推断
        """
        tasks = list(plan.tasks)

        for i, task in enumerate(tasks):
            if not task.acceptance_criteria:
                inferred = self._infer_criteria(task)
                if inferred:
                    tasks[i] = task.model_copy(
                        update={"acceptance_criteria": inferred}
                    )
                    result.warnings = [
                        w for w in result.warnings
                        if f"任务 {task.id}" not in w or "验收标准" not in w
                    ]
                    result.warnings.append(
                        f"任务 {task.id}: 已自动推断验收标准: {inferred}"
                    )

        return plan.model_copy(update={"tasks": tasks})

    # ── 内部方法 ──────────────────────────────────────────────────

    @staticmethod
    def _check_cycles(
        task_by_id: dict[str, AgentTask], result: ValidationResult,
    ) -> None:
        visiting: set[str] = set()
        visited: set[str] = set()
        deps = {tid: t.depends_on for tid, t in task_by_id.items()}

        def visit(tid: str) -> None:
            if tid in visiting:
                result.errors.append(f"检测到循环依赖，涉及: {tid}")
                result.is_valid = False
                return
            if tid in visited:
                return
            visiting.add(tid)
            for d in deps.get(tid, []):
                visit(d)
            visiting.remove(tid)
            visited.add(tid)

        for tid in task_by_id:
            if result.is_valid:
                visit(tid)

    def _check_forbidden_tasks(
        self, plan: ExecutionPlan, result: ValidationResult,
    ) -> None:
        try:
            profiles = self._registry.load_project_agents(self._project_id)  # type: ignore[union-attr]
        except Exception:
            return

        for task in plan.tasks:
            profile = profiles.get(task.agent)
            if profile is None:
                continue
            obj_lower = task.objective.lower()
            for forbidden in profile.forbidden_tasks:
                if forbidden.lower() in obj_lower:
                    result.errors.append(
                        f"任务 {task.id}: Agent '{task.agent}' 的禁止项 "
                        f"'{forbidden}' 与任务目标冲突"
                    )
                    result.is_valid = False

    def _check_required_tools(
        self, plan: ExecutionPlan, result: ValidationResult,
    ) -> None:
        try:
            profiles = self._registry.load_project_agents(self._project_id)  # type: ignore[union-attr]
        except Exception:
            return

        for task in plan.tasks:
            if not task.allowed_tools:
                continue
            profile = profiles.get(task.agent)
            if profile is None:
                continue
            agent_tools = {t.lower() for t in profile.tools}
            for required in task.allowed_tools:
                if required.lower() not in agent_tools:
                    result.errors.append(
                        f"任务 {task.id}: Agent '{task.agent}' 缺少必需工具 '{required}'"
                    )
                    result.is_valid = False

    @staticmethod
    def _compute_status(
        task_by_id: dict[str, AgentTask],
    ) -> tuple[list[str], list[str]]:
        """计算哪些任务可以进入 ready，哪些仍在 backlog/blocked。"""
        ready: list[str] = []
        backlog: list[str] = []

        for task in task_by_id.values():
            if task.status in ("completed", "failed", "cancelled"):
                continue
            if not task.depends_on:
                ready.append(task.id)
            else:
                backlog.append(task.id)

        return ready, backlog

    @staticmethod
    def _infer_criteria(task: AgentTask) -> list[str]:
        """从任务目标推断验收标准。"""
        obj = task.objective.lower()
        criteria: list[str] = []

        # 关键词推断
        if any(w in obj for w in ("创建", "新建", "生成", "create", "generate")):
            criteria.append("确认生成的文件存在且内容符合规范")
        if any(w in obj for w in ("修改", "更新", "修复", "modify", "update", "fix")):
            criteria.append("确认修改的文件已保存且功能符合预期")
        if any(w in obj for w in ("删除", "移除", "delete", "remove")):
            criteria.append("确认指定内容已删除且无残留")
        if any(w in obj for w in ("测试", "验证", "test", "verify", "validate")):
            criteria.append("确认测试通过且覆盖主流程")
        if any(w in obj for w in ("api", "接口", "endpoint")):
            criteria.append("确认 API 契约不变或变更已通知主脑")
        if any(w in obj for w in ("文档", "document", "说明")):
            criteria.append("确认文档内容准确、格式正确")
        if any(w in obj for w in ("搜索", "检索", "查找", "search", "find", "query")):
            criteria.append("确认搜索结果完整且标注来源")

        if not criteria:
            criteria.append("任务目标已达成，产物已生成")

        return criteria
