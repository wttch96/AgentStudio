"""纯文件操作 Agent —— 基于 LangChain DeepSeek + FileManagementToolkit。

提供 copy/move/delete/read/write/list/search 等标准文件操作，
通过 DeepSeek 推理自主组合工具完成任务。
工具记录、事件发送等接口与现有 ClaudeAgentExecutor 完全一致。
"""

from __future__ import annotations

import asyncio
import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from langchain.agents import create_agent
from langchain_openai import ChatOpenAI
from langchain_community.agent_toolkits.file_management.toolkit import FileManagementToolkit

from app.agents.registry import AgentRegistry
from app.config import Settings
from app.domain.models import AgentResult, DagTask
from app.events.publisher import EventPublisher


def _build_file_tools(base_dir: Path) -> list:
    """使用 FileManagementToolkit 构建标准文件操作工具集。"""
    toolkit = FileManagementToolkit(
        root_dir=str(base_dir),
    )
    tools = toolkit.get_tools()
    return list(tools)


class FileAgentExecutor:
    """纯文件操作 Agent —— FileManagementToolkit + DeepSeek 推理。

    直接使用 FileManagementToolkit，不依赖 Agent 配置白名单
    提供的 7 个标准文件工具。在 DAG 中作为 agent_type='file-ops' 调度。
    """

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

        from app.prompts.builder import PromptBuilder
        system_prompt = (
            PromptBuilder().add_common_protocol()
            .add_role_prompt("file-ops", profile)
            .add_system_prompt(profile).build_system()
            + "\n\n"
            f"工作空间根目录：{workspace_root}\n"
            "你是纯文件操作 Agent，负责文件的复制、移动、删除、读取、写入、列表和搜索。\n"
            "所有操作限制在工作空间内。使用工具时传入相对于工作空间的路径。\n"
            "完成任务后简洁说明：操作了什么文件、结果如何。"
        )
        task_prompt = (
            f"任务 ID：{task.id}\n任务目标：{task.objective}\n"
            f"允许写入范围：{task.write_scope or ['只读']}\n"
            f"前置任务结果：\n{dep_context}"
        )

        tools = _build_file_tools(workspace_root)

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
            payload={
                "prompt_chars": prompt_chars,
                "system_prompt_chars": len(str(profile.prompt)),
                "tools": [t.name for t in tools],
            },
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
                summary="文件 Agent 执行超时",
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
                summary="文件 Agent 执行失败",
                error=error_detail,
            )

    @staticmethod
    def _cancelled(task: DagTask) -> AgentResult:
        return AgentResult(
            task_id=task.id, agent=task.agent, status="cancelled",
            summary="文件操作已按用户请求取消",
        )

    @staticmethod
    def tool_names() -> list[str]:
        """返回该 executor 提供的工具名列表，供前端信息展示。"""
        return ["copy_file", "file_delete", "file_search", "move_file",
                "read_file", "write_file", "list_directory"]
