"""统一事件发布入口，隔离执行引擎与 SQLite 细节。"""

import logging
from typing import Any

from app.domain.models import RunEvent
from app.storage.runtime_files import RuntimeFiles

logger = logging.getLogger(__name__)

IMPORTANT_EVENTS = {
    "run.started",
    "run.completed",
    "run.cancelled",
    "run.failed",
    "plan.created",
    "flow.started",
    "agent.started",
    "agent.completed",
    "agent.failed",
    "agent.retrying",
}


class EventPublisher:
    def __init__(self, runtime_dir) -> None:
        self.files = RuntimeFiles(runtime_dir)

    def emit(
        self,
        run_id: str,
        event_type: str,
        *,
        agent_id: str | None = None,
        task_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> RunEvent:
        event = RunEvent(
            run_id=run_id,
            type=event_type,
            agent_id=agent_id,
            task_id=task_id,
            payload=payload or {},
        )
        event.sequence = self.files.append_next_event(run_id, {
            "run_id": event.run_id, "sequence": event.sequence, "type": event.type,
            "timestamp": event.timestamp, "agent_id": event.agent_id,
            "task_id": event.task_id, "payload": event.payload,
        })
        saved = event
        log = logger.info if event_type in IMPORTANT_EVENTS else logger.debug
        log(
            "event.emitted run_id=%s sequence=%s type=%s agent_id=%s task_id=%s payload_keys=%s",
            run_id,
            saved.sequence,
            event_type,
            agent_id or "-",
            task_id or "-",
            ",".join(sorted(event.payload)) or "-",
        )
        return saved

    def list_events(self, run_id: str, after: int = 0) -> list[dict[str, Any]]:
        return [event for event in self.files.list_events(run_id) if event["sequence"] > after]
