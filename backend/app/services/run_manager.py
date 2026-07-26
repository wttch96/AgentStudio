"""后台运行生命周期管理。

HTTP 请求只负责创建任务；LangGraph 在守护线程中执行，避免长时间占用 Flask 请求。
"""

from __future__ import annotations

import asyncio
import threading
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.agents.claude_executor import ClaudeAgentExecutor
from app.domain.configuration import SchedulerConfiguration
from app.domain.models import DagTask, TaskDag
from app.events.publisher import EventPublisher
from app.orchestration.graph import build_graph
from app.planning.deepseek_planner import DeepSeekPlanner
from app.services.interrupt_router import InterruptRouter
from app.services.memory_manager import MemoryManager
from app.services.run_commands import RunCommand, parse_run_command
from app.services.scheduler_settings import SchedulerSettings
from app.services.workspace_settings import WorkspaceSettings
from app.storage.sqlite_store import SQLiteStore


async def _ainvoke_graph(
    graph_factory: Callable[[Any], Any],
    checkpoint_path: Path | None,
    state: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    """在单一事件循环内创建异步 checkpointer、执行图并关闭连接。"""
    if checkpoint_path is None:
        return await graph_factory(None).ainvoke(state, config)

    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    async with AsyncSqliteSaver.from_conn_string(str(checkpoint_path)) as checkpointer:
        graph = graph_factory(checkpointer)
        return await graph.ainvoke(state, config)


class RunManager:
    def __init__(
        self,
        store: SQLiteStore,
        events: EventPublisher,
        planner: DeepSeekPlanner,
        executor: ClaudeAgentExecutor,
        workspace_settings: WorkspaceSettings,
        scheduler_settings: SchedulerSettings,
        memory_manager: MemoryManager | None = None,
        interrupt_router: InterruptRouter | None = None,
        rag_executor=None,
        chat_executor=None,
        file_agent_executor=None,
        flow_engine: Any = None,
        blackboard_store: Any = None,
        todo_store: Any = None,
        yaml_compiler: Any = None,
        flow_store: Any = None,
        reviewer: Any = None,
        agent_context_builder: Any = None,
        conflict_detector: Any = None,
        agent_selector: Any = None,
        settings: Any = None,
    ) -> None:
        self.store = store
        self.events = events
        self.planner = planner
        self.executor = executor
        self.workspace_settings = workspace_settings
        self.scheduler_settings = scheduler_settings
        self.memory_manager = memory_manager
        self.interrupt_router = interrupt_router
        self.rag_executor = rag_executor
        self.chat_executor = chat_executor
        self.file_agent_executor = file_agent_executor
        self.flow_engine = flow_engine
        self.blackboard_store = blackboard_store
        self.todo_store = todo_store
        self.yaml_compiler = yaml_compiler
        self.flow_store = flow_store
        self.reviewer = reviewer
        self.agent_context_builder = agent_context_builder
        self.conflict_detector = conflict_detector
        self.agent_selector = agent_selector
        self._settings = settings
        self._cancel_events: dict[str, threading.Event] = {}
        self._agent_pause_events: dict[str, threading.Event] = {}
        self._lock = threading.Lock()

    def start(self, objective: str, parent_run_id: str | None = None,
              project_id: str | None = None, flow_name: str | None = None,
              flow_inputs: dict | None = None) -> dict:
        command = parse_run_command(objective)
        parent = self.store.get_run(parent_run_id) if parent_run_id else None
        if parent_run_id and not parent:
            raise ValueError("上游任务不存在")
        if parent and parent["status"] not in {"completed", "failed", "cancelled"}:
            raise RuntimeError("上游任务仍在执行，请等待结束后再继续")
        root = (
            Path(parent["workspace_root"])
            if parent and parent.get("workspace_root")
            else self.workspace_settings.current(project_id or "")
        )
        if not root.is_dir():
            raise ValueError(f"工作目录不存在：{root}")
        scheduler = self.scheduler_settings.current(project_id or "")
        run_id = uuid.uuid4().hex
        continuation_context = self._continuation_context(parent_run_id)
        preset_dag = self._preset_dag(command, parent_run_id, project_id or "")
        run = self.store.create_run(run_id, objective, str(root), parent_run_id, project_id)
        cancel_event = threading.Event()
        with self._lock:
            self._cancel_events[run_id] = cancel_event

        thread = threading.Thread(
            target=self._execute,
            args=(
                run_id,
                objective,
                root,
                scheduler,
                cancel_event,
                continuation_context,
                preset_dag.model_dump() if preset_dag else None,
                command.kind == "direct",
                self.interrupt_router,
                self.memory_manager,
                self.store.get_run(run_id).get("conversation_id", run_id),
                project_id,
                flow_name,
                flow_inputs,
            ),
            name=f"run-{run_id[:8]}",
            daemon=True,
        )
        thread.start()
        return run

    def _continuation_context(self, parent_run_id: str | None) -> str:
        """把最近上游输出压缩为有界上下文，供规划器和执行 Agent 使用。"""
        if not parent_run_id:
            return ""
        sections: list[str] = []
        for run in self.store.run_ancestry(parent_run_id):
            agent_summaries: list[str] = []
            for event in self.store.list_events(run["id"]):
                if event["type"] not in {"agent.completed", "agent.failed"}:
                    continue
                payload = event["payload"]
                summary = str(payload.get("summary") or payload.get("error") or "")[:1600]
                if summary:
                    agent_summaries.append(
                        f"- {event.get('agent_id') or 'agent'}: {summary}"
                    )
            answer = str(run.get("final_answer") or run.get("error") or "无最终输出")[:6000]
            sections.append("\n".join([
                f"第 {run.get('turn_index', 1)} 轮用户目标：{run['objective']}",
                f"状态：{run['status']}",
                "Agent 结果：",
                *(agent_summaries[-6:] or ["- 无"]),
                f"最终输出：\n{answer}",
            ]))
        return "\n\n--- 上游轮次 ---\n\n".join(sections)[-24_000:]

    def fork(self, source_run_id: str, objective_override: str | None = None,
             project_id: str | None = None) -> dict:
        """从已完成任务中分叉，创建新的对话分支并携带记忆上下文。"""
        source = self.store.get_run(source_run_id)
        if not source:
            raise ValueError("源任务不存在")
        if source.get("status") not in ("completed", "failed", "cancelled"):
            raise RuntimeError("源任务尚未结束，请等待完成后再分叉")

        import uuid
        new_run_id = uuid.uuid4().hex
        objective = (objective_override or source.get("objective", "")).strip()
        root = str(self.workspace_settings.current())

        # 通过 store 创建新 run（新 conversation_id）+ 检索记忆
        run = self.store.fork_run(source_run_id, new_run_id, objective, root)
        memory_context = run.pop("_memory_context", "")

        scheduler = self.scheduler_settings.current()
        cancel_event = threading.Event()
        with self._lock:
            self._cancel_events[new_run_id] = cancel_event

        thread = threading.Thread(
            target=self._execute,
            args=(
                new_run_id, objective, self.workspace_settings.current(),
                scheduler, cancel_event,
                memory_context,  # guidance = 继承的记忆上下文
                None,  # preset_dag
                False,  # direct_mode
                self.interrupt_router,
                self.memory_manager,
                new_run_id,  # conversation_id = 新分支
                project_id,
            ),
            name=f"run-{new_run_id[:8]}",
            daemon=True,
        )
        thread.start()
        return run

    def cancel(self, run_id: str) -> bool:
        run = self.store.get_run(run_id)
        if not run or run["status"] in {"completed", "failed", "cancelled"}:
            return False
        with self._lock:
            cancel_event = self._cancel_events.get(run_id)
        if cancel_event:
            cancel_event.set()
            self.events.emit(run_id, "run.cancel_requested", payload={})
            return True

        # 数据库显示活动但当前进程没有执行线程，说明它是重启遗留的孤儿记录。
        self.store.update_run(
            run_id,
            "cancelled",
            error="运行线程不存在，已清理遗留状态",
        )
        self.events.emit(
            run_id,
            "run.cancelled",
            payload={"text": "遗留运行已停止，现在可以删除。", "orphaned": True},
        )
        return True

    def is_active(self, run_id: str) -> bool:
        """判断运行是否确实由当前进程中的后台线程持有。"""

        with self._lock:
            return run_id in self._cancel_events

    def _execute(
        self,
        run_id: str,
        objective: str,
        workspace_root: Path,
        scheduler: SchedulerConfiguration,
        cancel_event: threading.Event,
        guidance: str,
        preset_dag: dict | None,
        direct_mode: bool,
        interrupt_router: InterruptRouter | None = None,
        memory_manager: MemoryManager | None = None,
        conversation_id: str = "",
        project_id: str | None = None,
        flow_name: str | None = None,
        flow_inputs: dict | None = None,
    ) -> None:
        started_at_iso = datetime.now(timezone.utc).isoformat()
        self.store.update_run(run_id, "running", started_at=started_at_iso)
        try:
            self.events.emit(
                run_id,
                "run.started",
                payload={
                    "objective": objective,
                    "workspace_root": str(workspace_root),
                    "scheduler": scheduler.model_dump(),
                    "parent_run_id": self.store.get_run(run_id).get("parent_run_id"),
                },
            )
            if not flow_name and preset_dag is None and self.flow_store is not None:
                try:
                    flow_name = self.planner.classify_intent(
                        objective, self.flow_store.list_all()
                    )
                    if flow_name:
                        flow_inputs = {"prompt": objective}
                        self.events.emit(
                            run_id, "planner.flow_selected",
                            payload={"flow_name": flow_name, "inputs": flow_inputs},
                        )
                except Exception:
                    flow_name = None
            # ---- Flow engine path (deterministic YAML pipeline) ----
            if flow_name and self.flow_engine:
                flow = self.flow_engine._flow_store_loader(flow_name)
                if flow:
                    if flow.is_extended and self.yaml_compiler is not None:
                        self.events.emit(
                            run_id,
                            "plan.created",
                            payload={
                                "flow_name": flow.name,
                                "flow_version": flow.version,
                                "stage": "execution",
                                "tasks": [
                                    {
                                        "id": node.id,
                                        "title": node.title,
                                        "objective": node.objective,
                                        "agent": node.agent,
                                        "depends_on": node.depends_on,
                                        "write_scope": node.write_scope,
                                    }
                                    for node in flow.nodes
                                ],
                                "summary": flow.description,
                                "coordination_contract": (
                                    f"流程 {flow.name} v{flow.version}: {flow.description}"
                                ),
                            },
                        )
                        self.events.emit(
                            run_id,
                            "flow.started",
                            payload={
                                "flow_name": flow.name,
                                "flow_version": flow.version,
                                "node_count": len(flow.nodes),
                                "extended": True,
                            },
                        )
                        if self.blackboard_store is not None:
                            self.blackboard_store.init(run_id)
                        if self.todo_store is not None:
                            self.todo_store.init(run_id, [
                                {
                                    **node.model_dump(),
                                    "content": node.title,
                                    "assigned_to": node.agent,
                                }
                                for node in flow.nodes
                            ])
                        compiled = self.yaml_compiler.compile(flow)
                        output = compiled.invoke(
                            {
                                "run_id": run_id,
                                "flow_name": flow.name,
                                "workspace_root": str(workspace_root),
                                "project_id": project_id or "",
                                "inputs": flow_inputs or {},
                                "blackboard": {},
                                "loop_counters": {},
                            },
                            config={
                                "recursion_limit": max(
                                    25,
                                    scheduler.recursion_limit,
                                ),
                            },
                        )
                    else:
                        output = self.flow_engine.execute(
                            flow=flow,
                            inputs=flow_inputs or {},
                            run_id=run_id,
                            workspace_root=str(workspace_root),
                            cancel_event=cancel_event,
                            interrupt_router=interrupt_router,
                            scheduler=scheduler,
                            project_id=project_id or "",
                        )
                    final_answer = output.get("final_answer", "")
                    status = "cancelled" if cancel_event.is_set() else "completed"
                    # Long-term memory
                    if memory_manager and conversation_id:
                        try:
                            memory_manager.extract_long_term_memory(
                                conversation_id, run_id,
                                session_summary=str(final_answer)[:4000],
                                agent_results=output.get("results", [])[-20:],
                            )
                            memory_manager.summarize_thread(
                                conversation_id,
                                [
                                    {"role": "user", "content": objective},
                                    {"role": "assistant", "content": final_answer},
                                ],
                            )
                        except Exception:
                            pass
                    self.store.update_run(run_id, status, final_answer=final_answer)
                    self.events.emit(run_id, f"run.{status}", payload={"text": final_answer})
                    return

            # ---- Existing LangGraph path ----
            # Load project agents from file-based config
            project_agents = []
            try:
                if project_id:
                    agent_profiles = self.executor.registry.load_project_agents(project_id)
                    project_agents = list(agent_profiles.values())
                else:
                    # 从文件加载所有 Agent（排除 brain 类型）
                    agent_profiles = self.executor.registry.load_project_agents("")
                    project_agents = [
                        p for p in agent_profiles.values()
                        if p.agent_type not in ('brain',)
                    ]
            except Exception:
                pass

            def graph_factory(checkpointer: Any):
                return build_graph(
                    self.planner, self.executor, self.events, cancel_event,
                    checkpointer, interrupt_router, memory_manager, project_agents,
                    rag_executor=self.rag_executor,
                    chat_executor=self.chat_executor,
                    file_agent_executor=self.file_agent_executor,
                    blackboard_store=self.blackboard_store,
                    todo_store=self.todo_store,
                    yaml_compiler=self.yaml_compiler,
                    flow_store=self.flow_store,
                    reviewer=self.reviewer,
                    agent_selector=self.agent_selector,
                    conflict_detector=self.conflict_detector,
                    context_builder=self.agent_context_builder,
                    max_graph_iterations=getattr(
                        self._settings, "max_graph_iterations", 20
                    ) if self._settings else 20,
                    max_replan_iterations=getattr(
                        self._settings, "max_replan_iterations", 3
                    ) if self._settings else 3,
                    max_task_revisions=getattr(
                        self._settings, "max_task_revisions", 2
                    ) if self._settings else 2,
                )

            checkpoint_path = (
                self._settings.data_dir / "checkpoints.db"
                if self._settings is not None
                else None
            )
            output = asyncio.run(
                _ainvoke_graph(
                    graph_factory,
                    checkpoint_path,
                    {
                        "run_id": run_id,
                        "objective": objective,
                        "guidance": guidance,
                        "preset_dag": preset_dag,
                        "direct_mode": direct_mode,
                        "workspace_root": str(workspace_root),
                        "agent_max_turns": scheduler.agent_max_turns,
                        "agent_timeout_seconds": scheduler.agent_timeout_seconds,
                        "project_id": project_id or "",
                        "results": [],
                    },
                    {
                        "configurable": {"thread_id": run_id},
                        "max_concurrency": scheduler.max_concurrent_agents,
                        "recursion_limit": scheduler.recursion_limit,
                    },
                )
            )
            final_answer = output.get("final_answer", "")
            status = "cancelled" if cancel_event.is_set() else "completed"
            # 长期记忆：运行结束后用 LangMem 提取跨会话记忆
            if memory_manager and conversation_id:
                try:
                    session_summary = output.get("session_summary", final_answer)
                    results_raw = output.get("results", [])
                    memory_manager.extract_long_term_memory(
                        conversation_id, run_id,
                        session_summary=str(session_summary)[:4000],
                        agent_results=list(results_raw)[-20:] if results_raw else None,
                    )
                    memory_manager.summarize_thread(
                        conversation_id,
                        [
                            {"role": "user", "content": objective},
                            {"role": "assistant", "content": final_answer},
                        ],
                    )
                except Exception:
                    pass  # 长期记忆提取失败不影响主流程
            self.store.update_run(run_id, status, final_answer=final_answer)
            self.events.emit(run_id, f"run.{status}", payload={"text": final_answer})
        except Exception as error:
            import traceback
            error_detail = f"{type(error).__name__}: {str(error) or repr(error)}"
            traceback.print_exc()
            self.store.update_run(run_id, "failed", error=error_detail)
            self.events.emit(
                run_id,
                "run.failed",
                payload={
                    "error": error_detail,
                    "error_type": type(error).__name__,
                },
            )
        finally:
            with self._lock:
                self._cancel_events.pop(run_id, None)

    def _preset_dag(
        self, command: RunCommand, parent_run_id: str | None, project_id: str = ""
    ) -> TaskDag | None:
        if command.kind == "normal":
            return None
        if command.kind == "direct" and command.agent:
            self.executor.registry.get(project_id, command.agent)
            return TaskDag(
                summary=f"直接对话：{command.agent}",
                tasks=[
                    DagTask(
                        id=f"direct-{command.agent.removesuffix('-agent')}",
                        title=f"直接交给 {command.agent}",
                        objective=command.instruction,
                        agent=command.agent,
                        write_scope=["."],
                        expected_outputs=["Agent 的实际执行结果"],
                        acceptance_criteria=["完成用户指令并说明验证结果"],
                        forbidden_actions=["不得写出所选工作空间"],
                        status="ready",
                    )
                ],
            )

        return None
