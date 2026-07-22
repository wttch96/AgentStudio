"""轻量本地持久化。

每次操作创建短连接，配合 WAL 模式支持 Flask 请求线程、后台图线程和 SSE 线程并发访问。
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from app.domain.models import RunEvent


TERMINAL_STATUSES = {"completed", "failed", "cancelled"}


class SQLiteStore:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY,
                    objective TEXT NOT NULL,
                    workspace_root TEXT,
                    parent_run_id TEXT,
                    conversation_id TEXT,
                    turn_index INTEGER NOT NULL DEFAULT 1,
                    status TEXT NOT NULL,
                    final_answer TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
                    sequence INTEGER NOT NULL,
                    type TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    agent_id TEXT,
                    task_id TEXT,
                    payload TEXT NOT NULL,
                    UNIQUE(run_id, sequence)
                );
                CREATE INDEX IF NOT EXISTS idx_events_run_sequence
                ON events(run_id, sequence);
                CREATE TABLE IF NOT EXISTS deepseek_usage (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT,
                    phase TEXT NOT NULL,
                    model TEXT NOT NULL,
                    prompt_tokens INTEGER NOT NULL,
                    cache_hit_tokens INTEGER NOT NULL,
                    cache_miss_tokens INTEGER NOT NULL,
                    completion_tokens INTEGER NOT NULL,
                    total_tokens INTEGER NOT NULL,
                    estimated_cost_usd REAL NOT NULL,
                    occurred_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_deepseek_usage_occurred_at
                ON deepseek_usage(occurred_at);
                """
            )
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(runs)").fetchall()
            }
            if "workspace_root" not in columns:
                connection.execute("ALTER TABLE runs ADD COLUMN workspace_root TEXT")
            if "parent_run_id" not in columns:
                connection.execute("ALTER TABLE runs ADD COLUMN parent_run_id TEXT")
            if "conversation_id" not in columns:
                connection.execute("ALTER TABLE runs ADD COLUMN conversation_id TEXT")
            if "turn_index" not in columns:
                connection.execute(
                    "ALTER TABLE runs ADD COLUMN turn_index INTEGER NOT NULL DEFAULT 1"
                )
            # 老数据视为各自对话的第一轮，迁移后即可作为后续任务的上游。
            connection.execute(
                "UPDATE runs SET conversation_id = id WHERE conversation_id IS NULL"
            )

    def create_run(
        self,
        run_id: str,
        objective: str,
        workspace_root: str,
        parent_run_id: str | None = None,
    ) -> dict[str, Any]:
        with self._connect() as connection:
            conversation_id = run_id
            turn_index = 1
            if parent_run_id:
                parent = connection.execute(
                    "SELECT id, status, conversation_id, turn_index FROM runs WHERE id = ?",
                    (parent_run_id,),
                ).fetchone()
                if not parent:
                    raise ValueError("上游任务不存在")
                if parent["status"] not in TERMINAL_STATUSES:
                    raise RuntimeError("上游任务仍在执行，请等待结束后再继续")
                conversation_id = parent["conversation_id"] or parent["id"]
                turn_index = int(parent["turn_index"] or 1) + 1
            connection.execute(
                "INSERT INTO runs(id, objective, workspace_root, parent_run_id, "
                "conversation_id, turn_index, status) VALUES (?, ?, ?, ?, ?, ?, 'queued')",
                (
                    run_id,
                    objective,
                    workspace_root,
                    parent_run_id,
                    conversation_id,
                    turn_index,
                ),
            )
        return self.get_run(run_id) or {}

    def run_ancestry(self, run_id: str, limit: int = 8) -> list[dict[str, Any]]:
        """读取从最早到最近的上游链，并防御脏数据造成的循环。"""

        chain: list[dict[str, Any]] = []
        current_id: str | None = run_id
        seen: set[str] = set()
        while current_id and len(chain) < limit and current_id not in seen:
            seen.add(current_id)
            run = self.get_run(current_id)
            if not run:
                break
            chain.append(run)
            current_id = run.get("parent_run_id")
        chain.reverse()
        return chain

    def update_run(self, run_id: str, status: str, **fields: Any) -> None:
        allowed = {"final_answer", "error"}
        assignments = ["status = ?", "updated_at = CURRENT_TIMESTAMP"]
        values: list[Any] = [status]
        for key, value in fields.items():
            if key in allowed:
                assignments.append(f"{key} = ?")
                values.append(value)
        values.append(run_id)
        with self._connect() as connection:
            connection.execute(
                f"UPDATE runs SET {', '.join(assignments)} WHERE id = ?", values
            )

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        return dict(row) if row else None

    def list_runs(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM runs ORDER BY created_at DESC, rowid DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(row) for row in rows]

    def recover_interrupted_runs(self) -> int:
        """进程启动时关闭上次进程遗留的 queued/running 记录。

        后台 worker 只存在于当前 Python 进程；服务重启后不可能继续这些记录，
        因此必须把它们从“永远运行中”的脏状态恢复为可检查、可删除的终态。
        """

        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE runs
                SET status = 'failed',
                    error = '后端进程已重启，原运行线程不存在',
                    updated_at = CURRENT_TIMESTAMP
                WHERE status IN ('queued', 'running')
                """
            )
        return cursor.rowcount

    def delete_run(self, run_id: str, *, allow_orphaned_active: bool = False) -> str:
        """删除终态运行及其级联事件；活动运行必须先取消并等待结束。"""

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT status FROM runs WHERE id = ?", (run_id,)
            ).fetchone()
            if not row:
                return "not_found"
            if row["status"] not in TERMINAL_STATUSES and not allow_orphaned_active:
                return "active"
            connection.execute("DELETE FROM runs WHERE id = ?", (run_id,))
        return "deleted"

    def append_event(self, event: RunEvent) -> RunEvent:
        # BEGIN IMMEDIATE 保证多个 Agent 并行上报时仍能得到唯一、递增的序号。
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 1 AS next_sequence "
                "FROM events WHERE run_id = ?",
                (event.run_id,),
            ).fetchone()
            event.sequence = int(row["next_sequence"])
            connection.execute(
                """
                INSERT INTO events(
                    run_id, sequence, type, timestamp, agent_id, task_id, payload
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.run_id,
                    event.sequence,
                    event.type,
                    event.timestamp,
                    event.agent_id,
                    event.task_id,
                    json.dumps(event.payload, ensure_ascii=False),
                ),
            )
        return event

    def append_deepseek_usage(self, record: dict[str, Any]) -> None:
        """保存一次 DeepSeek 响应的 usage；与远端账单完全独立。"""

        columns = (
            "run_id",
            "phase",
            "model",
            "prompt_tokens",
            "cache_hit_tokens",
            "cache_miss_tokens",
            "completion_tokens",
            "total_tokens",
            "estimated_cost_usd",
            "occurred_at",
        )
        with self._connect() as connection:
            connection.execute(
                f"INSERT INTO deepseek_usage({', '.join(columns)}) "
                f"VALUES ({', '.join('?' for _ in columns)})",
                tuple(record[column] for column in columns),
            )

    def summarize_deepseek_usage(self, since: str | None = None) -> dict[str, Any]:
        where = "WHERE occurred_at >= ?" if since else ""
        parameters = (since,) if since else ()
        with self._connect() as connection:
            row = connection.execute(
                f"""
                SELECT COUNT(*) AS requests,
                       COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
                       COALESCE(SUM(cache_hit_tokens), 0) AS cache_hit_tokens,
                       COALESCE(SUM(cache_miss_tokens), 0) AS cache_miss_tokens,
                       COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
                       COALESCE(SUM(total_tokens), 0) AS total_tokens,
                       COALESCE(SUM(estimated_cost_usd), 0) AS estimated_cost_usd,
                       MIN(occurred_at) AS first_recorded_at
                FROM deepseek_usage {where}
                """,
                parameters,
            ).fetchone()
        result = dict(row)
        result["estimated_cost_usd"] = f"{float(result['estimated_cost_usd']):.8f}"
        return result

    def list_events(self, run_id: str, after: int = 0) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM events WHERE run_id = ? AND sequence > ? ORDER BY sequence",
                (run_id, after),
            ).fetchall()
        events = []
        for row in rows:
            event = dict(row)
            event["payload"] = json.loads(event["payload"])
            event.pop("id", None)
            events.append(event)
        return events
