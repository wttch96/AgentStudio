"""后台运行生命周期管理。

HTTP 请求只负责创建任务；LangGraph 在守护线程中执行，避免长时间占用 Flask 请求。
"""

from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.agents.claude_executor import ClaudeAgentExecutor
from app.domain.configuration import SchedulerConfiguration
from app.domain.models import DagTask, TaskDag
from app.events.publisher import EventPublisher
from app.orchestration.graph import build_graph
from app.planning.deepseek_planner import DeepSeekPlanner
from app.services.run_commands import RunCommand, parse_run_command
from app.services.scheduler_settings import SchedulerSettings
from app.storage.sqlite_store import SQLiteStore
from app.services.workspace_settings import WorkspaceSettings
from app.services.memory_manager import MemoryManager
from app.services.interrupt_router import InterruptRouter


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
        self._cancel_events: dict[str, threading.Event] = {}
        self._agent_pause_events: dict[str, threading.Event] = {}
        self._lock = threading.Lock()

    def start(self, objective: str, parent_run_id: str | None = None,
              project_id: str | None = None) -> dict:
        command = parse_run_command(objective)
        root = self.workspace_settings.current()
        if not root.is_dir():
            raise ValueError(f"工作目录不存在：{root}")
        scheduler = self.scheduler_settings.current()
        run_id = uuid.uuid4().hex
        preset_dag = self._preset_dag(command, parent_run_id)
        flow_name = command.flow_name if command.kind == "flow" else None
        flow_inputs = command.flow_inputs if command.kind == "flow" else None
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
                "",
                preset_dag.model_dump() if preset_dag else None,
                command.kind in {"direct", "retry"},
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
            # ---- Flow engine path (deterministic YAML pipeline) ----
            if flow_name and self.flow_engine:
                flow = self.flow_engine._flow_store_loader(flow_name)
                if flow:
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

            graph = build_graph(self.planner, self.executor, self.events, cancel_event, None, interrupt_router, memory_manager, project_agents, rag_executor=self.rag_executor, chat_executor=self.chat_executor, file_agent_executor=self.file_agent_executor)
            output = graph.invoke(
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
        self, command: RunCommand, parent_run_id: str | None
    ) -> TaskDag | None:
        if command.kind in ("normal", "flow"):
            return None
        if command.kind == "direct" and command.agent:
            return TaskDag(
                summary=f"直接对话：{command.agent}",
                tasks=[
                    DagTask(
                        id=f"direct-{command.agent.removesuffix('-agent')}",
                        title=f"直接交给 {command.agent}",
                        objective=command.instruction,
                        agent=command.agent,
                        write_scope=["."],
                    )
                ],
            )

        if not parent_run_id or not command.task_id:
            raise ValueError("/retry 必须在选中的上游任务中使用")
        events = self.store.list_events(parent_run_id)
        plan_event = next(
            (event for event in reversed(events) if event["type"] == "plan.created"),
            None,
        )
        tasks = plan_event["payload"].get("tasks", []) if plan_event else []
        source = next((item for item in tasks if item.get("id") == command.task_id), None)
        failure = next(
            (
                event
                for event in reversed(events)
                if event.get("task_id") == command.task_id
                and event["type"] == "agent.failed"
            ),
            None,
        )
        if not source:
            raise ValueError(f"上游任务中不存在子任务：{command.task_id}")
        if not failure:
            raise ValueError(f"子任务 {command.task_id} 没有失败记录，无需重试")
        error = str(
            failure["payload"].get("error")
            or failure["payload"].get("summary")
            or "未知失败"
        )[:1200]
        objective = (
            f"重新执行失败子任务 {command.task_id}。\n"
            f"原任务目标：{source.get('objective', source.get('title', ''))}\n"
            f"上次失败原因：{error}\n"
            "请检查当前工作区已有进度，避免重复或覆盖已完成的正确修改，并完成验证。"
        )[:4000]
        return TaskDag(
            summary=f"重试失败节点 {command.task_id}",
            tasks=[
                DagTask(
                    id=f"retry-{command.task_id}",
                    title=f"重试：{source.get('title', command.task_id)}",
                    objective=objective,
                    agent=source["agent"],
                    write_scope=source.get("write_scope", []),
                )
            ],
        )
