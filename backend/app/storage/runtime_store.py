"""Project-scoped file persistence for non-RAG runtime data."""

from __future__ import annotations

import json
import shutil
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


TERMINAL_STATUSES = {"completed", "failed", "cancelled", "awaiting_confirmation"}


class RuntimeStore:
    """Persist runs, memory, interrupts and traces as observable project files."""

    def __init__(self, project_dir: Path) -> None:
        self.project_dir = Path(project_dir)
        self.runs_dir = self.project_dir / "runs"
        self.memory_dir = self.project_dir / "memory"
        self._lock = threading.RLock()
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self.memory_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _read(path: Path, default: Any) -> Any:
        if not path.is_file():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return default

    @staticmethod
    def _write(path: Path, value: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(
            f".{path.name}.{threading.get_ident()}.tmp"
        )
        temporary.write_text(
            json.dumps(value, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        for attempt in range(5):
            try:
                temporary.replace(path)
                return
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.01 * (attempt + 1))

    def _run_dir(self, run_id: str) -> Path:
        return self.runs_dir / run_id

    def _run_path(self, run_id: str) -> Path:
        return self._run_dir(run_id) / "run.json"

    # Runs -----------------------------------------------------------------

    def create_run(
        self,
        run_id: str,
        objective: str,
        workspace_root: str,
        parent_run_id: str | None = None,
        project_id: str | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            conversation_id = run_id
            turn_index = 1
            if parent_run_id:
                parent = self.get_run(parent_run_id)
                if not parent:
                    raise ValueError("上游任务不存在")
                if parent["status"] not in TERMINAL_STATUSES:
                    raise RuntimeError("上游任务仍在执行，请等待结束后再继续")
                conversation_id = parent.get("conversation_id") or parent["id"]
                turn_index = int(parent.get("turn_index") or 1) + 1
            now = self._now()
            run = {
                "id": run_id,
                "objective": objective,
                "workspace_root": workspace_root,
                "parent_run_id": parent_run_id,
                "conversation_id": conversation_id,
                "turn_index": turn_index,
                "project_id": project_id or "",
                "status": "queued",
                "final_answer": None,
                "error": None,
                "created_at": now,
                "updated_at": now,
            }
            self._write(self._run_path(run_id), run)
            return run

    def fork_run(
        self, source_run_id: str, new_run_id: str, objective: str, workspace_root: str
    ) -> dict[str, Any]:
        source = self.get_run(source_run_id)
        if not source:
            raise ValueError("源任务不存在")
        memories = self.query_memories(
            source.get("conversation_id") or source_run_id, limit=20
        )
        run = self.create_run(
            new_run_id, objective, workspace_root, project_id=source.get("project_id")
        )
        run["forked_from_run_id"] = source_run_id
        self._write(self._run_path(new_run_id), run)
        run["_memory_context"] = self._format_memories_as_context(memories)
        run["_memory_count"] = len(memories)
        return run

    def get_fork_preview(self, source_run_id: str) -> dict[str, Any] | None:
        source = self.get_run(source_run_id)
        if not source:
            return None
        conversation_id = source.get("conversation_id") or source_run_id
        memories = self.query_memories(conversation_id, limit=5)
        return {
            "source_run_id": source_run_id,
            "source_objective": source.get("objective", ""),
            "turn_count": source.get("turn_index", 1),
            "memory_stats": self.get_memory_stats(conversation_id),
            "recent_memories": [
                {"phase": item.get("phase", ""), "summary": item.get("summary", "")[:200]}
                for item in memories
            ],
        }

    @staticmethod
    def _format_memories_as_context(memories: list[dict[str, Any]]) -> str:
        lines = ["[从历史对话中继承的记忆]"]
        for item in memories:
            summary = str(item.get("summary") or "").strip()
            if summary:
                lines.append(
                    f"- [{item.get('level', '')}/{item.get('phase', '')}] {summary[:300]}"
                )
        return "\n".join(lines) if len(lines) > 1 else ""

    def update_run(self, run_id: str, status: str, **fields: Any) -> None:
        with self._lock:
            run = self.get_run(run_id)
            if not run:
                return
            run["status"] = status
            for key in ("final_answer", "error", "started_at"):
                if key in fields:
                    run[key] = fields[key]
            run["updated_at"] = self._now()
            self._write(self._run_path(run_id), run)

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        run = self._read(self._run_path(run_id), None)
        return dict(run) if isinstance(run, dict) else None

    def list_runs(
        self, limit: int = 50, project_id: str | None = None
    ) -> list[dict[str, Any]]:
        runs = [
            run for path in self.runs_dir.glob("*/run.json")
            if (run := self._read(path, None))
            and run.get("parent_run_id") is None
            and (not project_id or run.get("project_id") == project_id)
        ]
        runs.sort(key=lambda item: item.get("created_at", ""), reverse=True)
        return runs[:limit]

    def get_runs_by_conversation(self, conversation_id: str) -> list[dict[str, Any]]:
        runs = [
            run for path in self.runs_dir.glob("*/run.json")
            if (run := self._read(path, None))
            and run.get("conversation_id") == conversation_id
        ]
        return sorted(runs, key=lambda item: int(item.get("turn_index", 1)))

    def run_ancestry(self, run_id: str, limit: int = 8) -> list[dict[str, Any]]:
        chain: list[dict[str, Any]] = []
        seen: set[str] = set()
        current: str | None = run_id
        while current and current not in seen and len(chain) < limit:
            seen.add(current)
            run = self.get_run(current)
            if not run:
                break
            chain.append(run)
            current = run.get("parent_run_id")
        chain.reverse()
        return chain

    def recover_interrupted_runs(self) -> int:
        count = 0
        for path in self.runs_dir.glob("*/run.json"):
            run = self._read(path, None)
            if run and run.get("status") in {"queued", "running"}:
                run.update({
                    "status": "failed",
                    "error": "后端进程已重启，原运行线程不存在",
                    "updated_at": self._now(),
                })
                self._write(path, run)
                count += 1
        return count

    def delete_run(self, run_id: str, *, allow_orphaned_active: bool = False) -> str:
        with self._lock:
            run = self.get_run(run_id)
            if not run:
                return "not_found"
            if run.get("status") not in TERMINAL_STATUSES and not allow_orphaned_active:
                return "active"
            shutil.rmtree(self._run_dir(run_id))
            return "deleted"

    # Memory ---------------------------------------------------------------

    @property
    def _memories_path(self) -> Path:
        return self.memory_dir / "memories.jsonl"

    def _all_memories(self) -> list[dict[str, Any]]:
        if not self._memories_path.is_file():
            return []
        result = []
        for line in self._memories_path.read_text(encoding="utf-8").splitlines():
            try:
                result.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return result

    def insert_memory(self, record: dict[str, Any]) -> None:
        with self._lock:
            self._memories_path.parent.mkdir(parents=True, exist_ok=True)
            with self._memories_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    def query_memories(
        self,
        conversation_id: str,
        level: str | None = None,
        agent_id: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        result = [
            item for item in self._all_memories()
            if item.get("conversation_id") == conversation_id
            and (not level or item.get("level") == level)
            and (not agent_id or item.get("agent_id") == agent_id)
        ]
        result.sort(key=lambda item: item.get("created_at", ""), reverse=True)
        return result[:limit]

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
        path = self.memory_dir / "sessions" / f"{conversation_id}.json"
        self._write(path, {
            "conversation_id": conversation_id,
            "title": title,
            "summary": summary,
            "key_decisions": key_decisions or [],
            "total_turns": total_turns,
            "total_tokens": total_tokens,
            "last_updated": self._now(),
        })

    def get_session_summary(self, conversation_id: str) -> dict[str, Any] | None:
        return self._read(
            self.memory_dir / "sessions" / f"{conversation_id}.json", None
        )

    def save_planner_memory_state(
        self, conversation_id: str, state: dict[str, Any]
    ) -> None:
        self._write(
            self.memory_dir / "planner" / f"{conversation_id}.json",
            {**state, "conversation_id": conversation_id, "last_updated": self._now()},
        )

    def get_planner_memory_state(
        self, conversation_id: str
    ) -> dict[str, Any] | None:
        return self._read(
            self.memory_dir / "planner" / f"{conversation_id}.json", None
        )

    def get_memory_stats(self, conversation_id: str) -> dict[str, Any]:
        items = self.query_memories(conversation_id, limit=1_000_000)
        by_level: dict[str, int] = {}
        for item in items:
            level = str(item.get("level", ""))
            by_level[level] = by_level.get(level, 0) + 1
        before = sum(int(item.get("token_count_before", 0)) for item in items)
        after = sum(int(item.get("token_count_after", 0)) for item in items)
        times = [item.get("created_at") for item in items if item.get("created_at")]
        return {
            "conversation_id": conversation_id,
            "total_memories": len(items),
            "memories_by_level": by_level,
            "total_tokens_saved": max(0, before - after),
            "compression_ratio": round(after / before, 3) if before else 1.0,
            "oldest_memory": min(times) if times else None,
            "newest_memory": max(times) if times else None,
        }

    # Interrupts -----------------------------------------------------------

    def _interrupts_path(self, run_id: str) -> Path:
        return self._run_dir(run_id) / "interrupts.json"

    def insert_interrupt_command(self, record: dict[str, Any]) -> None:
        with self._lock:
            items = self._read(self._interrupts_path(record["run_id"]), [])
            items.append({**record, "status": "pending"})
            self._write(self._interrupts_path(record["run_id"]), items)

    def get_pending_interrupts(self, run_id: str) -> list[dict[str, Any]]:
        return [
            item for item in self._read(self._interrupts_path(run_id), [])
            if item.get("status") == "pending"
        ]

    def resolve_interrupt(self, command_id: str, status: str = "resolved") -> None:
        with self._lock:
            for path in self.runs_dir.glob("*/interrupts.json"):
                items = self._read(path, [])
                changed = False
                for item in items:
                    if item.get("id") == command_id:
                        item["status"] = status
                        item["resolved_at"] = self._now()
                        changed = True
                if changed:
                    self._write(path, items)
                    return

    # Flow traces ----------------------------------------------------------

    def _traces_path(self, run_id: str) -> Path:
        return self._run_dir(run_id) / "flow-traces.json"

    def save_flow_trace(self, trace: dict[str, Any]) -> None:
        with self._lock:
            run_id = trace["run_id"]
            traces = self._read(self._traces_path(run_id), [])
            by_node = {item["node_id"]: item for item in traces}
            by_node[trace["node_id"]] = dict(trace)
            ordered = sorted(by_node.values(), key=lambda item: item.get("sequence", 0))
            self._write(self._traces_path(run_id), ordered)

    def list_flow_traces(self, run_id: str) -> list[dict[str, Any]]:
        return self._read(self._traces_path(run_id), [])
