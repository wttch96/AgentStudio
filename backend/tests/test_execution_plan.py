"""执行计划模型测试 —— 转换、校验、循环检测。"""

import pytest

from app.domain.models import DagTask
from app.planning.execution_plan import (
    AgentTask,
    ExecutionPlan,
    ReviewResult,
    EnhancedAgentResult,
    Artifact,
    Decision,
    ReviewDecision,
)


class TestAgentTaskConversion:
    """AgentTask ↔ DagTask 转换测试。"""

    def test_to_dag_task(self):
        """AgentTask.to_dag_task() 应生成有效 DagTask。"""
        at = AgentTask(
            id="task-1",
            title="测试任务",
            objective="完成任务目标",
            agent="test-agent",
            acceptance_criteria=["确认文件已创建"],
            expected_outputs=["output.txt"],
            allowed_tools=["Read", "Write"],
            priority=3,
            status="ready",
        )
        dt = at.to_dag_task()
        assert isinstance(dt, DagTask)
        assert dt.id == "task-1"
        assert dt.title == "测试任务"
        assert dt.objective == "完成任务目标"
        assert dt.agent == "test-agent"
        # 任务协议字段必须保留到 LangGraph 实际执行阶段。
        assert dt.acceptance_criteria == ["确认文件已创建"]
        assert dt.expected_outputs == ["output.txt"]
        assert dt.allowed_tools == ["Read", "Write"]

    def test_from_dag_task(self):
        """AgentTask.from_dag_task() 应从 DagTask 创建。"""
        dt = DagTask(
            id="task-2",
            title="升级任务",
            objective="执行升级",
            agent="claude",
            depends_on=["task-1"],
        )
        at = AgentTask.from_dag_task(
            dt,
            acceptance_criteria=["确认升级成功"],
            status="ready",
        )
        assert at.id == "task-2"
        assert at.depends_on == ["task-1"]
        assert at.acceptance_criteria == ["确认升级成功"]
        assert at.status == "ready"


class TestExecutionPlan:
    """执行计划测试。"""

    def test_valid_plan(self):
        """合法计划应通过校验。"""
        plan = ExecutionPlan(
            goal="实现用户登录功能",
            request_type="coding",
            tasks=[
                AgentTask(
                    id="t1", title="API设计", objective="设计登录API",
                    agent="backend", status="ready",
                ),
                AgentTask(
                    id="t2", title="前端实现", objective="实现登录页面",
                    agent="frontend", depends_on=["t1"], status="backlog",
                ),
            ],
            execution_strategy="sequential",
        )
        assert plan.goal == "实现用户登录功能"
        assert len(plan.tasks) == 2
        assert plan.to_task_dag().tasks[0].id == "t1"

    def test_duplicate_task_ids(self):
        """重复 task_id 应失败。"""
        with pytest.raises(ValueError, match="不能重复"):
            ExecutionPlan(
                goal="test",
                tasks=[
                    AgentTask(id="dup", title="A", objective="a", agent="x"),
                    AgentTask(id="dup", title="B", objective="b", agent="y"),
                ],
            )

    def test_unknown_dependency(self):
        """引用不存在的依赖应失败。"""
        with pytest.raises(ValueError, match="未知依赖"):
            ExecutionPlan(
                goal="test",
                tasks=[
                    AgentTask(id="t1", title="A", objective="a",
                              agent="x", depends_on=["nonexistent"]),
                ],
            )

    def test_self_dependency(self):
        """自依赖应失败。"""
        with pytest.raises(ValueError, match="不能依赖自身"):
            ExecutionPlan(
                goal="test",
                tasks=[
                    AgentTask(id="t1", title="A", objective="a",
                              agent="x", depends_on=["t1"]),
                ],
            )

    def test_circular_dependency(self):
        """循环依赖应失败。"""
        with pytest.raises(ValueError, match="循环"):
            ExecutionPlan(
                goal="test",
                tasks=[
                    AgentTask(id="t1", title="A", objective="a",
                              agent="x", depends_on=["t2"]),
                    AgentTask(id="t2", title="B", objective="b",
                              agent="y", depends_on=["t1"]),
                ],
            )

    def test_ready_task_ids(self):
        """ready_task_ids 应正确计算就绪任务。"""
        plan = ExecutionPlan(
            goal="test",
            tasks=[
                AgentTask(id="t1", title="A", objective="a", agent="x",
                          status="completed"),
                AgentTask(id="t2", title="B", objective="b", agent="y",
                          depends_on=["t1"], status="backlog"),
                AgentTask(id="t3", title="C", objective="c", agent="z",
                          status="ready"),
            ],
        )
        ready = plan.ready_task_ids()
        assert "t2" in ready  # t1 completed, t2's deps satisfied
        assert "t3" in ready  # no deps, already ready


class TestReviewResult:
    """审查结果测试。"""

    def test_accepted(self):
        rr = ReviewResult(
            task_id="t1",
            status=ReviewDecision.ACCEPTED,
            passed_criteria=["验收通过"],
        )
        assert rr.status == ReviewDecision.ACCEPTED

    def test_revision_required(self):
        rr = ReviewResult(
            task_id="t1",
            status=ReviewDecision.REVISION_REQUIRED,
            failed_criteria=["缺少验证"],
            revision_instructions=["添加测试并重新提交"],
        )
        assert rr.status == ReviewDecision.REVISION_REQUIRED
        assert len(rr.revision_instructions) == 1


class TestEnhancedAgentResult:
    """增强的 AgentResult 测试。"""

    def test_to_agent_result_completed(self):
        """completed 状态的 EnhancedAgentResult 应转换为 completed。"""
        from app.domain.models import AgentResult as OrigResult
        er = EnhancedAgentResult(
            task_id="t1",
            agent="test",
            status="completed",
            summary="完成",
            changes=["file.ts"],
            verification_result="passed",
        )
        ar = er.to_agent_result()
        assert isinstance(ar, OrigResult)
        assert ar.status == "completed"
        assert ar.changed_files == ["file.ts"]

    def test_to_agent_result_failed(self):
        """failed 状态的 EnhancedAgentResult 应转换为 failed。"""
        from app.domain.models import AgentResult as OrigResult
        er = EnhancedAgentResult(
            task_id="t1",
            agent="test",
            status="failed",
            summary="失败",
            error="something went wrong",
        )
        ar = er.to_agent_result()
        assert ar.status == "failed"

    def test_from_agent_result(self):
        """从现有 AgentResult 升级。"""
        from app.domain.models import AgentResult as OrigResult
        orig = OrigResult(
            task_id="t1",
            agent="test",
            status="completed",
            summary="done",
            changed_files=["a.ts"],
        )
        er = EnhancedAgentResult.from_agent_result(orig)
        assert er.task_id == "t1"
        assert er.status == "completed"
        assert er.changes == ["a.ts"]


class TestArtifactAndDecision:
    """产物和决策模型测试。"""

    def test_artifact(self):
        a = Artifact(type="file", path_or_id="/path/to/file", description="配置文件")
        assert a.type == "file"
        assert a.path_or_id == "/path/to/file"

    def test_decision(self):
        d = Decision(decision="使用 JWT", reason="无状态认证")
        assert d.decision == "使用 JWT"
