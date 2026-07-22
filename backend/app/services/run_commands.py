"""解析聊天框斜杠命令，保持 Agent 定向与重试规则集中。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


DIRECT_AGENTS = {
    "/frontend": "frontend-agent",
    "/backend": "backend-agent",
    "/netty": "netty-agent",
}
AGENT_SCOPES = {
    "frontend-agent": ["frontend/"],
    "backend-agent": ["backend/"],
    "netty-agent": ["netty/"],
}


@dataclass(frozen=True, slots=True)
class RunCommand:
    kind: Literal["normal", "direct", "retry"]
    instruction: str
    agent: str | None = None
    task_id: str | None = None


def parse_run_command(value: str) -> RunCommand:
    text = value.strip()
    if not text.startswith("/"):
        return RunCommand("normal", text)

    command, _, remainder = text.partition(" ")
    command = command.lower()
    remainder = remainder.strip()
    if command in DIRECT_AGENTS:
        if not remainder:
            raise ValueError(f"{command} 后需要填写给 Agent 的指令")
        return RunCommand("direct", remainder, agent=DIRECT_AGENTS[command])

    if command == "/agent":
        agent, _, instruction = remainder.partition(" ")
        aliases = {
            "frontend": "frontend-agent",
            "backend": "backend-agent",
            "netty": "netty-agent",
            **{name: name for name in AGENT_SCOPES},
        }
        selected = aliases.get(agent.lower())
        if not selected or not instruction.strip():
            raise ValueError("用法：/agent <frontend|backend|netty> <指令>")
        return RunCommand("direct", instruction.strip(), agent=selected)

    if command == "/retry":
        task_id = remainder.split(maxsplit=1)[0] if remainder else ""
        if not task_id:
            raise ValueError("用法：/retry <失败的 task-id>")
        return RunCommand("retry", text, task_id=task_id)

    if command == "/help":
        raise ValueError(
            "可用命令：/frontend <指令>、/backend <指令>、/netty <指令>、"
            "/agent <Agent> <指令>、/retry <task-id>"
        )
    raise ValueError(f"未知命令：{command}。输入 /help 查看可用命令")
