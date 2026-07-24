"""轻量本地持久化。

每次操作创建短连接，配合 WAL 模式支持 Flask 请求线程、后台图线程和 SSE 线程并发访问。
"""

from __future__ import annotations

import json
import sqlite3
import uuid
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
                CREATE TABLE IF NOT EXISTS memories (
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    conversation_id TEXT NOT NULL,
                    level TEXT NOT NULL CHECK(level IN ('agent','planner','session','project')),
                    agent_id TEXT,
                    task_id TEXT,
                    phase TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    structured_data TEXT,
                    token_count_before INTEGER NOT NULL DEFAULT 0,
                    token_count_after INTEGER NOT NULL DEFAULT 0,
                    importance REAL NOT NULL DEFAULT 0.5,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_memories_conversation
                ON memories(conversation_id, level, created_at);
                CREATE INDEX IF NOT EXISTS idx_memories_agent
                ON memories(agent_id, created_at);
                CREATE TABLE IF NOT EXISTS session_summaries (
                    conversation_id TEXT PRIMARY KEY,
                    title TEXT,
                    summary TEXT NOT NULL,
                    key_decisions TEXT,
                    total_turns INTEGER NOT NULL DEFAULT 0,
                    total_tokens INTEGER NOT NULL DEFAULT 0,
                    last_updated TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS agent_memory_state (
                    agent_id TEXT NOT NULL,
                    conversation_id TEXT NOT NULL,
                    extracted_facts TEXT NOT NULL DEFAULT '{}',
                    token_budget INTEGER NOT NULL DEFAULT 32000,
                    last_updated TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (agent_id, conversation_id)
                );
                CREATE TABLE IF NOT EXISTS planner_memory_state (
                    conversation_id TEXT PRIMARY KEY,
                    decision_log TEXT NOT NULL DEFAULT '[]',
                    agent_notes TEXT NOT NULL DEFAULT '{}',
                    project_notes TEXT NOT NULL DEFAULT '{}',
                    contract_history TEXT NOT NULL DEFAULT '[]',
                    last_updated TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS interrupt_commands (
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    target TEXT NOT NULL,
                    action TEXT NOT NULL,
                    target_agent_id TEXT,
                    target_task_id TEXT,
                    instruction TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'pending',
                    resolved_at TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_interrupt_run
                ON interrupt_commands(run_id, status);
                CREATE TABLE IF NOT EXISTS projects (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    root_dir TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS project_agents (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    name TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    template_id TEXT,
                    agent_type TEXT NOT NULL CHECK(agent_type IN ('brain','rag','claude','deepseek')),
                    sub_dir TEXT DEFAULT '',
                    system_prompt TEXT NOT NULL,
                    tools TEXT NOT NULL DEFAULT '[]',
                    skills TEXT NOT NULL DEFAULT '[]',
                    is_required INTEGER NOT NULL DEFAULT 0,
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(project_id, name)
                );
                CREATE TABLE IF NOT EXISTS agent_templates (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    display_name TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    category TEXT NOT NULL,
                    agent_type TEXT NOT NULL DEFAULT 'claude',
                    default_sub_dir TEXT DEFAULT '',
                    default_prompt TEXT NOT NULL,
                    default_tools TEXT NOT NULL DEFAULT '[]',
                    default_skills TEXT NOT NULL DEFAULT '[]',
                    is_builtin INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS configs (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS knowledge_entries (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL DEFAULT '',
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    category TEXT NOT NULL DEFAULT 'general',
                    tags TEXT NOT NULL DEFAULT '[]',
                    source TEXT DEFAULT '',
                    source_type TEXT NOT NULL DEFAULT 'manual',
                    score REAL NOT NULL DEFAULT 0.0,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    expires_at TEXT,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS knowledge_relations (
                    id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL REFERENCES knowledge_entries(id) ON DELETE CASCADE,
                    target_id TEXT NOT NULL REFERENCES knowledge_entries(id) ON DELETE CASCADE,
                    relation_type TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(source_id, target_id, relation_type)
                );
                CREATE TABLE IF NOT EXISTS knowledge_feedback (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    entry_id TEXT NOT NULL REFERENCES knowledge_entries(id) ON DELETE CASCADE,
                    feedback TEXT NOT NULL CHECK(feedback IN ('up', 'down')),
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
CREATE TABLE IF NOT EXISTS project_skills (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    name TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    content TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(project_id, name)
                );
CREATE INDEX IF NOT EXISTS idx_interrupt_run
                ON interrupt_commands(run_id, status);
                CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts USING fts5(
                    title, content, category, tags
                );
                CREATE TRIGGER IF NOT EXISTS knowledge_fts_insert
                AFTER INSERT ON knowledge_entries BEGIN
                    INSERT INTO knowledge_fts(rowid, title, content, category, tags)
                    VALUES (new.rowid, new.title, new.content, new.category, new.tags);
                END;
                CREATE TRIGGER IF NOT EXISTS knowledge_fts_update
                AFTER UPDATE ON knowledge_entries BEGIN
                    UPDATE knowledge_fts SET title=new.title, content=new.content,
                        category=new.category, tags=new.tags WHERE rowid=old.rowid;
                END;
                CREATE TRIGGER IF NOT EXISTS knowledge_fts_delete
                AFTER DELETE ON knowledge_entries BEGIN
                    DELETE FROM knowledge_fts WHERE rowid=old.rowid;
                END;
                CREATE TABLE IF NOT EXISTS skill_templates (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    display_name TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    category TEXT DEFAULT 'general',
                    content TEXT NOT NULL,
                    is_builtin INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
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
            if "started_at" not in columns:
                connection.execute("ALTER TABLE runs ADD COLUMN started_at TEXT")
            if "project_id" not in columns:
                connection.execute("ALTER TABLE runs ADD COLUMN project_id TEXT REFERENCES projects(id) ON DELETE SET NULL")
            if "forked_from_run_id" not in columns:
                connection.execute("ALTER TABLE runs ADD COLUMN forked_from_run_id TEXT")
            # Migrate knowledge_entries: add project_id column if missing
            kn_columns = {row["name"] for row in connection.execute("PRAGMA table_info(knowledge_entries)").fetchall()}
            if "project_id" not in kn_columns:
                connection.execute("ALTER TABLE knowledge_entries ADD COLUMN project_id TEXT NOT NULL DEFAULT ''")
            if "source_type" not in kn_columns:
                connection.execute("ALTER TABLE knowledge_entries ADD COLUMN source_type TEXT NOT NULL DEFAULT 'manual'")
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

    def fork_run(
        self,
        source_run_id: str,
        new_run_id: str,
        objective: str,
        workspace_root: str,
    ) -> dict[str, Any]:
        """从源 run fork 出新分支：新的 conversation_id + 继承记忆上下文。"""
        source = self.get_run(source_run_id)
        if not source:
            raise ValueError("源任务不存在")
        source_conv_id = source.get("conversation_id", source_run_id)
        memories = self.query_memories(source_conv_id, limit=20) or []
        memory_context = self._format_memories_as_context(memories)
        with self._connect() as connection:
            conversation_id = new_run_id
            connection.execute(
                "INSERT INTO runs(id, objective, workspace_root, parent_run_id, "
                "conversation_id, turn_index, forked_from_run_id, status) "
                "VALUES (?, ?, ?, NULL, ?, 1, ?, 'queued')",
                (new_run_id, objective, workspace_root, conversation_id, source_run_id),
            )
        run = self.get_run(new_run_id) or {}
        run["_memory_context"] = memory_context
        run["_memory_count"] = len(memories)
        return run

    def get_fork_preview(self, source_run_id: str) -> dict[str, Any] | None:
        """返回 fork 预览：源对话的记忆统计。"""
        source = self.get_run(source_run_id)
        if not source:
            return None
        conv_id = source.get("conversation_id", source_run_id)
        stats = self.get_memory_stats(conv_id)
        memories = self.query_memories(conv_id, limit=5) or []
        return {
            "source_run_id": source_run_id,
            "source_objective": source.get("objective", ""),
            "turn_count": source.get("turn_index", 1),
            "memory_stats": stats,
            "recent_memories": [
                {"phase": m.get("phase", ""), "summary": (m.get("summary", "") or "")[:200]}
                for m in memories
            ],
        }

    @staticmethod
    def _format_memories_as_context(memories: list[dict]) -> str:
        """将记忆列表格式化为可注入的上下文文本。"""
        if not memories:
            return ""
        lines = ["[从历史对话中继承的记忆]"]
        for m in memories:
            phase = m.get("phase", "")
            summary = m.get("summary", "") or ""
            level = m.get("level", "")
            if summary.strip():
                lines.append(f"- [{level}/{phase}] {summary[:300]}")
        return "\n".join(lines)

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
        allowed = {"final_answer", "error", "started_at"}
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


    # ==================== 分层记忆 Repository ====================

    def insert_memory(self, record: dict[str, Any]) -> None:
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO memories(
                    id, run_id, conversation_id, level, agent_id, task_id,
                    phase, summary, structured_data, token_count_before,
                    token_count_after, importance, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    record["id"],
                    record["run_id"],
                    record["conversation_id"],
                    record["level"],
                    record.get("agent_id"),
                    record.get("task_id"),
                    record["phase"],
                    record["summary"],
                    json.dumps(record.get("structured_data") or {}, ensure_ascii=False),
                    record.get("token_count_before", 0),
                    record.get("token_count_after", 0),
                    record.get("importance", 0.5),
                    record["created_at"],
                ),
            )

    def query_memories(
        self,
        conversation_id: str,
        level: str | None = None,
        agent_id: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        conditions = ["conversation_id = ?"]
        params: list[Any] = [conversation_id]
        if level:
            conditions.append("level = ?")
            params.append(level)
        if agent_id:
            conditions.append("agent_id = ?")
            params.append(agent_id)
        with self._connect() as connection:
            rows = connection.execute(
                f"""SELECT * FROM memories
                WHERE {' AND '.join(conditions)}
                ORDER BY created_at DESC
                LIMIT ?""",
                [*params, limit],
            ).fetchall()
        return [self._deserialize_memory(dict(row)) for row in rows]

    def get_recent_memories(
        self, conversation_id: str, level: str, limit: int = 10
    ) -> list[dict[str, Any]]:
        return self.query_memories(conversation_id, level=level, limit=limit)

    def upsert_session_summary(
        self,
        conversation_id: str,
        summary: str,
        title: str = "",
        key_decisions: list[str] | None = None,
        total_turns: int = 0,
        total_tokens: int = 0,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO session_summaries(
                    conversation_id, title, summary, key_decisions,
                    total_turns, total_tokens, last_updated
                ) VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(conversation_id) DO UPDATE SET
                    title = COALESCE(excluded.title, session_summaries.title),
                    summary = excluded.summary,
                    key_decisions = excluded.key_decisions,
                    total_turns = excluded.total_turns,
                    total_tokens = excluded.total_tokens,
                    last_updated = CURRENT_TIMESTAMP""",
                (
                    conversation_id,
                    title or None,
                    summary,
                    json.dumps(key_decisions or [], ensure_ascii=False),
                    total_turns,
                    total_tokens,
                ),
            )

    def get_session_summary(self, conversation_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM session_summaries WHERE conversation_id = ?",
                (conversation_id,),
            ).fetchone()
        if not row:
            return None
        result = dict(row)
        result["key_decisions"] = json.loads(result.get("key_decisions", "[]"))
        return result

    def save_agent_memory_state(
        self, agent_id: str, conversation_id: str, state: dict[str, Any]
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO agent_memory_state(
                    agent_id, conversation_id, extracted_facts, token_budget, last_updated
                ) VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(agent_id, conversation_id) DO UPDATE SET
                    extracted_facts = excluded.extracted_facts,
                    token_budget = excluded.token_budget,
                    last_updated = CURRENT_TIMESTAMP""",
                (
                    agent_id,
                    conversation_id,
                    json.dumps(state.get("extracted_facts", {}), ensure_ascii=False),
                    state.get("token_budget", 32000),
                ),
            )

    def get_agent_memory_state(
        self, agent_id: str, conversation_id: str
    ) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM agent_memory_state WHERE agent_id = ? AND conversation_id = ?",
                (agent_id, conversation_id),
            ).fetchone()
        if not row:
            return None
        result = dict(row)
        result["extracted_facts"] = json.loads(result.get("extracted_facts", "{}"))
        return result

    def save_planner_memory_state(
        self, conversation_id: str, state: dict[str, Any]
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO planner_memory_state(
                    conversation_id, decision_log, agent_notes,
                    project_notes, contract_history, last_updated
                ) VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(conversation_id) DO UPDATE SET
                    decision_log = excluded.decision_log,
                    agent_notes = excluded.agent_notes,
                    project_notes = excluded.project_notes,
                    contract_history = excluded.contract_history,
                    last_updated = CURRENT_TIMESTAMP""",
                (
                    conversation_id,
                    json.dumps(state.get("decision_log", []), ensure_ascii=False),
                    json.dumps(state.get("agent_capability_notes", {}), ensure_ascii=False),
                    json.dumps(state.get("project_structure_notes", {}), ensure_ascii=False),
                    json.dumps(state.get("contract_history", []), ensure_ascii=False),
                ),
            )

    def get_planner_memory_state(
        self, conversation_id: str
    ) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM planner_memory_state WHERE conversation_id = ?",
                (conversation_id,),
            ).fetchone()
        if not row:
            return None
        result = dict(row)
        for field in ("decision_log", "agent_notes", "project_notes", "contract_history"):
            raw = result.get(field, "[]" if field in ("decision_log", "contract_history") else "{}")
            result[field] = json.loads(raw)
        return result

    # ==================== 中断指令 Repository ====================

    def insert_interrupt_command(self, record: dict[str, Any]) -> None:
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO interrupt_commands(
                    id, run_id, target, action, target_agent_id,
                    target_task_id, instruction, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)""",
                (
                    record["id"],
                    record["run_id"],
                    record["target"],
                    record["action"],
                    record.get("target_agent_id"),
                    record.get("target_task_id"),
                    record.get("instruction", ""),
                    record["created_at"],
                ),
            )

    def get_pending_interrupts(self, run_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM interrupt_commands WHERE run_id = ? AND status = 'pending' ORDER BY created_at",
                (run_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def resolve_interrupt(self, command_id: str, status: str = "resolved") -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE interrupt_commands SET status = ?, resolved_at = CURRENT_TIMESTAMP WHERE id = ?",
                (status, command_id),
            )

    def get_memory_stats(self, conversation_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            counts = connection.execute(
                """SELECT level, COUNT(*) as cnt
                FROM memories WHERE conversation_id = ?
                GROUP BY level""",
                (conversation_id,),
            ).fetchall()
            tokens = connection.execute(
                """SELECT COALESCE(SUM(token_count_before), 0) as total_before,
                       COALESCE(SUM(token_count_after), 0) as total_after
                FROM memories WHERE conversation_id = ?""",
                (conversation_id,),
            ).fetchone()
            times = connection.execute(
                """SELECT MIN(created_at) as oldest, MAX(created_at) as newest
                FROM memories WHERE conversation_id = ?""",
                (conversation_id,),
            ).fetchone()
        memories_by_level = {row["level"]: row["cnt"] for row in counts}
        total_before = int(tokens["total_before"])
        total_after = int(tokens["total_after"])
        return {
            "conversation_id": conversation_id,
            "total_memories": sum(memories_by_level.values()),
            "memories_by_level": memories_by_level,
            "total_tokens_saved": max(0, total_before - total_after),
            "compression_ratio": round(total_after / total_before, 3) if total_before > 0 else 1.0,
            "oldest_memory": times["oldest"] if times else None,
            "newest_memory": times["newest"] if times else None,
        }

    @staticmethod
    def _deserialize_memory(row: dict[str, Any]) -> dict[str, Any]:
        row["structured_data"] = json.loads(row.get("structured_data", "{}"))
        return row

    # ==================== 配置存储 ====================

    def get_config(self, key):
        with self._connect() as connection:
            row = connection.execute(
                "SELECT value FROM configs WHERE key = ?", (key,)
            ).fetchone()
        return json.loads(row["value"]) if row else None

    def set_config(self, key, value):
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO configs(key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP",
                (key, json.dumps(value, ensure_ascii=False)),
            )

    def list_configs(self):
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT key, updated_at FROM configs ORDER BY key"
            ).fetchall()
        return [dict(row) for row in rows]

    def migrate_config_from_file(self, key, file_path):
        import os
        if not os.path.isfile(file_path):
            return False
        if self.get_config(key) is not None:
            return False
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.set_config(key, data)
            os.remove(file_path)
            return True
        except Exception:
            return False

    # ==================== 知识库 CRUD ====================

    def insert_knowledge(self, record):
        """插入知识条目。FTS 索引由 knowledge_fts_insert 触发器自动维护。"""
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO knowledge_entries("
                "id, project_id, title, content, category, tags, source, source_type, score, expires_at, created_at, updated_at"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)",
                (
                    record["id"], record.get("project_id", ""),
                    record["title"], record["content"],
                    record.get("category", "general"),
                    json.dumps(record.get("tags", []), ensure_ascii=False),
                    record.get("source", ""), record.get("source_type", "manual"),
                    record.get("score", 0.0),
                    record.get("expires_at"), record.get("created_at", ""),
                ),
            )
        return record["id"]

    def update_knowledge(self, entry_id, updates):
        """更新知识条目。FTS 索引由 knowledge_fts_update 触发器自动维护。"""
        allowed = {"title", "content", "category", "tags", "score", "expires_at"}
        fields = {k: v for k, v in updates.items() if k in allowed}
        if not fields:
            return False
        if "tags" in fields and not isinstance(fields["tags"], str):
            fields["tags"] = json.dumps(fields["tags"], ensure_ascii=False)
        set_clause = ", ".join("{} = ?".format(k) for k in fields)
        set_clause += ", updated_at = CURRENT_TIMESTAMP"
        values = list(fields.values()) + [entry_id]
        with self._connect() as connection:
            cursor = connection.execute(
                f"UPDATE knowledge_entries SET {set_clause} WHERE id = ?", values
            )
            if cursor.rowcount == 0:
                return False
        return True

    def delete_knowledge(self, entry_id):
        """删除知识条目。FTS 索引由 knowledge_fts_delete 触发器自动维护。"""
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM knowledge_entries WHERE id = ?", (entry_id,)
            )
            return cursor.rowcount > 0

    def get_knowledge(self, entry_id):
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM knowledge_entries WHERE id = ?", (entry_id,)
            ).fetchone()
        if not row:
            return None
        result = dict(row)
        result["tags"] = json.loads(result.get("tags", "[]"))
        return result

    def search_knowledge_fts(self, query, category=None, limit=20, project_id=""):
        conditions = ["knowledge_fts MATCH ?"]
        params = [query]
        if project_id:
            conditions.append("knowledge_entries.project_id = ?")
            params.append(project_id)
        if category:
            conditions.append("knowledge_entries.category = ?")
            params.append(category)
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT knowledge_entries.id FROM knowledge_fts "
                "JOIN knowledge_entries ON knowledge_fts.rowid = knowledge_entries.rowid "
                f"WHERE {' AND '.join(conditions)} ORDER BY rank LIMIT ?",
                params + [limit],
            ).fetchall()
        return [row["id"] for row in rows]

    def cleanup_expired_knowledge(self):
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id, rowid FROM knowledge_entries "
                "WHERE expires_at IS NOT NULL AND expires_at < datetime('now')"
            ).fetchall()
            count = 0
            for row in rows:
                connection.execute("DELETE FROM knowledge_fts WHERE rowid = ?", (row["rowid"],))
                connection.execute("DELETE FROM knowledge_entries WHERE id = ?", (row["id"],))
                count += 1
        return count

    def list_knowledge(self, category=None, limit=50, offset=0, project_id=""):
        conditions = []
        params = []
        if project_id:
            conditions.append("project_id = ?")
            params.append(project_id)
        if category:
            conditions.append("category = ?")
            params.append(category)
        where = "WHERE " + " AND ".join(conditions) if conditions else ""
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM knowledge_entries {where} "
                "ORDER BY score DESC, updated_at DESC LIMIT ? OFFSET ?",
                params + [limit, offset],
            ).fetchall()
        results = []
        for row in rows:
            r = dict(row)
            r["tags"] = json.loads(r.get("tags", "[]"))
            results.append(r)
        return results

    def knowledge_stats(self, project_id: str = ""):
        project_filter = "WHERE project_id = ?" if project_id else ""
        params = (project_id,) if project_id else ()
        with self._connect() as connection:
            total = connection.execute(
                f"SELECT COUNT(*) as cnt FROM knowledge_entries {project_filter}", params
            ).fetchone()
            by_cat = connection.execute(
                f"SELECT category, COUNT(*) as cnt FROM knowledge_entries {project_filter} GROUP BY category",
                params,
            ).fetchall()
            expired = connection.execute(
                f"SELECT COUNT(*) as cnt FROM knowledge_entries "
                f"WHERE expires_at IS NOT NULL AND expires_at < datetime('now')"
                f"{' AND project_id = ?' if project_id else ''}",
                (project_id,) if project_id else (),
            ).fetchone()
            relations = connection.execute("SELECT COUNT(*) as cnt FROM knowledge_relations").fetchone()
        return {
            "total": total["cnt"],
            "by_category": {r["category"]: r["cnt"] for r in by_cat},
            "expired": expired["cnt"],
            "relations": relations["cnt"],
        }

    def add_knowledge_relation(self, source_id, target_id, relation_type):
        rid = uuid.uuid4().hex
        with self._connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO knowledge_relations(id, source_id, target_id, relation_type) "
                "VALUES (?, ?, ?, ?)",
                (rid, source_id, target_id, relation_type),
            )
        return rid

    def get_knowledge_relations(self, entry_id):
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM knowledge_relations "
                "WHERE source_id = ? OR target_id = ? ORDER BY created_at DESC",
                (entry_id, entry_id),
            ).fetchall()
        return [dict(row) for row in rows]

    def add_knowledge_feedback(self, entry_id, feedback):
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO knowledge_feedback(entry_id, feedback) VALUES (?, ?)",
                (entry_id, feedback),
            )
            connection.execute(
                "UPDATE knowledge_entries SET score = ("
                "SELECT COALESCE("
                "CAST(SUM(CASE WHEN feedback='up' THEN 1 ELSE 0 END) AS REAL) / "
                "NULLIF(COUNT(*), 0) * 100, 0"
                ") FROM knowledge_feedback WHERE entry_id = ?"
                ") WHERE id = ?",
                (entry_id, entry_id),
            )
