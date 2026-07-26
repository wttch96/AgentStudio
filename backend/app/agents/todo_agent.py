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
                    content=item.get("content", item.get("title", "")),
                    assigned_to=item.get("assigned_to", item.get("agent", None)),
                    depends_on=item.get("depends_on", []),
                    created_at=now,
                )
                todos.append(todo)
        self._sync_to_blackboard(run_id, todos)
        return todos

    def list(self, run_id: str) -> list[TodoItem]:
        """获取当前所有 todo 项。"""
        return self._load_from_blackboard(run_id)

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
                if status in ("completed", "failed"):
                    t.completed_at = now
                break
        if target is None:
            return None
        self._sync_to_blackboard(run_id, todos, agent)
        return target

    def add(self, run_id: str, item: TodoItem, agent: str = "system") -> TodoItem:
        """动态添加新的 todo 项。"""
        todos = self._load_from_blackboard(run_id)
        todos.append(item)
        self._sync_to_blackboard(run_id, todos, agent)
        return item

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
