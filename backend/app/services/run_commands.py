"""解析聊天框斜杠命令，保持 Agent 定向与重试规则集中。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


DIRECT_AGENTS = {
    "/frontend": "frontend-agent",
    "/backend": "backend-agent",
    "/netty": "netty-agent",
}
# /agent 命令可用别名列表 — 实际 agent 名由项目配置决定
AGENT_ALIASES = {
    "frontend": "vue-frontend",
    "backend": "flask-backend",
    "netty": "springboot-netty",
    "rag": "rag",
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
        if not agent or not instruction.strip():
            raise ValueError("用法：/agent <agent名称> <指令>")
        # 先查别名，再直接用原名（支持项目自定义 agent）
        selected = AGENT_ALIASES.get(agent.lower(), agent)
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
