"""统一事件发布入口，隔离执行引擎与 SQLite 细节。"""

import logging
from typing import Any

from app.domain.models import RunEvent
from app.storage.sqlite_store import SQLiteStore

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
    def __init__(self, store: SQLiteStore) -> None:
        self.store = store

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
        saved = self.store.append_event(event)
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
