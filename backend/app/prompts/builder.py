"""可组合的 Agent 提示词构建器。"""

from __future__ import annotations

import json
from typing import Any

from app.agents.registry import AgentProfile
from app.domain.models import AgentResult, DagTask


class PromptBuilder:
    """通过组合独立区块来构建 Agent 提示词。

    用法::

        builder = PromptBuilder()
        builder.add_system_prompt(profile)
        builder.add_common_protocol()
        builder.add_role_prompt("claude")
        builder.add_board_context(board_data)
        builder.add_dependency_context(results)
        system = builder.build_system()
        task_prompt = builder.build_task(task, workspace_root)
    """

    def __init__(self) -> None:
        self._system_sections: list[tuple[str, str]] = []
        self._task_sections: list[tuple[str, str]] = []

    # ── 系统提示词区块 ──────────────────────────────────────────────

    def add_system_prompt(self, profile: AgentProfile) -> "PromptBuilder":
        """Agent 自有 system_prompt。"""
        self._system_sections.append(("agent_system_prompt", profile.prompt))
        return self

    def add_common_protocol(self) -> "PromptBuilder":
        """所有 Agent 共享的协作协议。"""
        from app.prompts.common_protocol import COMMON_PROTOCOL
        self._system_sections.append(("common_protocol", COMMON_PROTOCOL))
        return self

    def add_role_prompt(self, agent_type: str, profile: AgentProfile | None = None) -> "PromptBuilder":
        """根据 agent_type 注入角色 Prompt。"""
        from app.prompts.roles import ROLE_PROMPTS
        role = ROLE_PROMPTS.get(agent_type, ROLE_PROMPTS.get("claude", ""))
        if role:
            # 注入 Agent 的能力和限制信息
            caps = ""
            if profile:
                if profile.capabilities:
                    caps += f"\n你的能力领域: {', '.join(profile.capabilities)}"
                if profile.limitations:
                    caps += f"\n你的明确限制: {', '.join(profile.limitations)}"
                if profile.forbidden_tasks:
                    caps += f"\n绝对禁止的任务: {', '.join(profile.forbidden_tasks)}"
            self._system_sections.append(("role_prompt", role + caps))
        return self

    def add_output_schema(self, schema_desc: str) -> "PromptBuilder":
        """期望的输出结构。"""
        self._system_sections.append(("output_schema", f"## 期望输出格式\n{schema_desc}"))
        return self

    # ── 任务上下文区块 ──────────────────────────────────────────────

    def add_task_context(self, task: DagTask, workspace_root: str) -> "PromptBuilder":
        """当前任务定义。"""
        ctx = (
            f"<current_task>\n"
            f"  任务 ID: {task.id}\n"
            f"  任务标题: {task.title}\n"
            f"  任务目标: {task.objective}\n"
            f"  工作空间: {workspace_root}\n"
            f"  写入范围: {task.write_scope or '只读'}\n"
            f"</current_task>"
        )
        self._task_sections.append(("current_task", ctx))
        return self

    def add_board_context(self, board_data: dict[str, Any]) -> "PromptBuilder":
        """当前看板状态。"""
        if board_data:
            compact = {}
            for k, v in board_data.items():
                if k == "all_results":
                    compact["all_results"] = v
                elif k.startswith("result:") or k.startswith("review:"):
                    if isinstance(v, dict):
                        compact[k] = {
                            "status": v.get("status", "?"),
                            "summary": str(v.get("summary", ""))[:200],
                        }
                    elif isinstance(v, str):
                        compact[k] = v[:300]
                    else:
                        compact[k] = str(v)[:300]
                elif isinstance(v, (str, int, float, bool)):
                    compact[k] = v
            ctx = (
                f"<board_context>\n"
                f"  看板共享状态（精简）:\n"
                f"{json.dumps(compact, ensure_ascii=False, indent=2)}\n"
                f"  注意: 这是当前已知事实的唯一来源。所有 Agent 共享此看板。\n"
                f"  开始任务前先检查相关 key，完成任务后更新对应状态。\n"
                f"</board_context>"
            )
            self._task_sections.append(("board_context", ctx))
        return self

    def add_dependency_context(self, dep_results: list[AgentResult]) -> "PromptBuilder":
        """上游依赖结果。"""
        if dep_results:
            parts = []
            for r in dep_results:
                summary_short = r.summary[:300] if r.summary else "(无摘要)"
                icon = "✓" if r.status == "completed" else "✗" if r.status == "failed" else "-"
                parts.append(f"  {icon} [{r.task_id}] {r.agent}: {summary_short}")
            ctx = (
                f"<upstream_results>\n"
                f"  上游任务执行结果:\n"
                + "\n".join(parts) +
                f"\n</upstream_results>"
            )
            self._task_sections.append(("upstream_results", ctx))
        else:
            self._task_sections.append(("upstream_results", "<upstream_results>\n  无上游依赖\n</upstream_results>"))
        return self

    def add_coordination_contract(self, contract: str) -> "PromptBuilder":
        """跨 Agent 协调契约。"""
        if contract:
            ctx = (
                f"<coordination_contract>\n"
                f"  跨 Agent 共享契约（如 API 契约、数据模型等）：\n"
                f"{contract}\n"
                f"  不得单方面修改以上契约。如需变更，向主脑提出。\n"
                f"</coordination_contract>"
            )
            self._task_sections.append(("coordination_contract", ctx))
        return self

    def add_structured_output_instructions(self) -> "PromptBuilder":
        """添加结构化输出的格式要求。"""
        ctx = (
            "<output_schema>\n"
            "  请以 JSON 格式输出最终结果，包含以下字段:\n"
            "  {\n"
            "    \"status\": \"completed|partially_completed|blocked|failed|need_review\",\n"
            "    \"summary\": \"执行摘要\",\n"
            "    \"artifacts\": [{\"type\": \"file|blackboard_key|report\", \"path_or_id\": \"...\", \"description\": \"...\"}],\n"
            "    \"changes\": [\"修改的文件路径\"],\n"
            "    \"decisions\": [{\"decision\": \"决策\", \"reason\": \"理由\"}],\n"
            "    \"risks\": [\"识别的风险\"],\n"
            "    \"verification_performed\": [\"已执行的验证\"],\n"
            "    \"next_actions\": [\"建议的后续步骤\"]\n"
            "  }\n"
            "  如果无法输出 JSON，请在 summary 中说明原因。\n"
            "</output_schema>"
        )
        self._task_sections.append(("output_schema", ctx))
        return self

    # ── 构建 ────────────────────────────────────────────────────────

    def build_system(self) -> str:
        """组合所有系统级别的区块。"""
        parts = []
        for label, content in self._system_sections:
            parts.append(content)
        return "\n\n".join(parts)

    def build_task(self) -> str:
        """组合所有任务级别的区块。"""
        parts = []
        for label, content in self._task_sections:
            parts.append(content)
        combined = "\n\n".join(parts)
        combined += (
            "\n\n---\n"
            "请自主使用工具完成任务。结束时简洁说明结果、修改文件和验证情况。\n"
            "如果你完成了任务，必须确保以上 output_schema 中要求的检查项均已执行。\n"
            "不要声称执行了未实际执行的操作。不要编造文件、结果或验证通过结论。"
        )
        return combined
