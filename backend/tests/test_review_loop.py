"""审查和重新规划流程测试。"""

import pytest

from app.domain.models import AgentResult, DagTask, TaskDag, ReviewDecision
from app.planning.execution_plan import ReviewResult
from app.orchestration.reviewer import WaveReviewer, NoOpReviewer


class TestWaveReviewer:
    """审查器基础测试。"""

    def test_completed_task_accepted(self):
        """完成的正常任务应被接受。"""
        reviewer = WaveReviewer()
        results = [
            AgentResult(task_id="t1", agent="test", status="completed",
                        summary="成功完成了所有要求的工作，运行了测试并验证通过"),
        ]
        dag = TaskDag(summary="test", tasks=[
            DagTask(id="t1", title="Test", objective="测试", agent="test"),
        ])
        review_results = reviewer.review_wave("run-1", ["t1"], results, dag)
        assert len(review_results) == 1
        assert review_results[0].status == ReviewDecision.ACCEPTED

    def test_failed_task_revision_required(self):
        """失败的任务应要求返工。"""
        reviewer = WaveReviewer()
        results = [
            AgentResult(task_id="t1", agent="test", status="failed",
                        summary="执行出错", error="Connection refused"),
        ]
        dag = TaskDag(summary="test", tasks=[
            DagTask(id="t1", title="Test", objective="测试", agent="test"),
        ])
        review_results = reviewer.review_wave("run-1", ["t1"], results, dag, iteration=0)
        assert review_results[0].status == ReviewDecision.REVISION_REQUIRED

    def test_short_summary_flag(self):
        """摘要过短的任务应被标记。"""
        reviewer = WaveReviewer()
        results = [
            AgentResult(task_id="t1", agent="test", status="completed",
                        summary="ok"),
        ]
        dag = TaskDag(summary="test", tasks=[
            DagTask(id="t1", title="Test", objective="测试", agent="test"),
        ])
        review_results = reviewer.review_wave("run-1", ["t1"], results, dag)
        assert review_results[0].status in (
            ReviewDecision.REVISION_REQUIRED,
            ReviewDecision.ACCEPTED_WITH_RISKS,
        )

    def test_max_iterations_reached(self):
        """达到最大迭代次数后应拒绝。"""
        reviewer = WaveReviewer()
        results = [
            AgentResult(task_id="t1", agent="test", status="failed",
                        summary="第N次失败"),
        ]
        dag = TaskDag(summary="test", tasks=[
            DagTask(id="t1", title="Test", objective="测试", agent="test"),
        ])
        review_results = reviewer.review_wave("run-1", ["t1"], results, dag,
                                               iteration=3, max_iterations=3)
        assert review_results[0].status == ReviewDecision.REJECTED

    def test_should_replan(self):
        """有返工需求时应触发重新规划。"""
        reviewer = WaveReviewer()
        rr = [
            ReviewResult(task_id="t1", status=ReviewDecision.ACCEPTED),
            ReviewResult(task_id="t2", status=ReviewDecision.REVISION_REQUIRED,
                         failed_criteria=["测试失败"],
                         revision_instructions=["修复测试"]),
        ]
        assert reviewer.should_replan(rr) is True

    def test_should_not_replan_all_accepted(self):
        """全部通过时不应重新规划。"""
        reviewer = WaveReviewer()
        rr = [
            ReviewResult(task_id="t1", status=ReviewDecision.ACCEPTED),
            ReviewResult(task_id="t2", status=ReviewDecision.ACCEPTED_WITH_RISKS),
        ]
        assert reviewer.should_replan(rr) is False

    def test_generate_revision_tasks(self):
        """应能生成修正任务。"""
        reviewer = WaveReviewer()
        review_results = [
            ReviewResult(
                task_id="t1", status=ReviewDecision.REVISION_REQUIRED,
                failed_criteria=["缺少测试"],
                revision_instructions=["添加单元测试", "运行并验证通过"],
            ),
        ]
        original_tasks = [
            DagTask(id="t1", title="原任务", objective="完成功能",
                    agent="test", write_scope=["src/"]),
        ]
        revision = reviewer.generate_revision_tasks(review_results, original_tasks)
        assert len(revision) > 0
        assert "修正" in revision[0].title
        assert "添加单元测试" in revision[0].objective
        assert revision[0].agent == "test"


class TestNoOpReviewer:
    """不做审查的审查器测试。"""

    def test_always_accepts(self):
        """NoOpReviewer 应总是接受。"""
        reviewer = NoOpReviewer()
        results = [
            AgentResult(task_id="t1", agent="test", status="failed",
                        summary="crash", error="BOOM"),
        ]
        dag = TaskDag(summary="test", tasks=[
            DagTask(id="t1", title="T", objective="O", agent="X"),
        ])
        review_results = reviewer.review_wave("run", ["t1"], results, dag)
        assert review_results[0].status == ReviewDecision.ACCEPTED

    def test_never_replans(self):
        """NoOpReviewer 绝不应触发重新规划。"""
        reviewer = NoOpReviewer()
        assert reviewer.should_replan([]) is False


class TestStateTransition:
    """状态转换测试。"""

    def test_completed_goes_to_review(self):
        """Agent completed → 审查 → accepted 链。"""
        # 这测试的是逻辑链: Agent completed 不等于最终完成
        reviewer = WaveReviewer()
        result = AgentResult(task_id="t1", agent="test", status="completed",
                             summary="完成了任务并运行了所有测试，验证通过")
        dag = TaskDag(summary="test", tasks=[
            DagTask(id="t1", title="Test", objective="测试", agent="test"),
        ])
        review = reviewer.review_wave("r", ["t1"], [result], dag)
        # 正常完成应能通过审查
        assert review[0].status in (ReviewDecision.ACCEPTED, ReviewDecision.ACCEPT_WITH_RISKS)

    def test_failed_never_becomes_completed(self):
        """Agent failed 绝不应直接变成 completed。"""
        reviewer = WaveReviewer()
        result = AgentResult(task_id="t1", agent="test", status="failed",
                             summary="failed", error="something")
        dag = TaskDag(summary="test", tasks=[
            DagTask(id="t1", title="Test", objective="测试", agent="test"),
        ])
        review = reviewer.review_wave("r", ["t1"], [result], dag)
        assert review[0].status != ReviewDecision.ACCEPTED
