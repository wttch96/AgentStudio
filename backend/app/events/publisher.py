"""统一事件发布入口，隔离执行引擎与 SQLite 细节。"""

from typing import Any

from app.domain.models import RunEvent
from app.storage.sqlite_store import SQLiteStore


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
        return self.store.append_event(event)

