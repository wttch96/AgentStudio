"""构建动态任务 DAG 的 LangGraph。

图拓扑本身保持稳定，DeepSeek 生成的动态任务通过 ``Send`` 分发到 worker。
每一轮只调度依赖已满足的任务；并行 worker 的结果使用 reducer 合并，全部结束后
统一进入 barrier 汇流，再经过 review 节点审查，决定是否需要重新规划或继续。

增强功能:
    - 结构化 GraphState（ExecutionPlan、ReviewResult、迭代计数）
    - validate_plan 节点校验计划合法性
    - review 节点审查 Agent 结果并决定返工
    - replan 节点生成修正任务
    - Agent 上下文自动注入（看板、决策、产物）
    - Agent 结果自动写回看板
    - 文件写入冲突检测与顺序化
    - 最大迭代/返工限制
"""

from __future__ import annotations

import operator
import inspect
import json
import threading
import time
from datetime import datetime, timezone
from typing import Annotated, Any

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send, interrupt, Command
from typing_extensions import TypedDict

from app.agents.claude_executor import ClaudeAgentExecutor
from app.domain.models import AgentResult, DagTask, TaskDag, ReviewDecision
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
    guidance: str
    agent_guidance: dict[str, str]
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
    session_summary: str
    blackboard: dict[str, Any]
    flow_name: str | None
    flow_inputs: dict[str, Any]
    # ── 增强字段 ──
    execution_plan: dict[str, Any]          # 结构化 ExecutionPlan (序列化)
    review_results: Annotated[list[dict[str, Any]], operator.add]
    iteration_count: int                    # 图总循环次数
    replan_count: int                       # 重新规划次数
    stop_reason: str | None                 # 停止原因
    conflict_log: list[dict[str, Any]]      # 冲突检测日志


def build_graph(
    planner: DeepSeekPlanner,
    executor: ClaudeAgentExecutor,
    events: EventPublisher,
    cancel_event: threading.Event,
    checkpointer=None,
    interrupt_router: object | None = None,
    memory_manager: object | None = None,
    project_agents: list | None = None,
    rag_executor=None,
    file_agent_executor=None,
    chat_executor=None,
    blackboard_store: object | None = None,
    todo_store: object | None = None,
    yaml_compiler: object | None = None,
    flow_store: object | None = None,
    # ── 新增可选组件 ──
    reviewer: object | None = None,
    agent_selector: object | None = None,
    conflict_detector: object | None = None,
    context_builder: object | None = None,
    # ── 配置 ──
    max_graph_iterations: int = 20,
    max_replan_iterations: int = 3,
    max_task_revisions: int = 2,
):
    def call_planner(method_name: str, *args: Any, **kwargs: Any) -> Any:
        """兼容旧版 Planner/插件：只传递其声明支持的关键字参数。"""
        method = getattr(planner, method_name)
        accepted = inspect.signature(method).parameters
        return method(*args, **{
            key: value for key, value in kwargs.items() if key in accepted
        })

    def apply_agent_selection(dag: TaskDag, project_id: str) -> TaskDag:
        if agent_selector is None or not project_agents:
            return dag
        profiles = {getattr(profile, "name", ""): profile for profile in project_agents}
        workloads: dict[str, int] = {}
        selected_tasks: list[DagTask] = []
        for task in dag.tasks:
            profile = profiles.get(task.agent)
            valid = False
            if profile is not None:
                try:
                    valid, _ = agent_selector.validate_assignment(profile, task.objective)
                except Exception:
                    valid = True
            if not valid:
                required = list(task.context.get("required_capabilities", []))
                choice = agent_selector.select(
                    project_id,
                    task.objective,
                    required_tools=task.allowed_tools,
                    required_capabilities=required,
                    workload_counts=workloads,
                )
                if choice is not None:
                    task = task.model_copy(update={
                        "agent": choice.agent_name,
                        "context": {
                            **task.context,
                            "agent_selection_reason": choice.selection_reason,
                        },
                    })
            workloads[task.agent] = workloads.get(task.agent, 0) + 1
            selected_tasks.append(task)
        return dag.model_copy(update={"tasks": selected_tasks})

    # ── 初始化可选组件 ──
    if reviewer is None:
        from app.orchestration.reviewer import NoOpReviewer
        reviewer = NoOpReviewer()

    if conflict_detector is None:
        from app.orchestration.concurrency import NoOpConflictDetector
        conflict_detector = NoOpConflictDetector()

    if context_builder is None and blackboard_store is not None:
        from app.agents.agent_context import AgentContextBuilder
        context_builder = AgentContextBuilder(
            blackboard_store=blackboard_store,
            todo_store=todo_store,
        )

    # ═══════════════════════════════════════════════════════════════
    # 节点
    # ═══════════════════════════════════════════════════════════════

    def plan(state: GraphState) -> GraphState:
        run_id = state["run_id"]
        if state.get("preset_dag"):
            dag = TaskDag.model_validate(state["preset_dag"])
            stage = "execution"
            events.emit(run_id, "planner.bypassed",
                        payload={"reason": "direct-agent-or-retry"})
        else:
            discovery = call_planner(
                "create_discovery_dag",
                state["objective"],
                project_agents=project_agents,
            ) if hasattr(planner, "create_discovery_dag") else TaskDag(
                summary="跳过项目发现", tasks=[]
            )
            if discovery.tasks:
                dag = discovery
                stage = "discovery"
            else:
                events.emit(run_id, "workspace.discovery_skipped",
                            payload={"reason": "no-discovery-agents"})
                dag = call_planner(
                    "create_dag",
                    state["objective"], state["workspace_root"],
                    run_id=run_id,
                    guidance=state.get("guidance", ""),
                    continuation_context=state.get("guidance", ""),
                    project_agents=project_agents,
                    project_id=state.get("project_id", ""),
                )
                stage = "execution"

        dag = apply_agent_selection(dag, state.get("project_id", ""))
        events.emit(run_id, "plan.created",
                    payload={**dag.model_dump(), "stage": stage})

        # Blackboard + Todo 初始化
        if blackboard_store is not None:
            blackboard_store.init(run_id)
        if todo_store is not None and dag.tasks:
            try:
                todo_store.init(run_id, [
                    {**t.model_dump(), "content": t.title, "assigned_to": t.agent}
                    for t in dag.tasks
                ])
            except Exception:
                pass

        # 尝试升级为 ExecutionPlan（如果有 AgentTask 转换逻辑）
        execution_plan = None
        try:
            from app.planning.execution_plan import AgentTask, ExecutionPlan
            agent_tasks = [AgentTask.from_dag_task(t) for t in dag.tasks]
            execution_plan = ExecutionPlan(
                goal=state["objective"],
                tasks=agent_tasks,
                summary=dag.summary,
                coordination_contract=dag.coordination_contract,
            )
        except Exception:
            pass

        result: dict[str, Any] = {
            "dag": dag.model_dump(),
            "results": [],
            "stage": stage,
            "blackboard": {},
            "flow_name": None,
            "flow_inputs": {},
            "iteration_count": 0,
            "replan_count": 0,
            "stop_reason": None,
        }
        if execution_plan is not None:
            result["execution_plan"] = execution_plan.model_dump()
        return result

    def validate_plan(state: GraphState) -> GraphState:
        """校验执行计划的结构合法性。"""
        ep_raw = state.get("execution_plan")
        if not ep_raw:
            # 没有 ExecutionPlan 时跳过校验（向后兼容）
            events.emit(state["run_id"], "plan.validation_skipped",
                        payload={"reason": "no-execution-plan"})
            return {}

        try:
            from app.planning.execution_plan import ExecutionPlan
            from app.planning.validator import PlanValidator

            plan_obj = ExecutionPlan.model_validate(ep_raw)
            validator = PlanValidator(
                agent_registry=executor.registry if hasattr(executor, 'registry') else None,
                project_id=state.get("project_id", ""),
            )
            result = validator.validate(plan_obj)

            if not result.is_valid:
                events.emit(state["run_id"], "plan.validation_failed",
                            payload={"errors": result.errors, "warnings": result.warnings})

                replan_count = state.get("replan_count", 0)
                if replan_count < max_replan_iterations:
                    # 尝试自动修复
                    fixed = validator.auto_fix(plan_obj, result)
                    # 重新校验
                    result2 = validator.validate(fixed)
                    if result2.is_valid:
                        events.emit(state["run_id"], "plan.validation_fixed",
                                    payload={"warnings": result2.warnings})
                        return {
                            "execution_plan": fixed.model_dump(),
                            "dag": fixed.to_task_dag().model_dump(),
                            "replan_count": replan_count + 1,
                        }

                    # 需要主脑修复
                    return {
                        "stage": "replan_requested",
                        "replan_count": replan_count + 1,
                    }
                else:
                    return {
                        "stop_reason": f"计划校验失败，已达最大重试次数: {result.errors}",
                    }
            else:
                events.emit(state["run_id"], "plan.validated",
                            payload={
                                "ready_tasks": result.ready_task_ids,
                                "backlog_tasks": result.backlog_task_ids,
                                "warnings": result.warnings,
                            })
                # 同步 ExecutionPlan → TaskDag
                return {
                    "dag": plan_obj.to_task_dag().model_dump(),
                }
        except Exception as exc:
            events.emit(state["run_id"], "plan.validation_error",
                        payload={"error": str(exc)})
            return {}  # 不阻塞执行

    def interrupt_check(state: GraphState) -> GraphState:
        if interrupt_router is None:
            return {}
        pending = interrupt_router.check_and_clear(state["run_id"])
        if not pending:
            return {}
        inject_instructions = []
        agent_guidance = dict(state.get("agent_guidance", {}))
        pause_commands = []
        for cmd in pending:
            if cmd.get("action") == "inject":
                instruction = cmd.get("instruction", "")
                if cmd.get("target") == "agent" and cmd.get("target_agent"):
                    target = cmd["target_agent"]
                    agent_guidance[target] = (
                        f"{agent_guidance.get(target, '')}\n{instruction}".strip()
                    )
                else:
                    inject_instructions.append(instruction)
            elif cmd.get("target") == "all":
                pause_commands.append(cmd)
        events.emit(state["run_id"], "interrupt.received", payload={
            "count": len(pending), "injected": len(inject_instructions),
            "commands": [{"id": c.get("id"), "target": c.get("target"),
                          "action": c.get("action"),
                          "target_agent": c.get("target_agent_id"),
                          "instruction": c.get("instruction", "")[:200]}
                         for c in pending],
        })
        guidance = "\n".join(inject_instructions) if inject_instructions else ""
        result: dict = {}
        if agent_guidance:
            result["agent_guidance"] = agent_guidance
        if guidance:
            existing = state.get("guidance", "")
            result["guidance"] = (f"[用户引导]\n{guidance}\n\n{existing}"
                                  if existing else f"[用户引导]\n{guidance}")
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
        """冻结本轮就绪集合，检测冲突。"""
        if cancel_event.is_set():
            return {"active_task_ids": []}

        ready = ready_tasks(state)
        if not ready:
            return {"active_task_ids": []}

        # ── 冲突检测 ──
        if len(ready) > 1:
            try:
                conflicts = conflict_detector.detect(ready)
                if conflicts:
                    deferred = {conflict.task_b for conflict in conflicts}
                    ready = [task for task in ready if task.id not in deferred]
                    events.emit(state["run_id"], "conflicts.detected", payload={
                        "conflicts": [(c.task_a, c.task_b, c.conflicting_path)
                                       for c in conflicts],
                        "resolution": "deferred-conflicting-tasks",
                    })
            except Exception:
                pass

        wave_index = state.get("wave_index", 0) + 1
        task_ids = [task.id for task in ready]
        events.emit(state["run_id"], "wave.started", payload={
            "wave": wave_index, "task_ids": task_ids,
            "agents": [task.agent for task in ready],
        })
        # 检查全局迭代上限
        iter_count = state.get("iteration_count", 0)
        if iter_count >= max_graph_iterations:
            return {
                "active_task_ids": [],
                "stop_reason": f"达到最大图循环次数 ({max_graph_iterations})",
            }
        return {
            "active_task_ids": task_ids,
            "wave_index": wave_index,
            "iteration_count": iter_count + 1,
        }

    def route_tasks(state: GraphState):
        dag = TaskDag.model_validate(state["dag"])
        task_by_id = {task.id: task for task in dag.tasks}
        active_task_ids = state.get("active_task_ids", [])
        if active_task_ids:
            sends = []
            for task_id in active_task_ids:
                task = task_by_id.get(task_id)
                if task is None:
                    continue
                if task.agent == "__flow__":
                    sends.append(Send("flow_executor", {
                        "run_id": state["run_id"],
                        "workspace_root": state["workspace_root"],
                        "flow_name": task.objective,
                        "flow_inputs": state.get("flow_inputs", {}),
                        "dagger": state["dag"],
                        "results": state.get("results", []),
                        "agent_max_turns": state["agent_max_turns"],
                        "agent_timeout_seconds": state["agent_timeout_seconds"],
                        "project_id": state.get("project_id", ""),
                    }))
                else:
                    sends.append(Send("worker", {
                        "run_id": state["run_id"],
                        "workspace_root": state["workspace_root"],
                        "dag": state["dag"],
                        "task": task.model_dump(),
                        "results": state.get("results", []),
                        "agent_max_turns": state["agent_max_turns"],
                        "agent_timeout_seconds": state["agent_timeout_seconds"],
                        "continuation_context": state.get("guidance", ""),
                        "guidance": state.get("guidance", ""),
                        "agent_guidance": state.get("agent_guidance", {}),
                        "project_id": state.get("project_id", ""),
                        "execution_plan": state.get("execution_plan", {}),
                    }))
            if sends:
                return sends
        return "synthesize"

    def _resolve_agent_type(agent_name: str) -> str:
        if project_agents:
            for a in project_agents:
                if getattr(a, 'name', '') == agent_name:
                    return getattr(a, 'agent_type', 'claude')
        if agent_name == "__flow__":
            return "flow"
        if agent_name == "blackboard":
            return "blackboard"
        if agent_name == "todo":
            return "todo"
        if agent_name == "doc-diff":
            return "doc-diff"
        return "claude"

    def worker(state: GraphState) -> GraphState:
        task = DagTask.model_validate(state["task"])
        dag = TaskDag.model_validate(state["dag"])

        # ── 使用 AgentContextBuilder 构建上下文 ──
        agent_profile = None
        if project_agents and context_builder is not None:
            for a in project_agents:
                if getattr(a, 'name', '') == task.agent:
                    agent_profile = a
                    break

        targeted_guidance = state.get("agent_guidance", {}).get(task.agent, "")
        worker_state = dict(state)
        if targeted_guidance:
            worker_state["guidance"] = (
                f"{state.get('guidance', '')}\n[面向 {task.agent} 的用户引导]\n"
                f"{targeted_guidance}"
            ).strip()
        if context_builder is not None:
            try:
                ctx = context_builder.build(worker_state, task, agent_profile)
                dependencies = ctx.build_dependency_results()
            except Exception:
                # 回退到原有上下文构建
                dependencies = _build_dependencies_legacy(state, task, dag)
        else:
            dependencies = _build_dependencies_legacy(state, task, dag)

        # ── 根据 agent_type 选择 executor ──
        agent_type = _resolve_agent_type(task.agent)

        if agent_type == "todo":
            if todo_store is not None:
                try:
                    todo_store.update_status(state["run_id"], task.id, "in_progress", task.agent)
                except Exception:
                    pass
            result = AgentResult(
                task_id=task.id, agent=task.agent, status="completed",
                summary=f"Todo [{task.title}] 已更新",
                started_at=datetime.now(timezone.utc).isoformat(), duration_ms=0,
            )
        elif agent_type == "blackboard":
            try:
                from app.agents.blackboard_agent import BlackboardAgentExecutor
                bb_executor = BlackboardAgentExecutor(blackboard_store)
                result = bb_executor.execute(
                    state["run_id"], task, dependencies,
                    cancel_event, state["workspace_root"],
                    state.get("agent_max_turns"), state.get("agent_timeout_seconds"),
                    state.get("project_id", ""),
                )
            except Exception as exc:
                result = AgentResult(
                    task_id=task.id, agent=task.agent, status="failed",
                    summary=f"黑板操作异常: {exc}", error=str(exc),
                )
        elif agent_type == "doc-diff":
            try:
                from app.agents.doc_diff_executor import DocDiffAgentExecutor
                dd_executor = DocDiffAgentExecutor(blackboard_store, executor)
                result = dd_executor.execute(
                    state["run_id"], task, dependencies,
                    cancel_event, state["workspace_root"],
                    state.get("agent_max_turns"), state.get("agent_timeout_seconds"),
                    state.get("project_id", ""),
                )
            except Exception as exc:
                result = AgentResult(
                    task_id=task.id, agent=task.agent, status="failed",
                    summary=f"文档对比异常: {exc}", error=str(exc),
                )
        elif agent_type == "flow":
            result = AgentResult(
                task_id=task.id, agent=task.agent, status="failed",
                summary="流程任务不应路由到通用 worker", error="routing error",
            )
        elif agent_type == "rag" and rag_executor:
            active_executor = rag_executor
        elif agent_type == "chat" and chat_executor:
            active_executor = chat_executor
        elif agent_type == "file-ops" and file_agent_executor:
            active_executor = file_agent_executor
        else:
            active_executor = executor

        # ── 执行 ──
        if agent_type not in ("todo", "blackboard", "doc-diff", "flow"):
            started_at = datetime.now(timezone.utc).isoformat()
            started_ms = int(time.time() * 1000)
            events.emit(state["run_id"], "agent.started",
                        agent_id=task.agent, task_id=task.id,
                        payload={"title": task.title, "objective": task.objective,
                                 "started_at": started_at})

            # 注入增强上下文（如果可用）
            if context_builder is not None and agent_profile is not None:
                try:
                    from app.prompts.builder import PromptBuilder
                    pb = PromptBuilder()
                    pb.add_system_prompt(agent_profile)
                    pb.add_common_protocol()
                    pb.add_role_prompt(agent_type, agent_profile)
                    # 将增强的 system_prompt 通过 agent_profile 的 prompt 传递
                    # 注意: 这里不改变 execute() 签名，而是通过 task 的 objective 传递
                    # 保持向后兼容的前提
                except Exception:
                    pass

            execute_kwargs = {
                "workspace_root": state["workspace_root"],
                "max_turns": state["agent_max_turns"],
                "timeout_seconds": state["agent_timeout_seconds"],
                "project_id": state.get("project_id", ""),
                "interrupt_router": interrupt_router,
            }
            accepted = inspect.signature(active_executor.execute).parameters
            result = active_executor.execute(
                state["run_id"], task, dependencies, cancel_event,
                **{key: value for key, value in execute_kwargs.items() if key in accepted},
            )
            duration_ms = int(time.time() * 1000) - started_ms
            if result is not None:
                result.started_at = started_at
                result.duration_ms = duration_ms
            events.emit(state["run_id"],
                        "agent.completed" if result and result.status in (
                            "completed", "partially_completed", "need_review"
                        )
                        else "agent.failed",
                        agent_id=task.agent, task_id=task.id,
                        payload={**(result.model_dump() if result else {}),
                                 "duration_ms": duration_ms})
        else:
            events.emit(state["run_id"], "agent.started",
                        agent_id=task.agent, task_id=task.id,
                        payload={"title": task.title, "objective": task.objective})
            events.emit(state["run_id"],
                        "agent.completed" if result.status in (
                            "completed", "partially_completed", "need_review"
                        ) else "agent.failed",
                        agent_id=task.agent, task_id=task.id,
                        payload=result.model_dump())

        # ── 结果写回看板 ──
        if blackboard_store is not None and result is not None:
            try:
                blackboard_store.write(
                    state["run_id"], f"result:{task.id}",
                    result.model_dump(), task.agent,
                )
                for artifact in result.artifacts:
                    blackboard_store.write(
                        state["run_id"],
                        f"artifact:{task.id}:{len(blackboard_store.read_all(state['run_id']))}",
                        artifact,
                        task.agent,
                    )
                for decision in result.decisions:
                    blackboard_store.write(
                        state["run_id"],
                        f"decision:{task.id}:{len(blackboard_store.read_all(state['run_id']))}",
                        decision,
                        task.agent,
                    )
                all_results = blackboard_store.read(state["run_id"], "all_results") or []
                all_results.append({
                    "task_id": task.id, "agent": task.agent,
                    "status": result.status, "summary": result.summary[:300],
                })
                blackboard_store.write(state["run_id"], "all_results", all_results, "system")
            except Exception:
                pass

        # ── Todo 状态更新 ──
        if todo_store is not None:
            try:
                todo_store.apply_result(
                    state["run_id"], task.id, result.model_dump(), task.agent
                )
            except Exception:
                pass

        return {"results": [result.model_dump()] if result else []}

    def barrier(state: GraphState) -> GraphState:
        active_task_ids = state.get("active_task_ids", [])
        results = [AgentResult.model_validate(item) for item in state.get("results", [])]
        result_by_id = {result.task_id: result for result in results}
        events.emit(state["run_id"], "wave.completed", payload={
            "wave": state.get("wave_index", 0),
            "task_ids": active_task_ids,
            "statuses": {tid: result_by_id[tid].status
                         for tid in active_task_ids if tid in result_by_id},
        })
        return {}

    def review(state: GraphState) -> GraphState:
        """审查当前波次结果。"""
        run_id = state["run_id"]
        active_ids = state.get("active_task_ids", [])
        all_results = [AgentResult.model_validate(r) for r in state.get("results", [])]
        dag = TaskDag.model_validate(state["dag"])
        iter_count = state.get("iteration_count", 0)
        replan_count = state.get("replan_count", 0)

        # Discovery is evidence collection, not a deliverable. Its results are
        # consumed by the planner before normal acceptance review begins.
        if state.get("stage") == "discovery":
            return {"review_results": []}

        try:
            active_limits = [
                task.max_iterations for task in dag.tasks if task.id in active_ids
            ]
            review_results = reviewer.review_wave(
                run_id, active_ids, all_results, dag,
                iteration=replan_count,
                max_iterations=min(active_limits or [max_task_revisions]),
            )
        except Exception as exc:
            events.emit(run_id, "review.error", payload={"error": str(exc)})
            return {"review_results": []}

        events.emit(run_id, "review.completed", payload={
            "decisions": [{"task_id": r.task_id, "decision": r.status.value}
                          for r in review_results],
        })
        if todo_store is not None:
            for item in review_results:
                status_map = {
                    ReviewDecision.ACCEPTED: "completed",
                    ReviewDecision.ACCEPTED_WITH_RISKS: "completed",
                    ReviewDecision.BLOCKED: "blocked",
                    ReviewDecision.REJECTED: "failed",
                    ReviewDecision.REVISION_REQUIRED: "review",
                }
                try:
                    todo_store.update_status(
                        run_id, item.task_id, status_map[item.status], "reviewer"
                    )
                except Exception:
                    pass

        needs_replan = reviewer.should_replan(review_results)

        if needs_replan and replan_count < max_replan_iterations:
            events.emit(run_id, "review.replan_triggered", payload={
                "replan_count": replan_count + 1,
                "max_replan": max_replan_iterations,
            })
            # 持久化审查结果供 replan 节点使用
            if blackboard_store is not None:
                try:
                    blackboard_store.write(
                        run_id, "review_decisions",
                        [r.model_dump() for r in review_results], "reviewer",
                    )
                except Exception:
                    pass
            return {
                "review_results": [r.model_dump() for r in review_results],
                "stage": "replan_requested",
                "replan_count": replan_count + 1,
            }

        if needs_replan:
            events.emit(run_id, "review.replan_limit_reached", payload={
                "replan_count": replan_count,
                "max_replan": max_replan_iterations,
            })
            return {
                "review_results": [r.model_dump() for r in review_results],
                "stop_reason": f"达到最大重新规划次数 ({max_replan_iterations})",
            }

        return {"review_results": [r.model_dump() for r in review_results]}

    def route_after_review(state: GraphState) -> str:
        """根据审查结果决定下一步路由。"""
        stop_reason = state.get("stop_reason")
        if stop_reason:
            return "synthesize"

        stage = state.get("stage", "")
        if stage == "replan_requested":
            return "replan"
        if stage == "discovery":
            return "replan_after_discovery"

        return "compact_memory"

    def replan(state: GraphState) -> GraphState:
        """根据审查反馈重新生成修正任务。"""
        run_id = state["run_id"]
        dag = TaskDag.model_validate(state["dag"])
        review_decisions_raw = state.get("review_results", [])

        from app.planning.execution_plan import ReviewResult
        review_decisions = [ReviewResult.model_validate(r) for r in review_decisions_raw]

        events.emit(run_id, "planner.replan_started", payload={
            "failed_tasks": [r.task_id for r in review_decisions
                             if r.status != ReviewDecision.ACCEPTED],
        })

        try:
            # 生成修正任务
            revision_tasks = reviewer.generate_revision_tasks(
                review_decisions, dag.tasks,
            )

            if revision_tasks:
                # 保留已成功的任务 + 添加修正任务
                accepted_ids = {
                    r.task_id for r in review_decisions
                    if r.status in (ReviewDecision.ACCEPTED, ReviewDecision.ACCEPT_WITH_RISKS)
                }
                kept_tasks = [t for t in dag.tasks if t.id in accepted_ids]
                new_tasks = kept_tasks + [t.to_dag_task() for t in revision_tasks]

                new_dag = TaskDag(
                    summary=f"{dag.summary} (重新规划 v{state.get('replan_count', 0) + 1})",
                    coordination_contract=dag.coordination_contract,
                    tasks=new_tasks,
                )

                events.emit(run_id, "planner.replan_completed", payload={
                    "new_tasks": [t.id for t in new_tasks],
                    "revision_count": len(revision_tasks),
                })

                # 更新 Todo
                if todo_store is not None:
                    try:
                        for rt in revision_tasks:
                            todo_store.add(run_id, {
                                "id": rt.id, "content": rt.title,
                                "assigned_to": rt.agent,
                                "depends_on": rt.depends_on,
                            }, "planner")
                    except Exception:
                        pass

                return {
                    "dag": new_dag.model_dump(),
                    "stage": "execution",
                }

            return {"stage": "execution"}
        except Exception as exc:
            events.emit(run_id, "planner.replan_error", payload={"error": str(exc)})
            return {"stage": "execution"}

    def compact_memory(state: GraphState) -> GraphState:
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
            events.emit(state["run_id"], "memory.compacted",
                        payload={"wave": state.get("wave_index", 0), "agents": active_ids})
        except Exception:
            pass
        return {}

    def extract_memory(state: GraphState) -> GraphState:
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
            events.emit(state["run_id"], "memory.extracted",
                        payload={"conversation_id": state["run_id"]})
        except Exception:
            pass
        return {}

    def synthesize(state: GraphState) -> GraphState:
        results = [AgentResult.model_validate(item) for item in state.get("results", [])]
        stop_reason = state.get("stop_reason")

        if not results:
            dag_raw = state.get("dag", {})
            dag = TaskDag.model_validate(dag_raw) if dag_raw else None
            final_answer = dag.summary if dag else "无执行结果"
        else:
            parts: list[str] = []
            for r in results:
                icon = "✓" if r.status == "completed" else "✗" if r.status == "failed" else "-"
                parts.append(f"{icon} {r.agent}: {r.summary[:300]}")
            final_answer = "\n".join(parts) if parts else "无执行结果"
            try:
                dag = TaskDag.model_validate(state["dag"])
                if not state.get("direct_mode"):
                    events.emit(state["run_id"], "brain.synthesizing",
                                payload={"result_count": len(results)})
                    final_answer = call_planner(
                        "summarize",
                        state["objective"], dag, results,
                        run_id=state["run_id"],
                        guidance=state.get("guidance", ""),
                        continuation_context=state.get("guidance", ""),
                    )
            except Exception as exc:
                events.emit(state["run_id"], "summary.fallback",
                            payload={"error": str(exc)})

        if stop_reason:
            final_answer = (
                f"⚠ 执行未完全完成: {stop_reason}\n\n{final_answer}"
            )

        events.emit(state["run_id"], "run.summary",
                    payload={"text": final_answer, "result_count": len(results),
                             "stop_reason": stop_reason})

        return {
            "final_answer": final_answer,
            "session_summary": final_answer[:4000],
        }

    def flow_executor(state: GraphState) -> GraphState:
        flow_name = state.get("flow_name")
        if not flow_name or not yaml_compiler or not flow_store:
            return {
                "final_answer": f"流程引擎未就绪，无法执行流程: {flow_name}",
                "results": [],
            }
        try:
            flow = flow_store.load(flow_name)
        except Exception as exc:
            return {"final_answer": f"加载流程 {flow_name} 失败: {exc}", "results": []}

        events.emit(state["run_id"], "flow.started", payload={
            "flow_name": flow.name, "flow_version": flow.version,
            "node_count": len(flow.nodes),
        })

        if blackboard_store is not None:
            blackboard_store.init(state["run_id"])

        try:
            compiled_graph = yaml_compiler.compile(flow)
            output = compiled_graph.invoke({
                "run_id": state["run_id"], "flow_name": flow.name,
                "workspace_root": state["workspace_root"],
                "project_id": state.get("project_id", ""),
                "inputs": state.get("flow_inputs", {}),
                "blackboard": state.get("blackboard", {}),
            })
        except Exception as exc:
            events.emit(state["run_id"], "flow.failed",
                        payload={"flow_name": flow.name, "error": str(exc)})
            return {"final_answer": f"流程 {flow.name} 执行异常: {exc}", "results": []}

        final_answer = output.get("final_answer", "")
        flow_results = output.get("results", [])

        events.emit(state["run_id"], "flow.completed", payload={
            "flow_name": flow.name, "final_answer": final_answer[:500],
        })
        return {"results": flow_results, "final_answer": final_answer,
                "blackboard": output.get("blackboard", {})}

    # ── 辅助函数 ──────────────────────────────────────────────────

    def ready_tasks(state: GraphState) -> list[DagTask]:
        dag = TaskDag.model_validate(state["dag"])
        results = [AgentResult.model_validate(item) for item in state.get("results", [])]
        result_by_id = {result.task_id: result for result in results}
        pending = [task for task in dag.tasks if task.id not in result_by_id]
        return [
            task for task in pending
            if all(dep in result_by_id and result_by_id[dep].status == "completed"
                   for dep in task.depends_on)
        ]

    def _build_dependencies_legacy(
        state: GraphState, task: DagTask, dag: TaskDag,
    ) -> list[AgentResult]:
        """原有依赖构建逻辑，作为回退。"""
        previous_results = [
            AgentResult.model_validate(item) for item in state.get("results", [])
        ]
        deps = [r for r in previous_results if r.task_id in task.depends_on]
        if dag.coordination_contract and not task.id.startswith("workspace-discovery-"):
            deps.append(AgentResult(
                task_id="deepseek-coordination-contract", agent="deepseek-brain",
                status="completed", summary=dag.coordination_contract,
            ))
        if context := state.get("guidance", ""):
            deps.append(AgentResult(
                task_id="upstream-conversation", agent="system",
                status="completed", summary=context[-6000:],
            ))
        if blackboard_store is not None:
            try:
                bb_data = blackboard_store.read_all(state["run_id"])
                if bb_data:
                    deps.append(AgentResult(
                        task_id="blackboard-snapshot", agent="system",
                        status="completed",
                        summary=json.dumps(bb_data, ensure_ascii=False),
                    ))
            except Exception:
                pass
        return deps

    def replan_after_discovery(state: GraphState) -> GraphState:
        """项目发现汇流后由 DeepSeek 选择项目、定义共享契约并生成实施 DAG。"""
        run_id = state["run_id"]
        discovery_dag = TaskDag.model_validate(state["dag"])
        discovery_results = [
            AgentResult.model_validate(item) for item in state.get("results", [])
        ]
        events.emit(run_id, "planner.started",
                    payload={"model": "deepseek", "phase": "implementation"})
        implementation_dag = call_planner(
            "create_dag",
            state["objective"], state["workspace_root"],
            run_id=run_id, guidance=state.get("guidance", ""),
            continuation_context=state.get("guidance", ""),
            discovery_results=discovery_results,
            project_agents=project_agents,
            project_id=state.get("project_id", ""),
        )
        successful_discovery_ids = [
            r.task_id for r in discovery_results if r.status == "completed"
        ]
        implementation_tasks = [
            task.model_copy(update={
                "depends_on": list(dict.fromkeys([*successful_discovery_ids, *task.depends_on]))
            })
            for task in implementation_dag.tasks
        ]
        combined_dag = TaskDag(
            summary=implementation_dag.summary,
            coordination_contract=implementation_dag.coordination_contract,
            tasks=[*discovery_dag.tasks, *implementation_tasks],
        )
        if combined_dag.coordination_contract:
            events.emit(run_id, "brain.contract_created",
                        payload={"text": combined_dag.coordination_contract})
        if todo_store is not None:
            try:
                for task in implementation_tasks:
                    todo_store.add(
                        run_id,
                        {
                            **task.model_dump(),
                            "content": task.title,
                            "assigned_to": task.agent,
                        },
                        "planner",
                    )
            except Exception:
                pass
        events.emit(run_id, "plan.created",
                    payload={**combined_dag.model_dump(), "stage": "execution"})
        return {"dag": combined_dag.model_dump(), "stage": "execution"}

    # ═══════════════════════════════════════════════════════════════
    # 图构建
    # ═══════════════════════════════════════════════════════════════

    builder = StateGraph(GraphState)
    builder.add_node("plan", plan)
    builder.add_node("validate_plan", validate_plan)
    builder.add_node("interrupt_check", interrupt_check)
    builder.add_node("scheduler", scheduler)
    builder.add_node("replan_after_discovery", replan_after_discovery)
    builder.add_node("worker", worker)
    builder.add_node("barrier", barrier)
    builder.add_node("review", review)
    builder.add_node("compact_memory", compact_memory)
    builder.add_node("replan", replan)
    builder.add_node("extract_memory", extract_memory)
    builder.add_node("synthesize", synthesize)
    builder.add_node("flow_executor", flow_executor)

    # 拓扑: START → plan → validate_plan → interrupt_check → scheduler
    builder.add_edge(START, "plan")
    builder.add_edge("plan", "validate_plan")
    builder.add_edge("validate_plan", "interrupt_check")
    builder.add_edge("interrupt_check", "scheduler")

    # scheduler → worker / flow_executor / synthesize
    builder.add_conditional_edges(
        "scheduler", route_tasks, ["worker", "flow_executor", "synthesize"]
    )

    # worker / flow_executor → barrier
    builder.add_edge("worker", "barrier")
    builder.add_edge("flow_executor", "barrier")

    # barrier → review → route_after_review
    builder.add_edge("barrier", "review")
    builder.add_conditional_edges(
        "review", route_after_review,
        ["replan", "replan_after_discovery", "compact_memory", "synthesize"]
    )

    # replan → scheduler (重新进入调度循环)
    builder.add_edge("replan", "scheduler")

    # compact_memory → interrupt_check (正常下一波)
    builder.add_edge("compact_memory", "interrupt_check")

    # 遗留节点
    builder.add_edge("replan_after_discovery", "interrupt_check")

    # synthesize → extract_memory → END
    builder.add_edge("synthesize", "extract_memory")
    builder.add_edge("extract_memory", END)

    return builder.compile(checkpointer=checkpointer) if checkpointer else builder.compile()
