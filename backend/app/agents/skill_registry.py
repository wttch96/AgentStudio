"""项目级 Claude Skill 的读取、创建和更新服务。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from threading import RLock

import yaml


@dataclass(frozen=True, slots=True)
class SkillProfile:
    name: str
    description: str
    content: str


class SkillRegistry:
    def __init__(self, skills_dir: Path, store=None) -> None:
        self.skills_dir = skills_dir
        self.skills_dir.mkdir(parents=True, exist_ok=True)
        self._store = store
        self._lock = RLock()
        self._profiles = self._load_all()

    def _load_all(self) -> dict[str, SkillProfile]:
        profiles: dict[str, SkillProfile] = {}
        for path in sorted(self.skills_dir.glob("*/SKILL.md")):
            raw = path.read_text(encoding="utf-8")
            metadata, content = self._split_frontmatter(raw, path)
            name = str(metadata.get("name") or path.parent.name)
            profiles[name] = SkillProfile(
                name=name,
                description=str(metadata.get("description", "")),
                content=content.strip(),
            )
        return profiles

    @staticmethod
    def _split_frontmatter(raw: str, path: Path) -> tuple[dict, str]:
        parts = raw.split("---", 2)
        if len(parts) != 3 or parts[0].strip():
            raise ValueError(f"Skill 文件缺少 YAML frontmatter: {path}")
        return yaml.safe_load(parts[1]) or {}, parts[2]

    def list_public(self) -> list[dict[str, str]]:
        with self._lock:
            return [
                {"name": item.name, "description": item.description}
                for item in self._profiles.values()
            ]

    def names(self) -> set[str]:
        with self._lock:
            return set(self._profiles)

    def get_public(self, name: str) -> dict[str, str]:
        with self._lock:
            try:
                item = self._profiles[name]
            except KeyError as error:
                raise ValueError(f"未知 Skill: {name}") from error
            return {
                "name": item.name,
                "description": item.description,
                "content": item.content,
            }

    def create(self, name: str, description: str, content: str) -> dict[str, str]:
        with self._lock:
            if name in self._profiles:
                raise FileExistsError(f"Skill 已存在: {name}")
            self._write(name, description, content)
            self._profiles = self._load_all()
        return self.get_public(name)

    def update(self, name: str, description: str, content: str) -> dict[str, str]:
        with self._lock:
            if name not in self._profiles:
                raise ValueError(f"未知 Skill: {name}")
            self._write(name, description, content)
            self._profiles = self._load_all()
        return self.get_public(name)

    # ── 项目级 Skill（存储在 project_skills 表）──

    def list_project(self, project_id: str) -> list[dict]:
        if not self._store:
            return []
        with self._store._connect() as conn:
            rows = conn.execute(
                "SELECT name, description FROM project_skills WHERE project_id = ? ORDER BY name",
                (project_id,),
            ).fetchall()
        return [{"name": r["name"], "description": r["description"]} for r in rows]

    def get_project(self, project_id: str, name: str) -> dict:
        if not self._store:
            raise ValueError(f"未知 Skill: {name}")
        with self._store._connect() as conn:
            row = conn.execute(
                "SELECT * FROM project_skills WHERE project_id = ? AND name = ?",
                (project_id, name),
            ).fetchone()
        if not row:
            raise ValueError(f"未知 Skill: {name}")
        return {"name": row["name"], "description": row["description"], "content": row["content"]}

    def create_project(self, project_id: str, name: str, description: str, content: str) -> dict:
        if not self._store:
            raise RuntimeError("Store not available")
        import uuid, json
        sid = uuid.uuid4().hex
        with self._store._connect() as conn:
            try:
                conn.execute(
                    "INSERT INTO project_skills(id, project_id, name, description, content) VALUES (?,?,?,?,?)",
                    (sid, project_id, name, description, content),
                )
            except Exception:
                raise FileExistsError(f"Skill 已存在: {name}")
        return self.get_project(project_id, name)

    def update_project(self, project_id: str, name: str, description: str, content: str) -> dict:
        if not self._store:
            raise RuntimeError("Store not available")
        with self._store._connect() as conn:
            cursor = conn.execute(
                "UPDATE project_skills SET description=?, content=?, updated_at=CURRENT_TIMESTAMP WHERE project_id=? AND name=?",
                (description, content, project_id, name),
            )
            if cursor.rowcount == 0:
                raise ValueError(f"未知 Skill: {name}")
        return self.get_project(project_id, name)

    def _write(self, name: str, description: str, content: str) -> None:
        directory = self.skills_dir / name
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "SKILL.md"
        temporary = directory / "SKILL.md.tmp"
        metadata = yaml.safe_dump(
            {"name": name, "description": description},
            allow_unicode=True,
            sort_keys=False,
        ).strip()
        temporary.write_text(f"---\n{metadata}\n---\n\n{content.strip()}\n", encoding="utf-8")
        temporary.replace(path)

