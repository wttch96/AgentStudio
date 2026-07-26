"""TodoAgent — 纯基础设施 Agent。

不调用 LLM，通过 Blackboard 维护运行级别的任务跟踪列表。
主脑规划出 DAG 后自动填充 todo，每个 Agent 完成后自动更新状态。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from app.domain.models import TodoItem
from app.services.blackboard_store import BlackboardStore


class TodoStore:
    """通过黑板管理运行级的待办任务列表。

    数据存储在 blackboard 的 ``__todos__`` 键下（JSON 序列化）。
    """

    BLACKBOARD_KEY = "__todos__"

    def __init__(self, blackboard_store: BlackboardStore) -> None:
        self._blackboard = blackboard_store

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    def init(
        self,
        run_id: str,
        items: list[dict] | None = None,
    ) -> list[TodoItem]:
        """从 DAG 任务列表初始化 todo 列表。

        Args:
            items: 任务字典列表，每个包含 id, content, assigned_to, depends_on。
        """
        todos: list[TodoItem] = []
        if items:
            now = datetime.now(timezone.utc).isoformat()
            for item in items:
                todo = TodoItem(
                    id=item.get("id", ""),
                    title=item.get("title", item.get("content", "")),
                    content=item.get("content", item.get("title", "")),
                    objective=item.get("objective", ""),
                    assigned_to=item.get("assigned_to", item.get("agent", None)),
                    depends_on=item.get("depends_on", []),
                    context=item.get("context", {}),
                    inputs=item.get("inputs", []),
                    expected_outputs=item.get("expected_outputs", []),
                    acceptance_criteria=item.get("acceptance_criteria", []),
                    status=item.get("status", "pending"),
                    created_at=now,
                    updated_at=now,
                )
                todos.append(todo)
        self._sync_to_blackboard(run_id, todos)
        return todos

    def list(self, run_id: str) -> list[TodoItem]:
        """获取当前所有 todo 项。"""
        return self._load_from_blackboard(run_id)

    def get(self, run_id: str, item_id: str) -> TodoItem | None:
        return next(
            (item for item in self._load_from_blackboard(run_id) if item.id == item_id),
            None,
        )

    def related(self, run_id: str, item_id: str) -> dict[str, list[TodoItem]]:
        todos = self._load_from_blackboard(run_id)
        current = next((item for item in todos if item.id == item_id), None)
        if current is None:
            return {"upstream": [], "downstream": []}
        return {
            "upstream": [item for item in todos if item.id in current.depends_on],
            "downstream": [item for item in todos if item_id in item.depends_on],
        }

    def update_status(
        self,
        run_id: str,
        item_id: str,
        status: str,
        agent: str = "system",
    ) -> TodoItem | None:
        """更新单个 todo 项的状态。

        Args:
            agent: 触发更新的 agent 名称（用于 blackboard 写记录）。
        """
        todos = self._load_from_blackboard(run_id)
        now = datetime.now(timezone.utc).isoformat()
        target = None
        for t in todos:
            if t.id == item_id:
                target = t
                t.status = status  # type: ignore[assignment]
                t.updated_at = now
                if status in ("completed", "failed"):
                    t.completed_at = now
                break
        if target is None:
            return None
        self._sync_to_blackboard(run_id, todos, agent)
        return target

    def apply_result(self, run_id: str, item_id: str, result: dict, agent: str) -> TodoItem | None:
        """Persist structured Agent output and move the task to review/terminal state."""
        todos = self._load_from_blackboard(run_id)
        target = next((item for item in todos if item.id == item_id), None)
        if target is None:
            return None
        target.artifacts = list(result.get("artifacts", []))
        target.decisions = list(result.get("decisions", []))
        target.risks = list(result.get("risks", []))
        target.verification = {
            "performed": result.get("verification_performed", []),
            "not_performed": result.get("verification_not_performed", []),
            "result": result.get("verification_result", "not_run"),
        }
        status = result.get("status", "failed")
        target.status = (
            "review"
            if status in ("completed", "partially_completed", "need_review")
            else status
        )
        target.updated_at = datetime.now(timezone.utc).isoformat()
        self._sync_to_blackboard(run_id, todos, agent)
        return target

    def add_dependency(self, run_id: str, item_id: str, dependency_id: str) -> TodoItem | None:
        todos = self._load_from_blackboard(run_id)
        target = next((item for item in todos if item.id == item_id), None)
        if target is None or not any(item.id == dependency_id for item in todos):
            return None
        if dependency_id not in target.depends_on:
            target.depends_on.append(dependency_id)
            target.updated_at = datetime.now(timezone.utc).isoformat()
            self._sync_to_blackboard(run_id, todos)
        return target

    def ready(self, run_id: str) -> list[TodoItem]:
        todos = self._load_from_blackboard(run_id)
        completed = {item.id for item in todos if item.status == "completed"}
        return [
            item for item in todos
            if item.status in ("backlog", "ready", "pending")
            and all(dep in completed for dep in item.depends_on)
        ]

    def workload(self, run_id: str) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in self._load_from_blackboard(run_id):
            if item.assigned_to and item.status in (
                "backlog", "ready", "pending", "in_progress", "review"
            ):
                counts[item.assigned_to] = counts.get(item.assigned_to, 0) + 1
        return counts

    def add(
        self,
        run_id: str,
        item: TodoItem | dict,
        agent: str = "system",
    ) -> TodoItem:
        """动态添加新的 todo 项；同 ID 已存在时保留运行状态并更新任务描述。"""
        todos = self._load_from_blackboard(run_id)
        todo = item if isinstance(item, TodoItem) else TodoItem.model_validate({
            **item,
            "content": item.get("content") or item.get("title") or item.get("objective") or item.get("id"),
            "assigned_to": item.get("assigned_to", item.get("agent")),
        })
        existing = next((current for current in todos if current.id == todo.id), None)
        if existing is None:
            todos.append(todo)
        else:
            existing.title = todo.title or existing.title
            existing.content = todo.content or existing.content
            existing.objective = todo.objective or existing.objective
            existing.assigned_to = todo.assigned_to or existing.assigned_to
            existing.depends_on = todo.depends_on
            existing.expected_outputs = todo.expected_outputs
            existing.acceptance_criteria = todo.acceptance_criteria
            existing.updated_at = datetime.now(timezone.utc).isoformat()
            todo = existing
        self._sync_to_blackboard(run_id, todos, agent)
        return todo

    def is_all_complete(self, run_id: str) -> bool:
        """检查所有 todo 是否都已完成。"""
        todos = self._load_from_blackboard(run_id)
        if not todos:
            return False
        return all(t.status == "completed" for t in todos)

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _load_from_blackboard(self, run_id: str) -> list[TodoItem]:
        raw = self._blackboard.read(run_id, self.BLACKBOARD_KEY)
        if raw is None:
            return []
        if isinstance(raw, list):
            return [TodoItem.model_validate(item) for item in raw]
        return []

    def _sync_to_blackboard(
        self,
        run_id: str,
        todos: list[TodoItem],
        agent: str = "system",
    ) -> None:
        data = [t.model_dump() for t in todos]
        self._blackboard.write(run_id, self.BLACKBOARD_KEY, data, agent)
