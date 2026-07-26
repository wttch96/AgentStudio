"""解析统一的主脑/Agent 定向命令。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class RunCommand:
    kind: Literal["normal", "direct"]
    instruction: str
    agent: str | None = None


def parse_run_command(value: str) -> RunCommand:
    text = value.strip()
    if not text.startswith("/"):
        return RunCommand("normal", text)

    command, _, remainder = text.partition(" ")
    command = command.lower()
    remainder = remainder.strip()

    if not remainder:
        raise ValueError(f"{command} 后需要填写引导内容")
    target = command[1:]
    if target == "brain":
        return RunCommand("normal", remainder)
    if not target or target.startswith("+"):
        raise ValueError("只支持 /brain 或 /<agent-name> <指令>")
    return RunCommand("direct", remainder, agent=target)
