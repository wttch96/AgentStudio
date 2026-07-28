"""Pure operations over Todo items embedded in LangGraph State."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, MutableMapping

from app.domain.models import TodoItem


class TodoStateOps:
    """Mutate ``state['todos']`` without a separate store or hidden blackboard key."""

    def __init__(self, state: MutableMapping[str, Any]) -> None:
        self.state = state
        self.state.setdefault("todos", {})

    def _items(self) -> dict[str, TodoItem]:
        return {
            item_id: raw if isinstance(raw, TodoItem) else TodoItem.model_validate(raw)
            for item_id, raw in self.state["todos"].items()
        }

    def _save(self, items: dict[str, TodoItem]) -> None:
        self.state["todos"] = {key: item.model_dump() for key, item in items.items()}

    def init(self, items: list[dict] | None = None) -> list[TodoItem]:
        todos: dict[str, TodoItem] = {}
        for raw in items or []:
            item = TodoItem.model_validate({
                **raw,
                "content": raw.get("content") or raw.get("title") or raw.get("objective") or raw.get("id"),
                "assigned_to": raw.get("assigned_to", raw.get("agent")),
            })
            todos[item.id] = item
        self._save(todos)
        return list(todos.values())

    def list(self) -> list[TodoItem]:
        return list(self._items().values())

    def get(self, item_id: str) -> TodoItem | None:
        return self._items().get(item_id)

    def related(self, item_id: str) -> dict[str, list[TodoItem]]:
        items = self._items()
        current = items.get(item_id)
        if current is None:
            return {"upstream": [], "downstream": []}
        return {
            "upstream": [item for key, item in items.items() if key in current.depends_on],
            "downstream": [item for item in items.values() if item_id in item.depends_on],
        }

    def update_status(self, item_id: str, status: str, agent: str = "system") -> TodoItem | None:
        items = self._items()
        item = items.get(item_id)
        if item is None:
            return None
        now = datetime.now(timezone.utc).isoformat()
        item.status = status  # type: ignore[assignment]
        item.updated_at = now
        if status in {"completed", "failed", "cancelled"}:
            item.completed_at = now
        self._save(items)
        return item

    def apply_result(self, item_id: str, result: dict, agent: str) -> TodoItem | None:
        items = self._items()
        item = items.get(item_id)
        if item is None:
            return None
        item.artifacts = list(result.get("artifacts", []))
        item.decisions = list(result.get("decisions", []))
        item.risks = list(result.get("risks", []))
        item.verification = {
            "performed": result.get("verification_performed", []),
            "not_performed": result.get("verification_not_performed", []),
            "result": result.get("verification_result", "not_run"),
        }
        status = result.get("status", "failed")
        item.status = "review" if status in {"completed", "partially_completed", "need_review"} else status
        item.updated_at = datetime.now(timezone.utc).isoformat()
        self._save(items)
        return item

    def add_dependency(self, item_id: str, dependency_id: str) -> TodoItem | None:
        items = self._items()
        item = items.get(item_id)
        if item is None or dependency_id not in items:
            return None
        if dependency_id not in item.depends_on:
            item.depends_on.append(dependency_id)
            item.updated_at = datetime.now(timezone.utc).isoformat()
            self._save(items)
        return item

    def ready(self) -> list[TodoItem]:
        items = self._items()
        completed = {key for key, item in items.items() if item.status == "completed"}
        return [
            item for item in items.values()
            if item.status in {"backlog", "ready", "pending"}
            and all(dependency in completed for dependency in item.depends_on)
        ]

    def workload(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in self._items().values():
            if item.assigned_to and item.status in {"backlog", "ready", "pending", "in_progress", "review"}:
                counts[item.assigned_to] = counts.get(item.assigned_to, 0) + 1
        return counts

    def add(self, raw: TodoItem | dict, agent: str = "system") -> TodoItem:
        items = self._items()
        item = raw if isinstance(raw, TodoItem) else TodoItem.model_validate({
            **raw,
            "content": raw.get("content") or raw.get("title") or raw.get("objective") or raw.get("id"),
            "assigned_to": raw.get("assigned_to", raw.get("agent")),
        })
        existing = items.get(item.id)
        if existing:
            item = item.model_copy(update={
                "status": existing.status,
                "created_at": existing.created_at,
                "completed_at": existing.completed_at,
            })
        items[item.id] = item
        self._save(items)
        return item

    def all_done(self) -> bool:
        items = self.list()
        return bool(items) and all(item.status == "completed" for item in items)


TodoOps = TodoStateOps
