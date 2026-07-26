"""Wave 审查器 —— 在每波 Agent 执行结束后审查结果。

审查流程:
    1. 对波内每个 AgentResult 进行质量检查
    2. 生成 ReviewResult（accepted / revision_required / rejected）
    3. 判断是否需要重新规划
    4. 如需重新规划，生成修正任务
"""

from __future__ import annotations

from typing import Any

from app.domain.models import AgentResult, DagTask, TaskDag, ReviewDecision
from app.planning.execution_plan import ReviewResult, AgentTask


class WaveReviewer:
    """波次结果审查器。

    在 barrier 之后执行，检查当前波次中所有任务的结果质量。
    可在构造时注入 DeepSeekPlanner 用于 LLM 辅助审查。
    """

    def __init__(
        self,
        planner: Any = None,
        blackboard_store: Any = None,
        events: Any = None,
        enable_llm_review: bool = False,
    ) -> None:
        self._planner = planner
        self._bb = blackboard_store
        self._events = events
        self._enable_llm = enable_llm_review

    def review_wave(
        self,
        run_id: str,
        task_ids: list[str],
        results: list[AgentResult],
        dag: TaskDag | None = None,
        iteration: int = 0,
        max_iterations: int = 3,
    ) -> list[ReviewResult]:
        """审查一波任务的结果。

        Args:
            run_id: 运行 ID
            task_ids: 当前波次的任务 ID 列表
            results: 所有历史结果
            dag: 当前任务 DAG
            iteration: 当前审查迭代次数
            max_iterations: 最大审查/重试次数

        Returns:
            每个波次任务的 ReviewResult 列表
        """
        wave_results = [
            r for r in results
            if r.task_id in task_ids
        ]

        review_results: list[ReviewResult] = []

        for r in wave_results:
            review = self._review_single(r, dag, iteration, max_iterations)
            review_results.append(review)

        # 写回看板
        if self._bb is not None:
            try:
                all_reviews = self._bb.read(run_id, "all_reviews") or []
                for rr in review_results:
                    all_reviews.append(rr.model_dump())
                self._bb.write(run_id, "all_reviews", all_reviews, "reviewer")
            except Exception:
                pass

        return review_results

    def should_replan(self, review_results: list[ReviewResult]) -> bool:
        """判断是否需要重新规划。"""
        return any(
            r.status in (ReviewDecision.REVISION_REQUIRED, ReviewDecision.REJECTED)
            for r in review_results
        )

    def generate_revision_tasks(
        self,
        review_results: list[ReviewResult],
        original_tasks: list[DagTask],
    ) -> list[AgentTask]:
        """根据审查结果生成修正任务。

        仅对需要修正的任务生成新任务；已通过的任务保持不变。
        """
        orig_by_id = {t.id: t for t in original_tasks}
        revision_tasks: list[AgentTask] = []

        for rr in review_results:
            if rr.status in (ReviewDecision.REVISION_REQUIRED, ReviewDecision.REJECTED):
                orig = orig_by_id.get(rr.task_id)
                if orig is None:
                    continue

                # 构建修正任务
                fix_title = f"修正: {orig.title}"
                fix_objective = (
                    f"原始任务: {orig.objective}\n\n"
                    f"审查反馈:\n"
                    + "\n".join(f"- {i}" for i in rr.revision_instructions)
                    + f"\n\n失败标准: {', '.join(rr.failed_criteria)}"
                    + f"\n\n请只修正以上问题，不要修改已通过的部分。"
                )[:4000]

                revision_tasks.append(
                    AgentTask(
                        id=f"{orig.id}-fix-{len(revision_tasks) + 1}",
                        title=fix_title,
                        objective=fix_objective,
                        agent=orig.agent,
                        depends_on=orig.depends_on,
                        write_scope=orig.write_scope,
                        context=orig.context,
                        inputs=orig.inputs,
                        constraints=orig.constraints,
                        expected_outputs=orig.expected_outputs,
                        allowed_tools=orig.allowed_tools,
                        forbidden_actions=orig.forbidden_actions,
                        acceptance_criteria=rr.failed_criteria or orig.acceptance_criteria,
                        status="ready",
                        max_iterations=max(1, orig.max_iterations - 1),
                    )
                )

            elif rr.status == ReviewDecision.ACCEPTED:
                # 任务通过，可选更新原始计划中的状态
                pass

        return revision_tasks

    # ── 内部审查逻辑 ──────────────────────────────────────────────

    def _review_single(
        self,
        result: AgentResult,
        dag: TaskDag | None,
        iteration: int,
        max_iterations: int,
    ) -> ReviewResult:
        """审查单个任务结果。"""
        passed: list[str] = []
        failed: list[str] = []
        issues: list[str] = []
        risks: list[str] = []
        instructions: list[str] = []
        task = next((t for t in (dag.tasks if dag else []) if t.id == result.task_id), None)

        # 1. 检查执行状态
        if result.status in ("failed", "blocked"):
            failed.append("执行失败")
            issues.append(f"Agent 报告执行失败: {result.error or '无具体错误'}")
            instructions.append("分析失败原因并修正")

        elif result.status == "cancelled":
            failed.append("任务被取消")
            issues.append("任务被用户或系统取消")

        elif result.status in ("completed", "partially_completed", "need_review"):
            passed.append("执行状态为 completed")

            # 2. 摘要质量检查
            if not result.summary or len(result.summary.strip()) < 10:
                failed.append("摘要质量不足")
                issues.append("Agent 返回的摘要过短或为空")
                instructions.append("提供完整的执行摘要，至少包含做了什么、结果如何")
            else:
                passed.append("摘要质量合格")

            # 3. 产物检查
            if result.changed_files:
                passed.append(f"修改了 {len(result.changed_files)} 个文件")
                # 检查是否有实际文件存在（best-effort）
            else:
                # 没有修改文件不一定失败 — 可能是只读任务
                pass

            # 4. 按任务协议检查产物和验收证据
            if task and task.expected_outputs and not (result.artifacts or result.changed_files):
                failed.append("缺少结构化产物")
                issues.append(f"预期产物未提供: {task.expected_outputs}")
                instructions.append("提供真实 artifact 路径或标识，并确认其存在")
            if task and task.acceptance_criteria:
                if result.verification_result == "passed":
                    passed.extend(task.acceptance_criteria)
                else:
                    failed.extend(task.acceptance_criteria)
                    issues.append("没有足够验证证据证明验收标准通过")
                    instructions.append(
                        "逐条验证并报告: " + "；".join(task.acceptance_criteria)
                    )

            # 4. 验证检查
            if (
                result.verification_result == "passed"
                or result.verification_performed
                or "测试" in result.summary
                or "test" in result.summary.lower()
            ):
                passed.append("执行了测试或验证")
            else:
                risks.append("未明确说明是否执行了验证")

            # 5. 错误关键词检查
            error_keywords = ["失败", "错误", "异常", "error", "fail", "exception"]
            found_errors = [kw for kw in error_keywords if kw in result.summary.lower()]
            if found_errors and "没有" not in result.summary.lower():
                issues.append(f"摘要中包含错误关键词: {found_errors}")
                instructions.append("确认是否真的发生错误，或澄清关键词的上下文")

        # 6. 迭代上限检查
        if iteration >= max_iterations:
            risks.append(f"已达到最大审查迭代次数 ({max_iterations})")
            instructions.append("不要再重新规划此任务")

        # ── 判定最终状态 ──
        if result.status in ("failed", "blocked") and iteration >= max_iterations:
            decision = ReviewDecision.REJECTED
        elif result.status == "blocked":
            decision = ReviewDecision.BLOCKED
        elif result.status == "failed":
            decision = ReviewDecision.REVISION_REQUIRED
        elif failed:
            decision = (
                ReviewDecision.REJECTED
                if iteration >= max_iterations
                else ReviewDecision.REVISION_REQUIRED
            )
        elif risks and not failed:
            decision = ReviewDecision.ACCEPT_WITH_RISKS
        else:
            decision = ReviewDecision.ACCEPTED

        return ReviewResult(
            task_id=result.task_id,
            status=decision,
            passed_criteria=passed,
            failed_criteria=failed,
            issues=issues,
            risks=risks,
            revision_instructions=instructions,
        )


class NoOpReviewer(WaveReviewer):
    """不做审查的审查器 — 所有结果直接通过。

    用于向后兼容: 当未配置审查器时，系统行为不变。
    """

    def review_wave(
        self,
        run_id: str,
        task_ids: list[str],
        results: list[AgentResult],
        dag: TaskDag | None = None,
        iteration: int = 0,
        max_iterations: int = 3,
    ) -> list[ReviewResult]:
        return [
            ReviewResult(
                task_id=tid,
                status=ReviewDecision.ACCEPTED,
                passed_criteria=["（审查器未启用）"],
                issues=[],
                risks=[],
                revision_instructions=[],
            )
            for tid in task_ids
        ]

    def should_replan(self, review_results: list[ReviewResult]) -> bool:
        return False
