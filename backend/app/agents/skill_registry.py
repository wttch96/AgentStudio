"""项目级 Claude Skill 的读取、创建和更新服务。

公共 Skill：.claude/skills/<name>/SKILL.md
项目 Skill：.workspace/.agent-studio/skills/<name>.yaml
Skill 模板：templates/skills/<name>.yaml
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any

import yaml


@dataclass(frozen=True, slots=True)
class SkillProfile:
    name: str
    description: str
    content: str


class SkillRegistry:
    def __init__(self, skills_dir: Path, config_reader: Any = None) -> None:
        self.skills_dir = skills_dir
        self.skills_dir.mkdir(parents=True, exist_ok=True)
        self._config_reader = config_reader
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

    # ── 公共 Skill（.claude/skills/）──

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

    # ── 项目级 Skill（.workspace/.agent-studio/skills/*.yaml）──

    def list_project(self, project_id: str) -> list[dict]:
        """列出项目 Skill（文件优先）。"""
        if self._config_reader:
            return self._config_reader.list_skills()
        return []

    def get_project(self, project_id: str, name: str) -> dict:
        """获取单个项目 Skill。"""
        if self._config_reader:
            return self._config_reader.get_skill(name)
        raise ValueError(f"未知 Skill: {name}")

    def create_project(self, project_id: str, name: str, description: str, content: str) -> dict:
        """创建项目 Skill 为 YAML 文件。"""
        if not self._config_reader:
            raise RuntimeError("ConfigReader not available")
        existing = self._config_reader.list_skills()
        if any(s.get("name") == name for s in existing):
            raise FileExistsError(f"Skill 已存在: {name}")
        self._config_reader.save_skill(name, {
            "name": name,
            "description": description,
            "content": content,
        })
        return self._config_reader.get_skill(name)

    def update_project(self, project_id: str, name: str, description: str, content: str) -> dict:
        """更新项目 Skill YAML 文件。"""
        if not self._config_reader:
            raise RuntimeError("ConfigReader not available")
        try:
            self._config_reader.get_skill(name)
        except FileNotFoundError:
            raise ValueError(f"未知 Skill: {name}")
        self._config_reader.save_skill(name, {
            "name": name,
            "description": description,
            "content": content,
        })
        return self._config_reader.get_skill(name)

    # ── Skill 模板（templates/skills/*.yaml）──

    def list_templates(self) -> list[dict[str, Any]]:
        """从 templates/skills/ 目录列出 Skill 模板。"""
        tmpl_dir = self.skills_dir.parent.parent.parent / "templates" / "skills"
        if not tmpl_dir.is_dir():
            return []
        templates = []
        for f in sorted(tmpl_dir.glob("*.yaml")):
            try:
                data = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
                if "name" not in data:
                    data["name"] = f.stem
                templates.append(data)
            except Exception:
                pass
        return templates

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
