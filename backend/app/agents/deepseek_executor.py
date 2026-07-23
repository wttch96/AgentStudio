"""DeepSeek LangChain Agent 执行适配器。

通过 LangChain 的 create_agent + ChatOpenAI 驱动 DeepSeek API，
提供与 ClaudeAgentExecutor 一致的工具调用和事件发送接口。
当 Claude API Key 不可用时，此 executor 作为备选编码 Agent。
"""

from __future__ import annotations

import asyncio
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from langchain.agents import create_agent
from langchain_openai import ChatOpenAI

from app.agents.registry import AgentRegistry, AgentProfile
from app.config import Settings
from app.domain.models import AgentResult, DagTask
from app.events.publisher import EventPublisher


def _build_tools(profile: AgentProfile, workspace_root: Path, events: EventPublisher,
                 run_id: str, task: DagTask) -> list:
    """根据 AgentProfile 中的工具名构建 LangChain tools (callable format)。"""
    built: list = []

    for tool_name in profile.tools:
        if tool_name == "Read":
            def read_file(file_path: str) -> str:
                """Read a file from the workspace."""
                full = (workspace_root / file_path).resolve()
                if not str(full).startswith(str(workspace_root)):
                    return f"Error: path {file_path} is outside workspace"
                try:
                    return full.read_text(encoding="utf-8")[:8000]
                except Exception as e:
                    return f"Error reading {file_path}: {e}"
            read_file.__name__ = "Read"
            built.append(read_file)
        elif tool_name == "Write":
            def write_file(file_path: str, content: str) -> str:
                """Write content to a file in the workspace."""
                full = (workspace_root / file_path).resolve()
                if not str(full).startswith(str(workspace_root)):
                    return f"Error: path {file_path} is outside workspace"
                full.parent.mkdir(parents=True, exist_ok=True)
                full.write_text(content, encoding="utf-8")
                return f"Written: {file_path}"
            write_file.__name__ = "Write"
            built.append(write_file)
        elif tool_name == "Edit":
            def edit_file(file_path: str, old_string: str, new_string: str) -> str:
                """Replace text in a file in the workspace."""
                full = (workspace_root / file_path).resolve()
                if not str(full).startswith(str(workspace_root)):
                    return f"Error: path {file_path} is outside workspace"
                content = full.read_text(encoding="utf-8")
                if old_string not in content:
                    return f"Error: old_string not found in {file_path}"
                full.write_text(content.replace(old_string, new_string, 1), encoding="utf-8")
                return f"Edited: {file_path}"
            edit_file.__name__ = "Edit"
            built.append(edit_file)
        elif tool_name == "Glob":
            def glob_files(pattern: str) -> str:
                """List files matching a glob pattern in the workspace."""
                matches = list(workspace_root.glob(pattern))
                return "\n".join(str(m.relative_to(workspace_root)) for m in matches[:50])
            glob_files.__name__ = "Glob"
            built.append(glob_files)
        elif tool_name == "Grep":
            def grep_search(pattern: str) -> str:
                """Search for a pattern in workspace files (basic grep)."""
                try:
                    result = subprocess.run(
                        ["grep", "-rn", "--include=*.py", "--include=*.ts", "--include=*.vue",
                         "--include=*.md", "--include=*.json", "--include=*.yaml", "--include=*.yml",
                         pattern, str(workspace_root)],
                        capture_output=True, text=True, timeout=30,
                    )
                    return result.stdout[:8000] or "No matches"
                except Exception as e:
                    return f"Grep error: {e}"
            grep_search.__name__ = "Grep"
            built.append(grep_search)
        elif tool_name == "Bash":
            def run_bash(command: str) -> str:
                """Run a bash command in the workspace directory."""
                try:
                    result = subprocess.run(
                        command, shell=True, capture_output=True, text=True,
                        cwd=str(workspace_root), timeout=120,
                    )
                    output = result.stdout[:4000]
                    if result.stderr:
                        output += "\n[stderr]: " + result.stderr[:2000]
                    return output or "(no output)"
                except Exception as e:
                    return f"Bash error: {e}"
            run_bash.__name__ = "Bash"
            built.append(run_bash)
    return built


class DeepSeekAgentExecutor:
    """基于 LangChain create_agent + DeepSeek 的 Agent 执行器。"""

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
        if not self.settings.deepseek_api_key:
            return AgentResult(
                task_id=task.id, agent=task.agent, status="failed",
                summary="DeepSeek API Key 未配置",
            )
        return asyncio.run(
            self._execute_live(
                run_id, task, dependency_results, cancel_event,
                Path(workspace_root),
                max_turns or self.settings.agent_max_turns,
                timeout_seconds or self.settings.agent_timeout_seconds,
                project_id or "",
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
        project_id: str,
    ) -> AgentResult:
        profile = self.registry.get(project_id, task.agent)
        dep_context = "\n".join(
            f"- {r.task_id}: {r.summary}" for r in dependency_results
        ) or "无前置任务"
        assigned_skills = ", ".join(profile.skills) or "无"

        system_prompt = (
            f"{profile.prompt}\n\n"
            f"工作空间根目录：{workspace_root}\n"
            f"本 Agent 配置的项目 Skill：{assigned_skills}\n"
            "所有文件操作以工作空间为边界。请自主使用工具完成任务，结束时简洁说明结果。"
        )
        task_prompt = (
            f"任务 ID：{task.id}\n任务目标：{task.objective}\n"
            f"允许写入范围：{task.write_scope or ['只读']}\n"
            f"前置任务结果：\n{dep_context}"
        )

        tools = _build_tools(profile, workspace_root, self.events, run_id, task)

        llm = ChatOpenAI(
            model=self.settings.deepseek_model,
            api_key=self.settings.deepseek_api_key,
            base_url=self.settings.deepseek_base_url,
            temperature=0.1,
        )

        agent = create_agent(
            model=llm,
            tools=tools,
            system_prompt=system_prompt,
        )

        prompt_chars = len(system_prompt) + len(task_prompt) + len(str(profile.prompt))
        self.events.emit(
            run_id, "agent.prompt",
            agent_id=task.agent, task_id=task.id,
            payload={"prompt_chars": prompt_chars, "system_prompt_chars": len(str(profile.prompt))},
        )
        started_at = datetime.now(timezone.utc).isoformat()
        self.events.emit(
            run_id, "agent.started",
            agent_id=task.agent, task_id=task.id,
            payload={"title": task.title, "objective": task.objective, "started_at": started_at},
        )

        try:
            async with asyncio.timeout(timeout_seconds):
                result = await agent.ainvoke({
                    "messages": [{"role": "user", "content": task_prompt}],
                })
            # extract final response from agent state
            messages = result.get("messages", [])
            output = ""
            for msg in reversed(messages):
                if hasattr(msg, "content") and msg.type == "ai":
                    output = str(msg.content) if msg.content else ""
                    if output:
                        break
            if not output and hasattr(result, "get"):
                output = str(result.get("output", ""))
            self.events.emit(
                run_id, "agent.message",
                agent_id=task.agent, task_id=task.id,
                payload={"text": output},
            )
            return AgentResult(
                task_id=task.id, agent=task.agent, status="completed",
                summary=output[:6000] or "Agent 已完成，但没有返回文本摘要。",
            )
        except TimeoutError:
            return AgentResult(
                task_id=task.id, agent=task.agent, status="failed",
                summary="DeepSeek Agent 执行超时",
                error=f"超过 {timeout_seconds} 秒",
            )
        except Exception as error:
            error_detail = f"{type(error).__name__}: {str(error) or repr(error)}"
            self.events.emit(
                run_id, "agent.message",
                agent_id=task.agent, task_id=task.id,
                payload={"text": error_detail},
            )
            return AgentResult(
                task_id=task.id, agent=task.agent, status="failed",
                summary="DeepSeek Agent 执行失败",
                error=error_detail,
            )

    @staticmethod
    def _cancelled(task: DagTask) -> AgentResult:
        return AgentResult(
            task_id=task.id, agent=task.agent, status="cancelled",
            summary="任务已按用户请求取消",
        )
