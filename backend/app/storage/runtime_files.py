"""Human-readable, file-backed runtime records for a single project."""

from __future__ import annotations

import json
import shutil
import threading
from pathlib import Path
from typing import Any


class RuntimeFiles:
    """Owns append-only events and replaceable state under project ``runs/``.

    JSON is deliberately used for mutable runtime state. YAML remains reserved
    for configuration that users are expected to edit by hand.
    """

    def __init__(self, project_dir: Path) -> None:
        self.runs_dir = project_dir / "runs"
        self._lock = threading.RLock()

    def _run_dir(self, run_id: str) -> Path:
        return self.runs_dir / run_id

    def save_state(self, run_id: str, state: dict[str, Any]) -> None:
        with self._lock:
            path = self._run_dir(run_id) / "state.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(".tmp")
            temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            temporary.replace(path)

    def load_state(self, run_id: str) -> dict[str, Any] | None:
        path = self._run_dir(run_id) / "state.json"
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def append_event(self, run_id: str, event: dict[str, Any]) -> None:
        with self._lock:
            path = self._run_dir(run_id) / "events.jsonl"
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event, ensure_ascii=False) + "\n")

    def append_next_event(self, run_id: str, event: dict[str, Any]) -> int:
        """Append and allocate a per-run sequence under one process lock."""
        with self._lock:
            sequence = len(self.list_events(run_id)) + 1
            event["sequence"] = sequence
            path = self._run_dir(run_id) / "events.jsonl"
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event, ensure_ascii=False) + "\n")
            return sequence

    def list_events(self, run_id: str) -> list[dict[str, Any]]:
        path = self._run_dir(run_id) / "events.jsonl"
        if not path.is_file():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def delete_run(self, run_id: str) -> None:
        path = self._run_dir(run_id)
        if path.is_dir():
            shutil.rmtree(path)
