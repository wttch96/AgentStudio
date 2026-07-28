"""Pure operations over the blackboard embedded in LangGraph State."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, MutableMapping

from app.domain.models import BlackboardEntry, BlackboardState


class BlackboardStateOps:
    """Mutate a graph state's blackboard without owning persistence."""

    def __init__(self, state: MutableMapping[str, Any]) -> None:
        self.state = state
        self.state.setdefault("blackboard", {})
        self.state.setdefault("blackboard_revision", 0)

    def init(self) -> BlackboardState:
        self.state["blackboard"] = {}
        self.state["blackboard_revision"] = 0
        return self.snapshot()

    def read(self, key: str) -> Any | None:
        raw = self.state["blackboard"].get(key)
        if raw is None:
            return None
        return raw.value if isinstance(raw, BlackboardEntry) else raw.get("value")

    def read_all(self) -> dict[str, Any]:
        return {
            key: (raw.value if isinstance(raw, BlackboardEntry) else raw.get("value"))
            for key, raw in self.state["blackboard"].items()
        }

    def snapshot(self, run_id: str = "") -> BlackboardState:
        entries = {
            key: raw if isinstance(raw, BlackboardEntry) else BlackboardEntry.model_validate(raw)
            for key, raw in self.state["blackboard"].items()
        }
        return BlackboardState(
            run_id=run_id or str(self.state.get("run_id", "")),
            entries=entries,
            revision=int(self.state.get("blackboard_revision", 0)),
        )

    def write(
        self,
        key: str,
        value: Any,
        agent: str,
        expected_version: int | None = None,
    ) -> BlackboardEntry:
        current_raw = self.state["blackboard"].get(key)
        current = (
            current_raw
            if isinstance(current_raw, BlackboardEntry)
            else BlackboardEntry.model_validate(current_raw)
            if current_raw is not None
            else None
        )
        current_version = current.version if current else 0
        if expected_version is not None and expected_version != current_version:
            raise ValueError(
                f"CAS conflict: key={key} expected_version={expected_version} "
                f"actual_version={current_version}"
            )
        entry = BlackboardEntry(
            key=key,
            value=value,
            updated_by=agent,
            updated_at=datetime.now(timezone.utc).isoformat(),
            version=current_version + 1,
        )
        self.state["blackboard"][key] = entry.model_dump()
        self.state["blackboard_revision"] = int(self.state["blackboard_revision"]) + 1
        return entry

    def write_batch(self, updates: dict[str, Any], agent: str) -> None:
        for key, value in updates.items():
            self.write(key, value, agent)


# Compatibility name while callers are migrated; this object is no longer a store.
BlackboardOps = BlackboardStateOps
