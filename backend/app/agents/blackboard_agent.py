"""BlackboardAgent — 非 LLM 执行器。

当 planner 将任务分配给 "blackboard" agent 时，此 executor 解析任务 objective
中的黑板书/读指令并执行。不调用任何 LLM。
"""

from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timezone

from app.domain.models import AgentResult, DagTask
from app.services.blackboard_state import BlackboardStateOps


class BlackboardAgentExecutor:
    """非 LLM 执行器：解析黑板书/读/删除指令。"""

    # 匹配 {{blackboard.set('key', value)}} 或 {{blackboard.set("key", value)}}
    _SET_PATTERN = re.compile(
        r"\{\{\s*blackboard\.set\s*\(\s*['\"](\w+)['\"]\s*,\s*(.+?)\s*\)\s*\}\}"
    )
    # 匹配 {{blackboard.delete('key')}}
    _DELETE_PATTERN = re.compile(
        r"\{\{\s*blackboard\.delete\s*\(\s*['\"](\w+)['\"]\s*\)\s*\}\}"
    )

    def __init__(self, blackboard: BlackboardStateOps) -> None:
        self._blackboard = blackboard

    def execute(
        self,
        run_id: str,
        task: DagTask,
        dependency_results: list[AgentResult],
        cancel_event: threading.Event,
        workspace_root: str,
        max_turns: int | None = None,
        timeout_seconds: int | None = None,
        project_id: str | None = None,
    ) -> AgentResult:
        """解析 task.objective 中的黑板书/读指令并执行。"""
        started_at = datetime.now(timezone.utc).isoformat()
        objective = task.objective
        messages: list[str] = []
        updates: dict[str, str] = {}

        # 1. 解析 set 指令
        for m in self._SET_PATTERN.finditer(objective):
            key = m.group(1)
            raw_value = m.group(2).strip()
            try:
                value = json.loads(raw_value)
            except (json.JSONDecodeError, ValueError):
                value = raw_value.strip("'\"")
            self._blackboard.write(key, value, task.agent)
            updates[key] = str(value)[:200]
            messages.append(f"blackboard.{key} = {value}")

        # 2. 解析 delete 指令
        for m in self._DELETE_PATTERN.finditer(objective):
            key = m.group(1)
            self._blackboard.write(key, None, task.agent)
            messages.append(f"blackboard.{key} deleted")

        summary = "; ".join(messages) if messages else "黑板操作完成"
        return AgentResult(
            task_id=task.id,
            agent=task.agent,
            status="completed",
            summary=summary,
            started_at=started_at,
            duration_ms=0,
        )
