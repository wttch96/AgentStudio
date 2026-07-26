"""Claude Agent SDK 执行适配器。

本模块只负责“单个专业任务如何完成”。顶级任务依赖和并行关系由 LangGraph 管理。
"""

from __future__ import annotations

import asyncio
import json
import threading
from dataclasses import replace
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
    _MAX_TRANSIENT_RETRIES = 1
    _TRANSIENT_API_STATUSES = {408, 425, 429, 500, 502, 503, 504, 529}
    _TRANSIENT_ERROR_MARKERS = (
        "connection closed",
        "connection reset",
        "connection aborted",
        "mid-response",
        "unexpected eof",
        "broken pipe",
        "upstream",
        "overloaded",
        "rate limit",
        "temporarily unavailable",
        "请求中断",
        "连接中断",
        "连接重置",
        "上游服务",
        "暂时不可用",
    )

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
        interrupt_router: Any = None,
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
                project_id or "",
                interrupt_router=interrupt_router,
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
        project_id: str = "",
        interrupt_router: Any = None,
    ) -> AgentResult:
        profile = self.registry.get(project_id, task.agent)
        dependency_context = "\n".join(
            f"- {result.task_id}: {result.summary}" for result in dependency_results
        ) or "无前置任务"
        assigned_skills = ", ".join(profile.skills) or "无"
        from app.prompts.builder import PromptBuilder
        system_prompt = (
            PromptBuilder()
            .add_common_protocol()
            .add_role_prompt(profile.agent_type, profile)
            .add_system_prompt(profile)
            .build_system()
        )
        project_skill_context = self._project_skill_context(project_id, profile.skills)
        prompt = (
            f"任务 ID：{task.id}\n"
            f"用户选择的工作空间根目录：{workspace_root}\n"
            f"任务目标：{task.objective}\n"
            f"允许写入范围：{task.write_scope or ['只读']}\n"
            f"本 Agent 配置的项目 Skill：{assigned_skills}\n"
            f"项目 Skill 内容：\n{project_skill_context}\n"
            f"前置任务结果：\n{dependency_context}\n\n"
            "所有搜索和修改都以用户选择的工作空间为边界，不要默认操作 Agent Studio 自身。"
            "允许写入范围为空时必须严格只读；不为空时不得写出列出的相对路径前缀。"
            "需要专项规范时先通过 Skill 工具加载已配置 Skill。"
            "请自主使用工具完成任务，结束时简洁说明结果、修改文件和验证情况。"
        )
        # 提示词 + 系统提示词总长度
        prompt_chars = len(system_prompt) + len(prompt)

        options = ClaudeAgentOptions(
            model=self.settings.claude_model,
            system_prompt=system_prompt,
            cwd=str(workspace_root),
            # Skill 由 SDK 的 skills 选项按名称启用；不再依赖已弃用的裸
            # `allowed_tools=["Skill"]` 行为。其余工具仍遵循 Agent Markdown。
            allowed_tools=[tool for tool in profile.tools if tool != "Skill"],
            # Project skills are YAML under .workspace/<project>/skills and are
            # injected above. SDK-native .claude skills with the same names may
            # still be loaded when available.
            skills=[
                name for name in profile.skills
                if (self.settings.workspace_root / ".claude" / "skills" / name / "SKILL.md").is_file()
            ],
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
        result_api_status: int | None = None
        resume_session_id: str | None = None

        # 发送提示词大小事件，供前端统计 token
        self.events.emit(
            run_id, "agent.prompt",
            agent_id=task.agent, task_id=task.id,
            payload={"prompt_chars": prompt_chars, "system_prompt_chars": len(system_prompt)},
        )
        for attempt in range(self._MAX_TRANSIENT_RETRIES + 1):
            result_error = None
            result_subtype = None
            result_api_status = None
            attempt_text_start = len(text_parts)
            attempt_prompt = prompt
            attempt_options = options
            if attempt > 0:
                attempt_prompt = (
                    "上次响应因临时连接中断而未完整结束。请检查当前工作区状态，"
                    "从中断处继续完成原任务；不要重复已经完成的修改。"
                    "完成后请返回一份完整的最终结果与验证情况。"
                )
                attempt_options = replace(options, resume=resume_session_id)

            try:
                async with asyncio.timeout(timeout_seconds):
                    async for message in query(prompt=attempt_prompt, options=attempt_options):
                        if cancel_event.is_set():
                            return self._cancelled(task)
                        if interrupt_router and interrupt_router.is_task_aborted(run_id, task.id):
                            return self._cancelled(task)
                        # Per-agent pause check
                        if interrupt_router and interrupt_router.check_agent_paused(run_id, task.agent):
                            await self._wait_agent_resume(run_id, task.agent, interrupt_router, cancel_event)
                            if cancel_event.is_set():
                                return self._cancelled(task)
                        self._handle_message(run_id, task, message, text_parts, changed_files)
                        message_session_id = getattr(message, "session_id", None)
                        if message_session_id:
                            resume_session_id = message_session_id
                        if isinstance(message, ResultMessage):
                            if message.is_error:
                                result_subtype = message.subtype
                                result_api_status = message.api_error_status
                                result_error = self._result_error_detail(message, text_parts)
            except TimeoutError:
                return AgentResult(
                    task_id=task.id,
                    agent=task.agent,
                    status="failed",
                    summary="Agent 执行超时",
                    error=f"超过 {timeout_seconds} 秒",
                )
            except Exception as error:  # SDK 错误必须转成图状态，避免整轮并行回滚。
                # Claude CLI 会在 is_error ResultMessage 后以非零状态退出。SDK
                # 随后抛出的 “error result: success” 会丢掉真正的 API 错误，
                # 因此优先保留前面 ResultMessage/AssistantMessage 中提取的原因。
                result_error = (
                    result_error
                    or self._latest_api_error(text_parts[attempt_text_start:])
                )
                if result_error is None:
                    error_detail = f"{type(error).__name__}: {str(error) or repr(error)}"
                    return AgentResult(
                        task_id=task.id,
                        agent=task.agent,
                        status="failed",
                        summary="Claude Agent 执行失败",
                        error=error_detail,
                    )

            should_retry = (
                result_error is not None
                and attempt < self._MAX_TRANSIENT_RETRIES
                and resume_session_id is not None
                and self._is_transient_error(result_error, result_api_status)
            )
            if not should_retry:
                break

            # 错误文本已经作为事件发给前端，但不应混入恢复成功后的最终摘要。
            del text_parts[attempt_text_start:]
            self.events.emit(
                run_id,
                "agent.retrying",
                agent_id=task.agent,
                task_id=task.id,
                payload={
                    "attempt": attempt + 1,
                    "max_retries": self._MAX_TRANSIENT_RETRIES,
                    "reason": result_error,
                    "api_error_status": result_api_status,
                    "resume_session": True,
                },
            )
            await asyncio.sleep(0.5)

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
        structured = self._parse_structured_result(summary, task)
        if structured is not None:
            structured.changed_files = sorted(set(structured.changed_files) | changed_files)
            return structured
        return AgentResult(
            task_id=task.id,
            agent=task.agent,
            status="completed",
            summary=summary[-6000:],
            changed_files=sorted(changed_files),
        )

    @staticmethod
    def _latest_api_error(text_parts: list[str]) -> str | None:
        for text in reversed(text_parts):
            normalized = text.strip()
            if normalized.lower().startswith("api error:"):
                return normalized
        return None

    @classmethod
    def _result_error_detail(
        cls,
        message: ResultMessage,
        text_parts: list[str],
    ) -> str:
        if message.result and message.result.strip():
            return message.result.strip()
        errors = [str(error).strip() for error in (message.errors or []) if str(error).strip()]
        if errors:
            return "; ".join(errors)
        if latest := cls._latest_api_error(text_parts):
            return latest
        if message.api_error_status is not None:
            return f"Claude API HTTP {message.api_error_status}"
        if message.subtype == "success":
            return "Claude API 请求中断或上游服务返回异常"
        return message.subtype or "Claude Agent 未提供错误详情"

    @classmethod
    def _is_transient_error(
        cls,
        detail: str,
        api_error_status: int | None = None,
    ) -> bool:
        if api_error_status in cls._TRANSIENT_API_STATUSES:
            return True
        normalized = detail.lower()
        return any(marker in normalized for marker in cls._TRANSIENT_ERROR_MARKERS)

    @staticmethod
    def _parse_structured_result(text: str, task: DagTask) -> AgentResult | None:
        """Parse the final JSON object when an Agent follows the shared protocol."""
        start, end = text.rfind("{"), text.rfind("}")
        if start < 0 or end <= start:
            return None
        # Prefer a fenced or trailing JSON object, but gracefully retain legacy text.
        candidates = [text[start:end + 1]]
        first = text.find("{")
        if first != start:
            candidates.append(text[first:end + 1])
        for raw in candidates:
            try:
                data = json.loads(raw)
                if not isinstance(data, dict) or "status" not in data:
                    continue
                data.setdefault("task_id", task.id)
                data.setdefault("agent", task.agent)
                data.setdefault("summary", text[:6000])
                if "changes" in data and "changed_files" not in data:
                    data["changed_files"] = data.pop("changes")
                if "dependencies" in data and "dependencies_discovered" not in data:
                    data["dependencies_discovered"] = data.pop("dependencies")
                verification = data.pop("verification", None)
                if isinstance(verification, dict):
                    data.setdefault("verification_performed", verification.get("performed", []))
                    data.setdefault("verification_not_performed", verification.get("not_performed", []))
                    data.setdefault("verification_result", verification.get("result", "not_run"))
                return AgentResult.model_validate(data)
            except Exception:
                continue
        return None

    def _project_skill_context(self, project_id: str, skill_names: tuple[str, ...]) -> str:
        if not project_id or not skill_names or not self.registry.config_reader:
            return "无"
        reader = self.registry.config_reader.for_project(project_id)
        sections: list[str] = []
        for name in skill_names:
            try:
                skill = reader.get_skill(name)
            except (FileNotFoundError, ValueError):
                continue
            sections.append(
                f"### {name}\n{str(skill.get('content', ''))[:12000]}"
            )
        return "\n\n".join(sections) or "无"

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
            raw_usage = getattr(message, "usage", None)
            raw_model = getattr(message, "model_usage", None)
            # 直接传递 SDK 原始 token 数据
            usage_payload = {
                "duration_ms": getattr(message, "duration_ms", None),
                "cost_usd": getattr(message, "total_cost_usd", None),
                "is_error": getattr(message, "is_error", False),
                "subtype": getattr(message, "subtype", None),
                "api_error_status": getattr(message, "api_error_status", None),
                "terminal_reason": getattr(message, "terminal_reason", None),
                "stop_reason": getattr(message, "stop_reason", None),
                "errors": getattr(message, "errors", None) or [],
            }
            if isinstance(raw_usage, dict):
                usage_payload["input_tokens"] = (
                    raw_usage.get("input_tokens", 0)
                    or raw_usage.get("cache_read_input_tokens", 0)
                    or raw_usage.get("cache_creation_input_tokens", 0)
                )
                usage_payload["output_tokens"] = raw_usage.get("output_tokens", 0)
            self.events.emit(
                run_id,
                "agent.usage",
                agent_id=task.agent,
                task_id=task.id,
                payload=usage_payload,
            )

    def _execute_demo(
        self, run_id: str, task: DagTask, cancel_event: threading.Event
    ) -> AgentResult:
        """用短暂、可观察的模拟步骤验证 UI，不读写用户代码。"""

        import time

        profile = self.registry.get("", task.agent)
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
            artifacts=[{
                "type": "report",
                "path_or_id": f"demo:{task.id}",
                "description": "演示模式执行报告",
            }],
            verification_performed=["演示执行链路验证"],
            verification_result="passed",
        )

    @staticmethod
    def _cancelled(task: DagTask) -> AgentResult:
        return AgentResult(
            task_id=task.id,
            agent=task.agent,
            status="cancelled",
            summary="任务已按用户请求取消",
        )

    @staticmethod
    async def _wait_agent_resume(
        run_id: str,
        agent_id: str,
        interrupt_router: Any,
        cancel_event: threading.Event,
        poll_interval: float = 1.0,
    ) -> None:
        """Async wait until agent pause is cleared or run is cancelled."""
        import asyncio as _asyncio
        while not cancel_event.is_set() and interrupt_router.check_agent_paused(run_id, agent_id):
            await _asyncio.sleep(poll_interval)
