"""构建动态任务 DAG 的 LangGraph。

图拓扑本身保持稳定，DeepSeek 生成的动态任务通过 ``Send`` 分发到 worker。
每一轮只调度依赖已满足的任务；并行 worker 的结果使用 reducer 合并，全部结束后
统一进入 barrier 汇流，再回到 scheduler 计算下一轮。
"""

from __future__ import annotations

import operator
import threading
import time
from datetime import datetime, timezone
from typing import Annotated, Any

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send, interrupt, Command
from typing_extensions import TypedDict

from app.agents.claude_executor import ClaudeAgentExecutor
from app.domain.models import AgentResult, DagTask, TaskDag
from app.events.publisher import EventPublisher
from app.planning.deepseek_planner import DeepSeekPlanner
from typing import Protocol


class AgentExecutorProtocol(Protocol):
    def execute(self, run_id: str, task: DagTask, dependency_results: list[AgentResult],
                cancel_event: threading.Event, workspace_root: str,
                max_turns: int | None = None, timeout_seconds: int | None = None,
                project_id: str | None = None) -> AgentResult: ...


class GraphState(TypedDict, total=False):
    run_id: str
    objective: str
    guidance: str  # 运行中途用户注入的引导指令
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
    project_id: str
    final_answer: str
    # LangMem 长期记忆写入的会话摘要
    session_summary: str


def build_graph(
    planner: DeepSeekPlanner,
    executor: ClaudeAgentExecutor,
    events: EventPublisher,
    cancel_event: threading.Event,
    checkpointer=None,
    interrupt_router: object | None = None,
    memory_manager: object | None = None,
    project_agents: list | None = None,
    deepseek_executor=None,
    rag_executor=None,
    file_agent_executor=None,
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
        elif not project_agents:
            # 没有项目 Agent 时跳过发现阶段，直接由主脑规划
            events.emit(
                run_id,
                "workspace.discovery_skipped",
                payload={"reason": "no-project-agents"},
            )
            dag = planner.create_dag(
                state["objective"],
                state["workspace_root"],
                run_id=run_id,
                guidance=state.get("guidance", ""),
                project_agents=project_agents,
            )
            stage = "execution"
        else:
            # 有项目 Agent 时，直接让主脑 judge + 规划（跳过 discovery stage）
            # 主脑通过 prompt 自行判断：直接回答 → 空 tasks，需操作 → 1~N tasks
            dag = planner.create_dag(
                state["objective"],
                state["workspace_root"],
                run_id=run_id,
                guidance=state.get("guidance", ""),
                project_agents=project_agents,
            )
            stage = "execution"
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
            guidance=state.get("guidance", ""),
            discovery_results=discovery_results,
            project_agents=project_agents,
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

    def interrupt_check(state: GraphState) -> GraphState:
        """在每个 wave 开始前检查是否有中断指令。"""
        if interrupt_router is None:
            return {}
        pending = interrupt_router.check_and_clear(state["run_id"])
        if not pending:
            return {}
        # 收集所有 inject 类型的指令（不暂停，直接注入上下文）
        inject_instructions = []
        pause_commands = []
        for cmd in pending:
            if cmd.get("action") == "inject":
                inject_instructions.append(cmd.get("instruction", ""))
            else:
                pause_commands.append(cmd)
        events.emit(
            state["run_id"],
            "interrupt.received",
            payload={
                "count": len(pending),
                "injected": len(inject_instructions),
                "commands": [
                    {
                        "id": cmd.get("id"),
                        "target": cmd.get("target"),
                        "action": cmd.get("action"),
                        "target_agent": cmd.get("target_agent_id"),
                        "instruction": cmd.get("instruction", "")[:200],
                    }
                    for cmd in pending
                ],
            },
        )
        # inject 类型：直接注入为引导上下文，不暂停执行
        guidance = "\n".join(inject_instructions) if inject_instructions else ""
        result: dict = {}
        if guidance:
            existing = state.get("guidance", "")
            result["guidance"] = f"[用户引导]\n{guidance}\n\n{existing}" if existing else f"[用户引导]\n{guidance}"
        # pause/abort 类型：暂停图执行
        if pause_commands:
            decision = interrupt({
                "message": "收到用户中断指令",
                "pending_commands": pause_commands,
                "active_tasks": state.get("active_task_ids", []),
                "current_stage": state.get("stage"),
            })
            if isinstance(decision, dict):
                action = decision.get("action", "continue")
                if action == "replan":
                    result["stage"] = "replan_requested"
                elif action == "abort":
                    cancel_event.set()
        return result

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
                        "continuation_context": state.get("guidance", ""),
                    },
                )
                for task_id in active_task_ids
                if (task := task_by_id.get(task_id)) is not None
            ]

        # 没有就绪任务意味着全部完成、取消，或有任务被失败依赖阻塞。
        return "synthesize"

    def _resolve_agent_type(agent_name: str) -> str:
        """根据 agent 名称查找其类型。"""
        if project_agents:
            for a in project_agents:
                if getattr(a, 'name', '') == agent_name:
                    return getattr(a, 'agent_type', 'claude')
        return "claude"

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
        if context := state.get("guidance", ""):
            dependencies.append(
                AgentResult(
                    task_id="upstream-conversation",
                    agent="system",
                    status="completed",
                    summary=context[-6000:],
                )
            )
        # 根据 agent_type 选择 executor
        agent_type = _resolve_agent_type(task.agent)
        if agent_type == "deepseek" and deepseek_executor:
            active_executor = deepseek_executor
        elif agent_type == "rag" and rag_executor:
            active_executor = rag_executor
        elif agent_type == "file-ops" and file_agent_executor:
            active_executor = file_agent_executor
        else:
            active_executor = executor

        started_at = datetime.now(timezone.utc).isoformat()
        started_ms = int(time.time() * 1000)
        events.emit(
            state["run_id"],
            "agent.started",
            agent_id=task.agent,
            task_id=task.id,
            payload={"title": task.title, "objective": task.objective, "started_at": started_at},
        )
        result = active_executor.execute(
            state["run_id"],
            task,
            dependencies,
            cancel_event,
            workspace_root=state["workspace_root"],
            max_turns=state["agent_max_turns"],
            timeout_seconds=state["agent_timeout_seconds"],
            project_id=state.get("project_id", ""),
        )
        duration_ms = int(time.time() * 1000) - started_ms
        if result is not None:
            result.started_at = started_at
            result.duration_ms = duration_ms
        events.emit(
            state["run_id"],
            "agent.completed" if result.status == "completed" else "agent.failed",
            agent_id=task.agent,
            task_id=task.id,
            payload={
                **result.model_dump(),
                "duration_ms": duration_ms,
            },
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

    def compact_memory(state: GraphState) -> GraphState:
        """每个 wave 结束后，按滑动窗口策略压缩 Agent 消息历史。"""
        if memory_manager is None:
            return {}
        try:
            results = state.get("results", [])
            active_ids = state.get("active_task_ids", [])
            conversation_id = state.get("run_id", "")
            for result in results:
                r = AgentResult.model_validate(result) if isinstance(result, dict) else result
                messages = [{"role": "assistant", "content": r.summary}]
                memory_manager.compress_agent_messages(r.agent, conversation_id, messages)
            events.emit(
                state["run_id"], "memory.compacted",
                payload={"wave": state.get("wave_index", 0), "agents": active_ids},
            )
        except Exception:
            pass
        return {}

    def extract_memory(state: GraphState) -> GraphState:
        """全部执行完成后，用 LangMem 提取跨会话长期记忆。"""
        if memory_manager is None:
            return {}
        try:
            results_raw = state.get("results", [])
            session_summary = state.get("session_summary", state.get("final_answer", ""))
            memory_manager.extract_long_term_memory(
                state["run_id"], state["run_id"],
                session_summary=str(session_summary)[:4000],
                agent_results=list(results_raw)[-20:] if results_raw else None,
            )
            events.emit(
                state["run_id"], "memory.extracted",
                payload={"conversation_id": state["run_id"]},
            )
        except Exception:
            pass
        return {}

    def route_after_barrier(state: GraphState) -> str:
        # 直接回到 scheduler，不再区分 discovery/execution stage
        return "interrupt_check"

    def synthesize(state: GraphState) -> GraphState:
        """汇流所有 Agent 结果。如果没有任务被执行（主脑直接回答），使用 DAG summary 作为最终答案。"""
        results = [AgentResult.model_validate(item) for item in state.get("results", [])]
        if not results:
            # 主脑选择了直接回复（纯文本），没有创建任何任务
            dag_raw = state.get("dag", {})
            dag = TaskDag.model_validate(dag_raw) if dag_raw else None
            final_answer = dag.summary if dag else "无执行结果"
        else:
            parts: list[str] = []
            for r in results:
                icon = "✓" if r.status == "completed" else "✗" if r.status == "failed" else "-"
                parts.append(f"{icon} {r.agent}: {r.summary[:300]}")
            final_answer = "\n".join(parts) if parts else "无执行结果"
        events.emit(
            state["run_id"], "run.summary",
            payload={"text": final_answer, "result_count": len(results)},
        )
        return {
            "final_answer": final_answer,
            "session_summary": final_answer[:4000],
        }

    builder = StateGraph(GraphState)
    builder.add_node("plan", plan)
    builder.add_node("interrupt_check", interrupt_check)
    builder.add_node("scheduler", scheduler)
    builder.add_node("replan_after_discovery", replan_after_discovery)
    builder.add_node("worker", worker)
    builder.add_node("barrier", barrier)
    builder.add_node("extract_memory", extract_memory)
    builder.add_node("synthesize", synthesize)
    builder.add_edge(START, "plan")
    builder.add_edge("plan", "interrupt_check")
    builder.add_edge("interrupt_check", "scheduler")
    builder.add_conditional_edges(
        "scheduler", route_tasks, ["worker", "synthesize"]
    )
    # 同一 super-step 的 worker 全部完成后，只触发一次显式汇流屏障。
    builder.add_edge("worker", "barrier")
    builder.add_conditional_edges(
        "barrier", route_after_barrier, ["interrupt_check"]
    )
    builder.add_edge("replan_after_discovery", "interrupt_check")
    builder.add_edge("synthesize", "extract_memory")
    builder.add_edge("extract_memory", END)
    return builder.compile(checkpointer=checkpointer) if checkpointer else builder.compile()
