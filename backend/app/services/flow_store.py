"""File-system + DB-backed flow definition store.

Flows live as YAML files under config/flows/ and are cached in the flow_definitions
table for fast lookup and keyword matching.
"""

from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path

import yaml

from app.flow_engine.model import FlowDefinition
from app.storage.sqlite_store import SQLiteStore


class FlowStore:
    """Load and manage flow definitions from YAML files + DB cache."""

    def __init__(
        self, flows_dir: Path, store: SQLiteStore | None = None,
        fallback_dir: Path | None = None,
    ) -> None:
        self.flows_dir = flows_dir
        self.fallback_dir = fallback_dir
        self.store = store
        self._lock = threading.RLock()
        self._cache: dict[str, FlowDefinition] = {}
        self._refresh()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def list_all(self) -> list[dict]:
        """Return summary list of all active flows."""
        with self._lock:
            self._refresh()
            return [
                {
                    "name": f.name,
                    "description": f.description,
                    "version": f.version,
                    "keywords": f.keywords,
                    "node_count": len(f.nodes),
                }
                for f in self._cache.values()
            ]

    def load(self, name: str) -> FlowDefinition:
        """Load a single flow by name (raises KeyError if missing)."""
        with self._lock:
            self._refresh()
            return self._cache[name]

    def save(self, name: str, content: str) -> FlowDefinition:
        """Validate and write a flow YAML to disk, then refresh cache."""
        from yaml import safe_load

        raw = safe_load(content)
        if not isinstance(raw, dict):
            raise ValueError("YAML 内容必须是字典")
        raw.setdefault("name", name)
        if raw["name"] != name:
            raise ValueError(f"YAML name 字段 ({raw['name']!r}) 与文件名不一致")

        flow = FlowDefinition.model_validate(raw)

        self.flows_dir.mkdir(parents=True, exist_ok=True)
        file_path = self.flows_dir / f"{name}.yaml"
        file_path.write_text(content, encoding="utf-8")

        with self._lock:
            self._cache[name] = flow
            self._sync_one_to_db(flow, file_path)

        return flow

    def delete(self, name: str) -> None:
        """Remove a flow YAML file and its DB cache entry."""
        file_path = self.flows_dir / f"{name}.yaml"
        with self._lock:
            self._cache.pop(name, None)
        if file_path.exists():
            file_path.unlink()
        if self.store:
            self.store.delete_flow_definition(name)

    def fuzzy_match(self, query: str) -> list[dict]:
        """Return flows whose name or keywords partially match the query."""
        q = query.lower().strip()
        if not q:
            return self.list_all()
        with self._lock:
            self._refresh()
            matches = []
            for f in self._cache.values():
                score = 0
                if q in f.name.lower():
                    score = 100
                elif any(q in kw.lower() for kw in f.keywords):
                    score = 50
                elif q in f.description.lower():
                    score = 25
                if score > 0:
                    matches.append({
                        "name": f.name,
                        "description": f.description,
                        "version": f.version,
                        "keywords": f.keywords,
                        "node_count": len(f.nodes),
                        "score": score,
                    })
            matches.sort(key=lambda m: m["score"], reverse=True)
            return matches

    def match_best(self, query: str, min_confidence: float = 0.7) -> tuple[str | None, float]:
        """Return the best-matching flow name and confidence for a user query."""
        matches = self.fuzzy_match(query)
        if not matches:
            return None, 0.0
        best = matches[0]
        # Normalize score: 100 → 1.0, 50 → 0.7, 25 → 0.4
        confidence = best["score"] / 100.0
        if confidence >= min_confidence:
            return best["name"], confidence
        return None, confidence

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _refresh(self) -> None:
        """Scan flows_dir for .yaml files and load new/changed ones into cache."""
        directories = [
            directory for directory in (self.fallback_dir, self.flows_dir)
            if directory is not None and directory.is_dir()
        ]
        if not directories:
            return

        loaded = set()
        yaml_files: dict[str, Path] = {}
        for directory in directories:
            for yaml_file in sorted(directory.glob("*.yaml")):
                yaml_files[yaml_file.stem] = yaml_file
        for name, yaml_file in yaml_files.items():
            loaded.add(name)
            # Check if we need to reload
            if name in self._cache:
                # Quick hash check via mtime — re-parse for simplicity in dev
                pass  # always re-parse for now; cheap enough for dev-scale YAML
            try:
                flow = self._parse_file(yaml_file)
                self._cache[name] = flow
                if self.store:
                    self._sync_one_to_db(flow, yaml_file)
            except Exception:
                # Keep old cache entry if parse fails
                pass

        # Remove cache entries for deleted files
        stale = set(self._cache.keys()) - loaded
        for name in stale:
            self._cache.pop(name, None)
            if self.store:
                self.store.delete_flow_definition(name)

    def _parse_file(self, path: Path) -> FlowDefinition:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        return FlowDefinition.model_validate(raw)

    def _sync_one_to_db(self, flow: FlowDefinition, file_path: Path) -> None:
        if not self.store:
            return
        content = file_path.read_text(encoding="utf-8")
        file_hash = hashlib.sha256(content.encode()).hexdigest()
        self.store.upsert_flow_definition(
            name=flow.name,
            file_path=str(file_path),
            description=flow.description,
            version=flow.version,
            node_count=len(flow.nodes),
            hash_str=file_hash,
        )
