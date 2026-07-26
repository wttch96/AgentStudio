"""黑板共享状态存储。

提供 per-run 的键值存储，支持 CAS（比较并交换）版本语义。
同一次运行的 Agent 通过黑板共享信息，支持条件分支和循环决策。
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from typing import Any

from app.domain.models import BlackboardEntry, BlackboardState
from app.storage.sqlite_store import SQLiteStore


class BlackboardStore:
    """Per-run 黑板键值存储。

    所有写入落 SQLite，读取优先走内存快照（零延迟）。
    同一 run 内的 Agent 共享相同的 BlackboardStore 实例。
    """

    def __init__(self, store: SQLiteStore) -> None:
        self._store: SQLiteStore = store
        self._lock: threading.RLock = threading.RLock()
        self._snapshots: dict[str, BlackboardState] = {}

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    def init(self, run_id: str) -> BlackboardState:
        """初始化运行的黑板快照（内存 + DB 种子）。"""
        with self._lock:
            state = BlackboardState(run_id=run_id)
            self._snapshots[run_id] = state
            return state

    def destroy(self, run_id: str) -> None:
        """清理运行的黑板数据。"""
        with self._lock:
            self._snapshots.pop(run_id, None)
            with self._store._connect() as conn:
                conn.execute("DELETE FROM blackboard WHERE run_id = ?", (run_id,))

    # ------------------------------------------------------------------
    # 读取
    # ------------------------------------------------------------------

    def read(self, run_id: str, key: str) -> Any | None:
        """读取单个 key 的值。先从快照读，再从 DB 读。"""
        state = self._snapshots.get(run_id)
        if state and key in state.entries:
            return state.entries[key].value

        row = self._load_row(run_id, key)
        if row is None:
            return None
        return json.loads(row["value"])

    def read_all(self, run_id: str) -> dict[str, Any]:
        """读取所有键值对（用于模板渲染和 Agent 上下文）。"""
        snapshot = self.snapshot(run_id)
        return {k: v.value for k, v in snapshot.entries.items()}

    def snapshot(self, run_id: str) -> BlackboardState:
        """获取完整快照，优先内存。"""
        with self._lock:
            cached = self._snapshots.get(run_id)
            if cached is not None:
                return cached

            state = BlackboardState(run_id=run_id)
            rows = self._load_all_rows(run_id)
            for row in rows:
                entry = BlackboardEntry(
                    key=row["key"],
                    value=json.loads(row["value"]),
                    updated_by=row["updated_by"],
                    updated_at=row["updated_at"],
                    version=row["version"],
                )
                state.entries[entry.key] = entry
                state.revision = max(state.revision, entry.version)
            self._snapshots[run_id] = state
            return state

    # ------------------------------------------------------------------
    # 写入
    # ------------------------------------------------------------------

    def write(
        self,
        run_id: str,
        key: str,
        value: Any,
        agent: str,
        expected_version: int | None = None,
    ) -> BlackboardEntry:
        """写入单个键值对。

        Args:
            expected_version: 期望的当前版本号。None 时无条件写入。
                             若当前版本不等于 expected_version，抛出 ValueError。

        Returns:
            新写入的 BlackboardEntry。
        """
        with self._lock:
            state = self._snapshots.get(run_id)
            if state is None:
                state = self.snapshot(run_id)

            existing = state.entries.get(key)

            if expected_version is not None:
                current_ver = existing.version if existing else 0
                if current_ver != expected_version:
                    raise ValueError(
                        f"CAS 冲突：key={key} expected_version={expected_version} "
                        f"actual_version={current_ver}"
                    )

            new_version = (existing.version + 1) if existing else 1
            now = datetime.now(timezone.utc).isoformat()
            entry = BlackboardEntry(
                key=key,
                value=value,
                updated_by=agent,
                updated_at=now,
                version=new_version,
            )
            state.entries[key] = entry
            state.revision += 1

            # 持久化到 DB
            self._save_row(run_id, key, json.dumps(value, ensure_ascii=False), agent, now, new_version)
            return entry

    def write_batch(self, run_id: str, updates: dict[str, Any], agent: str) -> None:
        """批量写入（同一 agent 一次写入多个 key）。"""
        for key, value in updates.items():
            self.write(run_id, key, value, agent)

    # ------------------------------------------------------------------
    # 内部辅助
    # ------------------------------------------------------------------

    def _load_row(self, run_id: str, key: str) -> dict | None:
        with self._store._connect() as conn:
            row = conn.execute(
                "SELECT * FROM blackboard WHERE run_id = ? AND key = ?",
                (run_id, key),
            ).fetchone()
            return dict(row) if row else None

    def _load_all_rows(self, run_id: str) -> list[dict]:
        with self._store._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM blackboard WHERE run_id = ?", (run_id,)
            ).fetchall()
            return [dict(r) for r in rows]

    def _save_row(
        self,
        run_id: str,
        key: str,
        value_json: str,
        agent: str,
        updated_at: str,
        version: int,
    ) -> None:
        with self._store._connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO blackboard
                   (run_id, key, value, updated_by, updated_at, version)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (run_id, key, value_json, agent, updated_at, version),
            )
