"""加载根目录 agents/*.md 中的专业 Agent 定义。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from threading import RLock

import yaml


@dataclass(frozen=True, slots=True)
class AgentProfile:
    name: str
    description: str
    tools: tuple[str, ...]
    skills: tuple[str, ...]
    prompt: str


class AgentRegistry:
    def __init__(self, definitions_dir: Path) -> None:
        self.definitions_dir = definitions_dir
        self._lock = RLock()
        self._profiles = self._load_all()

    def _load_all(self) -> dict[str, AgentProfile]:
        profiles: dict[str, AgentProfile] = {}
        for path in sorted(self.definitions_dir.glob("*.md")):
            raw = path.read_text(encoding="utf-8")
            metadata, prompt = self._split_frontmatter(raw, path)
            profile = AgentProfile(
                name=str(metadata["name"]),
                description=str(metadata.get("description", "")),
                tools=tuple(metadata.get("tools", [])),
                skills=tuple(metadata.get("skills", [])),
                prompt=prompt.strip(),
            )
            profiles[profile.name] = profile
        if not profiles:
            raise RuntimeError(f"没有在 {self.definitions_dir} 找到 Agent 定义")
        return profiles

    @staticmethod
    def _split_frontmatter(raw: str, path: Path) -> tuple[dict, str]:
        parts = raw.split("---", 2)
        if len(parts) != 3 or parts[0].strip():
            raise ValueError(f"Agent 文件缺少 YAML frontmatter: {path}")
        metadata = yaml.safe_load(parts[1]) or {}
        if "name" not in metadata:
            raise ValueError(f"Agent 文件缺少 name: {path}")
        return metadata, parts[2]

    def get(self, name: str) -> AgentProfile:
        with self._lock:
            try:
                return self._profiles[name]
            except KeyError as error:
                raise ValueError(f"未知 Agent: {name}") from error

    def list_public(self) -> list[dict[str, object]]:
        with self._lock:
            return [
                {
                    "name": profile.name,
                    "description": profile.description,
                    "tools": list(profile.tools),
                    "skills": list(profile.skills),
                    "skill_count": len(profile.skills),
                    "builtin": True,
                }
                for profile in self._profiles.values()
            ]

    def get_public(self, name: str) -> dict[str, object]:
        profile = self.get(name)
        return {
            "name": profile.name,
            "description": profile.description,
            "tools": list(profile.tools),
            "skills": list(profile.skills),
            "skill_count": len(profile.skills),
            "builtin": True,
            "prompt": profile.prompt,
        }

    def update(
        self,
        name: str,
        *,
        description: str,
        tools: list[str],
        skills: list[str],
        prompt: str,
    ) -> dict[str, object]:
        """更新已有 Agent；name 固定，避免绕过代码中的允许角色集合。"""

        with self._lock:
            self.get(name)
            path = self.definitions_dir / f"{name}.md"
            metadata = {
                "name": name,
                "description": description,
                "tools": tools,
                "skills": skills,
            }
            self._atomic_write(path, metadata, prompt)
            self._profiles = self._load_all()
        return self.get_public(name)

    @staticmethod
    def _atomic_write(path: Path, metadata: dict, body: str) -> None:
        temporary = path.with_suffix(".md.tmp")
        frontmatter = yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False).strip()
        temporary.write_text(f"---\n{frontmatter}\n---\n\n{body.strip()}\n", encoding="utf-8")
        temporary.replace(path)
