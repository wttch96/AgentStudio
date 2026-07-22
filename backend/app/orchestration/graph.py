"""构建动态任务 DAG 的 LangGraph。

图拓扑本身保持稳定，DeepSeek 生成的动态任务通过 ``Send`` 分发到 worker。
每一轮只调度依赖已满足的任务；并行 worker 的结果使用 reducer 合并，全部结束后
统一进入 barrier 汇流，再回到 scheduler 计算下一轮。
"""

from __future__ import annotations

import operator
import threading
from typing import Annotated, Any

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send
from typing_extensions import TypedDict

from app.agents.claude_executor import ClaudeAgentExecutor
from app.domain.models import AgentResult, DagTask, TaskDag
from app.events.publisher import EventPublisher
from app.planning.deepseek_planner import DeepSeekPlanner


class GraphState(TypedDict, total=False):
    run_id: str
    objective: str
    continuation_context: str
    preset_dag: dict[str, Any] | None
    direct_mode: bool
    stage: str
    workspace_root: str
    dag: dict[str, Any]
    task: dict[str, Any]
    results: Annotated[list[dict[str, Any]], operator.add]
    active_task_ids: list[str]
    wave_index: int
    agent_max_turns: int
    agent_timeout_seconds: int
    final_answer: str


def build_graph(
    planner: DeepSeekPlanner,
    executor: ClaudeAgentExecutor,
    events: EventPublisher,
    cancel_event: threading.Event,
):
    def plan(state: GraphState) -> GraphState:
        run_id = state["run_id"]
        if state.get("preset_dag"):
            dag = TaskDag.model_validate(state["preset_dag"])
            stage = "execution"
            events.emit(
                run_id,
                "planner.bypassed",
                payload={"reason": "direct-agent-or-retry"},
            )
        else:
            events.emit(
                run_id,
                "workspace.discovery_started",
                payload={"workspace_root": state["workspace_root"]},
            )
            dag = planner.create_discovery_dag(state["objective"])
            stage = "discovery"
        events.emit(
            run_id,
            "plan.created",
            payload={**dag.model_dump(), "stage": stage},
        )
        return {"dag": dag.model_dump(), "results": [], "stage": stage}

    def replan_after_discovery(state: GraphState) -> GraphState:
        """项目发现汇流后由 DeepSeek 选择项目、定义共享契约并生成实施 DAG。"""

        run_id = state["run_id"]
        discovery_dag = TaskDag.model_validate(state["dag"])
        discovery_results = [
            AgentResult.model_validate(item) for item in state.get("results", [])
        ]
        events.emit(
            run_id,
            "planner.started",
            payload={"model": "deepseek", "phase": "implementation"},
        )
        implementation_dag = planner.create_dag(
            state["objective"],
            state["workspace_root"],
            run_id=run_id,
            continuation_context=state.get("continuation_context", ""),
            discovery_results=discovery_results,
        )

        # 图阶段本身已形成屏障；把成功的发现节点显式加入依赖，既记录决策来源，
        # 也让前端 DAG 能准确显示“先发现/定契约，再并行编码”的波次关系。
        successful_discovery_ids = [
            result.task_id
            for result in discovery_results
            if result.status == "completed"
        ]
        implementation_tasks = [
            task.model_copy(
                update={
                    "depends_on": list(
                        dict.fromkeys(
                            [*successful_discovery_ids, *task.depends_on]
                        )
                    )
                }
            )
            for task in implementation_dag.tasks
        ]
        combined_dag = TaskDag(
            summary=implementation_dag.summary,
            coordination_contract=implementation_dag.coordination_contract,
            tasks=[*discovery_dag.tasks, *implementation_tasks],
        )
        if combined_dag.coordination_contract:
            events.emit(
                run_id,
                "brain.contract_created",
                payload={"text": combined_dag.coordination_contract},
            )
        events.emit(
            run_id,
            "plan.created",
            payload={**combined_dag.model_dump(), "stage": "execution"},
        )
        return {"dag": combined_dag.model_dump(), "stage": "execution"}

    def ready_tasks(state: GraphState) -> list[DagTask]:
        dag = TaskDag.model_validate(state["dag"])
        results = [AgentResult.model_validate(item) for item in state.get("results", [])]
        result_by_id = {result.task_id: result for result in results}
        pending = [task for task in dag.tasks if task.id not in result_by_id]
        return [
            task
            for task in pending
            if all(
                dependency in result_by_id
                and result_by_id[dependency].status == "completed"
                for dependency in task.depends_on
            )
        ]

    def scheduler(state: GraphState) -> GraphState:
        """冻结本轮就绪集合，保证一批任务先并行完成，再计算下一批。"""

        ready = [] if cancel_event.is_set() else ready_tasks(state)
        if not ready:
            return {"active_task_ids": []}

        wave_index = state.get("wave_index", 0) + 1
        task_ids = [task.id for task in ready]
        events.emit(
            state["run_id"],
            "wave.started",
            payload={
                "wave": wave_index,
                "task_ids": task_ids,
                "agents": [task.agent for task in ready],
            },
        )
        return {"active_task_ids": task_ids, "wave_index": wave_index}

    def route_tasks(state: GraphState):
        dag = TaskDag.model_validate(state["dag"])
        task_by_id = {task.id: task for task in dag.tasks}
        active_task_ids = state.get("active_task_ids", [])
        if active_task_ids:
            return [
                Send(
                    "worker",
                    {
                        "run_id": state["run_id"],
                        "workspace_root": state["workspace_root"],
                        "dag": state["dag"],
                        "task": task.model_dump(),
                        "results": state.get("results", []),
                        "agent_max_turns": state["agent_max_turns"],
                        "agent_timeout_seconds": state["agent_timeout_seconds"],
                        "continuation_context": state.get("continuation_context", ""),
                    },
                )
                for task_id in active_task_ids
                if (task := task_by_id.get(task_id)) is not None
            ]

        # 没有就绪任务意味着全部完成、取消，或有任务被失败依赖阻塞。
        return "synthesize"

    def worker(state: GraphState) -> GraphState:
        task = DagTask.model_validate(state["task"])
        dag = TaskDag.model_validate(state["dag"])
        previous_results = [
            AgentResult.model_validate(item) for item in state.get("results", [])
        ]
        dependencies = [
            result for result in previous_results if result.task_id in task.depends_on
        ]
        if dag.coordination_contract and not task.id.startswith("workspace-discovery-"):
            dependencies.append(
                AgentResult(
                    task_id="deepseek-coordination-contract",
                    agent="deepseek-brain",
                    status="completed",
                    summary=dag.coordination_contract,
                )
            )
        if context := state.get("continuation_context", ""):
            dependencies.append(
                AgentResult(
                    task_id="upstream-conversation",
                    agent="system",
                    status="completed",
                    summary=context[-6000:],
                )
            )
        events.emit(
            state["run_id"],
            "agent.started",
            agent_id=task.agent,
            task_id=task.id,
            payload={"title": task.title, "objective": task.objective},
        )
        result = executor.execute(
            state["run_id"],
            task,
            dependencies,
            cancel_event,
            workspace_root=state["workspace_root"],
            max_turns=state["agent_max_turns"],
            timeout_seconds=state["agent_timeout_seconds"],
        )
        events.emit(
            state["run_id"],
            "agent.completed" if result.status == "completed" else "agent.failed",
            agent_id=task.agent,
            task_id=task.id,
            payload=result.model_dump(),
        )
        # reducer 会把每个并行 worker 的单个结果合并回共享状态。
        return {"results": [result.model_dump()]}

    def barrier(state: GraphState) -> GraphState:
        """本轮所有 Send worker 返回后，LangGraph 才会执行一次此节点。"""

        active_task_ids = state.get("active_task_ids", [])
        results = [AgentResult.model_validate(item) for item in state.get("results", [])]
        result_by_id = {result.task_id: result for result in results}
        events.emit(
            state["run_id"],
            "wave.completed",
            payload={
                "wave": state.get("wave_index", 0),
                "task_ids": active_task_ids,
                "statuses": {
                    task_id: result_by_id[task_id].status
                    for task_id in active_task_ids
                    if task_id in result_by_id
                },
            },
        )
        return {}

    def route_after_barrier(state: GraphState) -> str:
        return "replan_after_discovery" if state.get("stage") == "discovery" else "scheduler"

    def synthesize(state: GraphState) -> GraphState:
        dag = TaskDag.model_validate(state["dag"])
        results = [AgentResult.model_validate(item) for item in state.get("results", [])]
        if state.get("direct_mode"):
            result = results[-1] if results else None
            if result:
                final_answer = result.summary
                if result.error:
                    final_answer = f"{final_answer}\n\n失败原因：{result.error}"
            else:
                final_answer = "指定 Agent 没有返回执行结果。"
            events.emit(
                state["run_id"],
                "run.summary",
                payload={"text": final_answer, "direct_agent": True},
            )
            return {"final_answer": final_answer}
        events.emit(
            state["run_id"],
            "brain.synthesizing",
            payload={"model": "deepseek", "result_count": len(results)},
        )
        final_answer = planner.summarize(
            state["objective"],
            dag,
            results,
            run_id=state["run_id"],
            continuation_context=state.get("continuation_context", ""),
        )
        events.emit(
            state["run_id"], "run.summary", payload={"text": final_answer}
        )
        return {"final_answer": final_answer}

    builder = StateGraph(GraphState)
    builder.add_node("plan", plan)
    builder.add_node("scheduler", scheduler)
    builder.add_node("replan_after_discovery", replan_after_discovery)
    builder.add_node("worker", worker)
    builder.add_node("barrier", barrier)
    builder.add_node("synthesize", synthesize)
    builder.add_edge(START, "plan")
    builder.add_edge("plan", "scheduler")
    builder.add_conditional_edges(
        "scheduler", route_tasks, ["worker", "synthesize"]
    )
    # 同一 super-step 的 worker 全部完成后，只触发一次显式汇流屏障。
    builder.add_edge("worker", "barrier")
    builder.add_conditional_edges(
        "barrier",
        route_after_barrier,
        ["replan_after_discovery", "scheduler"],
    )
    builder.add_edge("replan_after_discovery", "scheduler")
    builder.add_edge("synthesize", END)
    return builder.compile()
