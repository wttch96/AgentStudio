"""Claude Agent SDK 执行适配器。

本模块只负责“单个专业任务如何完成”。顶级任务依赖和并行关系由 LangGraph 管理。
"""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
    query,
)

from app.agents.registry import AgentRegistry
from app.config import Settings
from app.domain.models import AgentResult, DagTask
from app.events.publisher import EventPublisher


class ClaudeAgentExecutor:
    def __init__(
        self,
        settings: Settings,
        registry: AgentRegistry,
        events: EventPublisher,
    ) -> None:
        self.settings = settings
        self.registry = registry
        self.events = events

    def execute(
        self,
        run_id: str,
        task: DagTask,
        dependency_results: list[AgentResult],
        cancel_event: threading.Event,
        workspace_root: str,
        max_turns: int | None = None,
        timeout_seconds: int | None = None,
        project_id: str | None = None,
    ) -> AgentResult:
        if cancel_event.is_set():
            return self._cancelled(task)
        if not self.settings.claude_configured:
            return self._execute_demo(run_id, task, cancel_event)
        return asyncio.run(
            self._execute_live(
                run_id,
                task,
                dependency_results,
                cancel_event,
                Path(workspace_root),
                max_turns or self.settings.agent_max_turns,
                timeout_seconds or self.settings.agent_timeout_seconds,
            )
        )

    async def _execute_live(
        self,
        run_id: str,
        task: DagTask,
        dependency_results: list[AgentResult],
        cancel_event: threading.Event,
        workspace_root: Path,
        max_turns: int,
        timeout_seconds: int,
    ) -> AgentResult:
        profile = self.registry.get(project_id or "", task.agent)
        dependency_context = "\n".join(
            f"- {result.task_id}: {result.summary}" for result in dependency_results
        ) or "无前置任务"
        assigned_skills = ", ".join(profile.skills) or "无"
        prompt = (
            f"任务 ID：{task.id}\n"
            f"用户选择的工作空间根目录：{workspace_root}\n"
            f"任务目标：{task.objective}\n"
            f"允许写入范围：{task.write_scope or ['只读']}\n"
            f"本 Agent 配置的项目 Skill：{assigned_skills}\n"
            f"前置任务结果：\n{dependency_context}\n\n"
            "所有搜索和修改都以用户选择的工作空间为边界，不要默认操作 Agent Studio 自身。"
            "允许写入范围为空时必须严格只读；不为空时不得写出列出的相对路径前缀。"
            "需要专项规范时先通过 Skill 工具加载已配置 Skill。"
            "请自主使用工具完成任务，结束时简洁说明结果、修改文件和验证情况。"
        )

        options = ClaudeAgentOptions(
            model=self.settings.claude_model,
            system_prompt=profile.prompt,
            cwd=str(workspace_root),
            # Skill 由 SDK 的 skills 选项按名称启用；不再依赖已弃用的裸
            # `allowed_tools=["Skill"]` 行为。其余工具仍遵循 Agent Markdown。
            allowed_tools=[tool for tool in profile.tools if tool != "Skill"],
            skills=list(profile.skills),
            # cwd 指向用户选择的代码项目；额外加入 Agent Studio 根目录，
            # 让 SDK 仍能发现由配置中心维护的 .claude/skills。
            add_dirs=[self.settings.workspace_root],
            max_turns=max_turns,
            setting_sources=["project"],
        )
        text_parts: list[str] = []
        changed_files: set[str] = set()
        result_error: str | None = None
        result_subtype: str | None = None

        try:
            async with asyncio.timeout(timeout_seconds):
                async for message in query(prompt=prompt, options=options):
                    if cancel_event.is_set():
                        return self._cancelled(task)
                    self._handle_message(run_id, task, message, text_parts, changed_files)
                    if isinstance(message, ResultMessage) and message.is_error:
                        result_subtype = message.subtype
                        result_error = (
                            message.result
                            or "; ".join(message.errors or [])
                            or message.subtype
                        )
        except TimeoutError:
            return AgentResult(
                task_id=task.id,
                agent=task.agent,
                status="failed",
                summary="Agent 执行超时",
                error=f"超过 {timeout_seconds} 秒",
            )
        except Exception as error:  # SDK 错误必须转成图状态，避免整轮并行回滚。
            error_detail = f"{type(error).__name__}: {str(error) or repr(error)}"
            return AgentResult(
                task_id=task.id,
                agent=task.agent,
                status="failed",
                summary="Claude Agent 执行失败",
                error=error_detail,
            )

        if result_error:
            reached_turn_limit = result_subtype == "error_max_turns" or "max_turn" in result_error
            summary = (
                f"Claude Agent 达到最大交互轮次限制（{max_turns} 次），任务未完成。"
                if reached_turn_limit
                else "Claude Agent SDK 返回执行错误，任务未完成。"
            )
            return AgentResult(
                task_id=task.id,
                agent=task.agent,
                status="failed",
                summary=summary,
                changed_files=sorted(changed_files),
                error=result_error,
            )

        summary = "\n".join(text_parts).strip() or "Agent 已完成，但没有返回文本摘要。"
        return AgentResult(
            task_id=task.id,
            agent=task.agent,
            status="completed",
            summary=summary[-6000:],
            changed_files=sorted(changed_files),
        )

    def _handle_message(
        self,
        run_id: str,
        task: DagTask,
        message: Any,
        text_parts: list[str],
        changed_files: set[str],
    ) -> None:
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    text_parts.append(block.text)
                    self.events.emit(
                        run_id,
                        "agent.message",
                        agent_id=task.agent,
                        task_id=task.id,
                        payload={"text": block.text},
                    )
                elif isinstance(block, ToolUseBlock):
                    tool_input = block.input if isinstance(block.input, dict) else {}
                    file_path = tool_input.get("file_path") or tool_input.get("path")
                    if block.name in {"Write", "Edit", "MultiEdit"} and file_path:
                        changed_files.add(str(file_path))
                    event_type = "skill.loaded" if block.name == "Skill" else "tool.started"
                    payload = {"tool": block.name, "input": tool_input}
                    if block.name == "Skill":
                        payload["skill"] = (
                            tool_input.get("skill")
                            or tool_input.get("name")
                            or "unknown"
                        )
                    self.events.emit(
                        run_id,
                        event_type,
                        agent_id=task.agent,
                        task_id=task.id,
                        payload=payload,
                    )
        elif isinstance(message, ResultMessage):
            self.events.emit(
                run_id,
                "agent.usage",
                agent_id=task.agent,
                task_id=task.id,
                payload={
                    "duration_ms": getattr(message, "duration_ms", None),
                    "cost_usd": getattr(message, "total_cost_usd", None),
                    "is_error": getattr(message, "is_error", False),
                },
            )

    def _execute_demo(
        self, run_id: str, task: DagTask, cancel_event: threading.Event
    ) -> AgentResult:
        """用短暂、可观察的模拟步骤验证 UI，不读写用户代码。"""

        import time

        profile = self.registry.get(project_id or "", task.agent)
        steps = [
            ("tool.started", {"tool": "Read", "summary": "检查相关目录和约束"}),
        ]
        steps.extend(
            (
                "skill.loaded",
                {"skill": skill, "summary": f"加载项目 Skill：{skill}"},
            )
            for skill in profile.skills
        )
        steps.append(("agent.message", {"text": f"正在处理：{task.title}"}))
        for event_type, payload in steps:
            if cancel_event.is_set():
                return self._cancelled(task)
            self.events.emit(
                run_id,
                event_type,
                agent_id=task.agent,
                task_id=task.id,
                payload=payload,
            )
            time.sleep(0.35)

        return AgentResult(
            task_id=task.id,
            agent=task.agent,
            status="completed",
            summary=f"演示模式：{task.agent} 已完成“{task.title}”。配置密钥后会执行真实任务。",
        )

    @staticmethod
    def _cancelled(task: DagTask) -> AgentResult:
        return AgentResult(
            task_id=task.id,
            agent=task.agent,
            status="cancelled",
            summary="任务已按用户请求取消",
        )
