"""后台运行生命周期管理。

HTTP 请求只负责创建任务；LangGraph 在守护线程中执行，避免长时间占用 Flask 请求。
"""

from __future__ import annotations

import threading
import uuid
from pathlib import Path

from app.agents.claude_executor import ClaudeAgentExecutor
from app.domain.configuration import SchedulerConfiguration
from app.domain.models import DagTask, TaskDag
from app.events.publisher import EventPublisher
from app.orchestration.graph import build_graph
from app.planning.deepseek_planner import DeepSeekPlanner
from app.services.run_commands import AGENT_SCOPES, RunCommand, parse_run_command
from app.services.scheduler_settings import SchedulerSettings
from app.storage.sqlite_store import SQLiteStore
from app.services.workspace_settings import WorkspaceSettings


class RunManager:
    def __init__(
        self,
        store: SQLiteStore,
        events: EventPublisher,
        planner: DeepSeekPlanner,
        executor: ClaudeAgentExecutor,
        workspace_settings: WorkspaceSettings,
        scheduler_settings: SchedulerSettings,
    ) -> None:
        self.store = store
        self.events = events
        self.planner = planner
        self.executor = executor
        self.workspace_settings = workspace_settings
        self.scheduler_settings = scheduler_settings
        self._cancel_events: dict[str, threading.Event] = {}
        self._lock = threading.Lock()

    def start(self, objective: str, parent_run_id: str | None = None) -> dict:
        command = parse_run_command(objective)
        parent = self.store.get_run(parent_run_id) if parent_run_id else None
        if parent_run_id and not parent:
            raise ValueError("上游任务不存在")
        if parent and parent["status"] not in {"completed", "failed", "cancelled"}:
            raise RuntimeError("上游任务仍在执行，请等待结束后再继续")

        # 继续任务必须沿用上游工作目录，避免一次对话意外切到另一个项目。
        root = (
            Path(parent["workspace_root"])
            if parent and parent.get("workspace_root")
            else self.workspace_settings.current()
        )
        if not root.is_dir():
            raise ValueError(f"上游工作目录不存在：{root}")
        scheduler = self.scheduler_settings.current()
        run_id = uuid.uuid4().hex
        continuation_context = self._continuation_context(parent_run_id)
        preset_dag = self._preset_dag(command, parent_run_id)
        run = self.store.create_run(run_id, objective, str(root), parent_run_id)
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
                command.kind in {"direct", "retry"},
            ),
            name=f"run-{run_id[:8]}",
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
        continuation_context: str,
        preset_dag: dict | None,
        direct_mode: bool,
    ) -> None:
        self.store.update_run(run_id, "running")
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
        try:
            graph = build_graph(self.planner, self.executor, self.events, cancel_event)
            output = graph.invoke(
                {
                    "run_id": run_id,
                    "objective": objective,
                    "continuation_context": continuation_context,
                    "preset_dag": preset_dag,
                    "direct_mode": direct_mode,
                    "workspace_root": str(workspace_root),
                    "agent_max_turns": scheduler.agent_max_turns,
                    "agent_timeout_seconds": scheduler.agent_timeout_seconds,
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
            self.store.update_run(run_id, status, final_answer=final_answer)
            self.events.emit(run_id, f"run.{status}", payload={"text": final_answer})
        except Exception as error:
            error_detail = f"{type(error).__name__}: {str(error) or repr(error)}"
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
        if command.kind == "normal":
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
                        write_scope=AGENT_SCOPES[command.agent],
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

    def _continuation_context(self, parent_run_id: str | None) -> str:
        """把最近上游输出压缩成有界文本，供 DeepSeek 继续规划。"""

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
            sections.append(
                "\n".join(
                    [
                        f"第 {run.get('turn_index', 1)} 轮用户目标：{run['objective']}",
                        f"状态：{run['status']}",
                        "Agent 结果：",
                        *(agent_summaries[-6:] or ["- 无"]),
                        f"最终输出：\n{answer}",
                    ]
                )
            )
        # 优先保留最新轮次，限制上下文避免历史对话无限膨胀。
        return "\n\n--- 上游轮次 ---\n\n".join(sections)[-24_000:]
