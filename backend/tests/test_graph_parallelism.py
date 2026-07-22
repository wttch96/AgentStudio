"""验证 LangGraph 分流是真并发，并且汇流屏障晚于全部 worker。"""

from __future__ import annotations

import threading
import time
from typing import Any

from app.domain.models import AgentResult, DagTask, TaskDag
from app.orchestration.graph import build_graph


class ParallelPlanner:
    def create_discovery_dag(self, objective: str) -> TaskDag:
        return TaskDag(
            summary="发现候选项目",
            tasks=[
                DagTask(
                    id="workspace-discovery-frontend",
                    title="发现前端",
                    objective="发现前端",
                    agent="frontend-agent",
                ),
                DagTask(
                    id="workspace-discovery-backend",
                    title="发现后端",
                    objective="发现后端",
                    agent="backend-agent",
                ),
                DagTask(
                    id="workspace-discovery-netty",
                    title="发现 Netty",
                    objective="发现 Netty",
                    agent="netty-agent",
                ),
            ],
        )

    def create_dag(
        self,
        objective: str,
        workspace_root: str | None = None,
        run_id: str | None = None,
        continuation_context: str = "",
        discovery_results: list[AgentResult] | None = None,
    ) -> TaskDag:
        return TaskDag(
            summary=objective,
            coordination_contract="GET /api/example 返回统一结果",
            tasks=[
                DagTask(id="frontend", title="前端", objective="前端", agent="frontend-agent"),
                DagTask(id="backend", title="后端", objective="后端", agent="backend-agent"),
                DagTask(id="netty", title="Netty", objective="Netty", agent="netty-agent"),
            ],
        )

    def summarize(
        self,
        objective: str,
        dag: TaskDag,
        results: list[AgentResult],
        run_id: str | None = None,
        continuation_context: str = "",
    ) -> str:
        return f"汇总 {len(results)} 个结果"


class BarrierExecutor:
    def __init__(self) -> None:
        # 若 worker 被串行调用，第一个任务会在这里超时，使测试失败。
        self.worker_barrier = threading.Barrier(3, timeout=2)
        self.started_at: list[float] = []
        self.dependencies: dict[str, list[AgentResult]] = {}
        self.lock = threading.Lock()

    def execute(
        self,
        run_id: str,
        task: DagTask,
        dependency_results: list[AgentResult],
        cancel_event: threading.Event,
        workspace_root: str,
        max_turns: int | None = None,
        timeout_seconds: int | None = None,
    ) -> AgentResult:
        with self.lock:
            self.started_at.append(time.monotonic())
            self.dependencies[task.id] = dependency_results
        self.worker_barrier.wait()
        return AgentResult(
            task_id=task.id,
            agent=task.agent,
            status="completed",
            summary="完成",
        )


class RecordingEvents:
    def __init__(self) -> None:
        self.items: list[tuple[str, dict[str, Any]]] = []
        self.lock = threading.Lock()

    def emit(self, run_id: str, event_type: str, **kwargs: Any) -> None:
        with self.lock:
            self.items.append((event_type, kwargs))


def test_workers_run_in_parallel_then_join_at_barrier():
    executor = BarrierExecutor()
    events = RecordingEvents()
    graph = build_graph(ParallelPlanner(), executor, events, threading.Event())

    output = graph.invoke(
        {
            "run_id": "parallel-test",
            "objective": "并行验证",
            "workspace_root": "/tmp",
            "agent_max_turns": 12,
            "agent_timeout_seconds": 900,
            "results": [],
        },
        {"max_concurrency": 3},
    )

    assert len(output["results"]) == 6
    assert max(executor.started_at[:3]) - min(executor.started_at[:3]) < 0.5
    assert max(executor.started_at[3:]) - min(executor.started_at[3:]) < 0.5

    event_types = [event_type for event_type, _ in events.items]
    assert event_types.count("wave.started") == 2
    assert event_types.count("wave.completed") == 2
    assert "brain.contract_created" in event_types
    for task_id in ("frontend", "backend", "netty"):
        assert any(
            result.task_id == "deepseek-coordination-contract"
            for result in executor.dependencies[task_id]
        )
    assert event_types.index("planner.started") > event_types.index("wave.completed")
    assert event_types.index("brain.contract_created") > event_types.index("planner.started")
    last_wave_completed = max(
        index for index, event_type in enumerate(event_types) if event_type == "wave.completed"
    )
    last_agent_completed = max(
        index for index, event_type in enumerate(event_types) if event_type == "agent.completed"
    )
    assert last_wave_completed > last_agent_completed
    assert event_types.index("brain.synthesizing") > last_wave_completed
