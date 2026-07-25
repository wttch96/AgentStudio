"""中断指令队列与路由。支持按 target 精准路由到全部、单个 Agent 或主脑。"""

from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone

from app.domain.models import InterruptAction, InterruptCommand, InterruptTarget
from app.events.publisher import EventPublisher
from app.storage.sqlite_store import SQLiteStore


class InterruptRouter:
    """管理中断指令队列和执行信号。"""

    def __init__(self, store: SQLiteStore, events: EventPublisher) -> None:
        self.store = store
        self.events = events
        self._queues: dict[str, list[InterruptCommand]] = {}  # run_id -> pending
        self._agent_pause_events: dict[str, threading.Event] = {}  # "run_id:agent_id"
        self._node_pause_events: dict[str, threading.Event] = {}  # "run_id:node_id"
        self._lock = threading.Lock()

    def send(self, command: InterruptCommand) -> str:
        """发送中断指令，路由到对应目标。"""
        run_id = command.run_id
        command_id = command.id

        # 持久化到 SQLite
        self.store.insert_interrupt_command(command.model_dump())

        with self._lock:
            if run_id not in self._queues:
                self._queues[run_id] = []
            self._queues[run_id].append(command)

            if command.target == InterruptTarget.ALL:
                # 全停：标记所有活跃 agent 暂停
                pass  # 由 graph 层 interrupt() 统一处理
            elif command.target == InterruptTarget.AGENT and command.target_agent:
                key = f"{run_id}:{command.target_agent}"
                if key not in self._agent_pause_events:
                    self._agent_pause_events[key] = threading.Event()
                if command.action == InterruptAction.PAUSE:
                    self._agent_pause_events[key].set()

        self.events.emit(
            run_id,
            "interrupt.requested",
            payload={
                "command_id": command_id,
                "target": command.target.value,
                "action": command.action.value,
                "target_agent": command.target_agent,
                "target_task": command.target_task,
                "instruction": command.instruction[:200],
            },
        )
        return command_id

    def check_and_clear(self, run_id: str) -> list[dict]:
        """获取并清空待处理中断（供 graph interrupt_check 使用）。"""
        with self._lock:
            pending = self._queues.pop(run_id, [])
        return [cmd.model_dump() for cmd in pending]

    def check_agent_paused(self, run_id: str, agent_id: str) -> bool:
        """检查指定 agent 是否被要求暂停。"""
        key = f"{run_id}:{agent_id}"
        with self._lock:
            event = self._agent_pause_events.get(key)
        if event and event.is_set():
            return True
        return False

    def clear_agent_pause(self, run_id: str, agent_id: str) -> None:
        """清除 agent 暂停信号。"""
        key = f"{run_id}:{agent_id}"
        with self._lock:
            self._agent_pause_events.pop(key, None)

    # ---- Per-node pause (for flow engine) ----

    def pause_node(self, run_id: str, node_id: str) -> None:
        """Set pause signal for a specific flow node."""
        key = f"{run_id}:{node_id}"
        with self._lock:
            if key not in self._node_pause_events:
                self._node_pause_events[key] = threading.Event()
            self._node_pause_events[key].set()

    def resume_node(self, run_id: str, node_id: str) -> None:
        """Clear pause signal for a specific flow node."""
        key = f"{run_id}:{node_id}"
        with self._lock:
            self._node_pause_events.pop(key, None)

    def is_node_paused(self, run_id: str, node_id: str) -> bool:
        """Check if a flow node has been requested to pause."""
        key = f"{run_id}:{node_id}"
        with self._lock:
            event = self._node_pause_events.get(key)
        return event is not None and event.is_set()

    def wait_for_node_resume(
        self, run_id: str, node_id: str, cancel_event: threading.Event,
        poll_interval: float = 0.5,
    ) -> None:
        """Block until node is resumed or run is cancelled."""
        while not cancel_event.is_set():
            pending = self.check_and_clear(run_id)
            for cmd in pending:
                if cmd.get("action") in ("abort",):
                    cancel_event.set()
                    return
                if cmd.get("action") in ("resume",) and cmd.get("target_task") == node_id:
                    self.resume_node(run_id, node_id)
                    return
            if not self.is_node_paused(run_id, node_id):
                return
            import time
            time.sleep(poll_interval)

    def resolve(self, run_id: str, command_id: str, decision: str = "apply") -> None:
        """标记中断为已处理。"""
        self.store.resolve_interrupt(command_id, status=decision)
        self.events.emit(
            run_id,
            "interrupt.resolved",
            payload={"command_id": command_id, "decision": decision},
        )
