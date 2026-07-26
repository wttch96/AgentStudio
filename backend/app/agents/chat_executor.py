"""Chat Agent -- LangChain 驱动的纯对话 Agent（无工具，仅 LLM）。"""

from __future__ import annotations

import asyncio
import threading
from datetime import datetime, timezone

from langchain.agents import create_agent
from langchain_openai import ChatOpenAI

from app.agents.registry import AgentRegistry
from app.config import Settings
from app.domain.models import AgentResult, DagTask
from app.events.publisher import EventPublisher


class ChatExecutor:
    """基于 LangChain + DeepSeek 的纯对话 Agent，不使用任何工具。"""

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
        max_turns: int,
        timeout_seconds: int,
        project_id: str,
    ) -> AgentResult:
        started_at = datetime.now(timezone.utc)
        self.events.emit(run_id, "agent.started", agent_id=task.agent, task_id=task.id,
                         payload={"objective": task.objective, "agent_type": "chat"})

        profile = self.registry.get(project_id, task.agent)
        dep_context = "\n".join(
            f"- {r.task_id}: {r.summary}" for r in dependency_results
        ) or "无前置任务"

        from app.prompts.builder import PromptBuilder
        system_prompt = (
            PromptBuilder().add_common_protocol()
            .add_role_prompt("chat", profile)
            .add_system_prompt(profile).build_system()
        )

        try:
            model_name = profile.model or self.settings.deepseek_model
            llm = ChatOpenAI(
                model=model_name,
                api_key=self.settings.deepseek_api_key,
                base_url=self.settings.deepseek_base_url,
                temperature=0.3,
            )
            agent = create_agent(llm, [], system_prompt=system_prompt)

            task_prompt = (
                f"任务 ID：{task.id}\n任务目标：{task.objective}\n"
                f"前置任务结果：\n{dep_context}"
            )

            result = await agent.ainvoke({"messages": [("user", task_prompt)]})
            messages = result.get("messages", [])
            final_msg = messages[-1].content if messages else ""
            summary = str(final_msg)[:2000] if final_msg else "Chat Agent 完成对话"

            duration_ms = int((datetime.now(timezone.utc) - started_at).total_seconds() * 1000)
            self.events.emit(run_id, "agent.completed", agent_id=task.agent, task_id=task.id,
                             payload={"summary": summary, "duration_ms": duration_ms,
                                      "status": "completed"})

            return AgentResult(
                task_id=task.id, agent=task.agent, status="completed",
                summary=summary, duration_ms=duration_ms,
            )
        except Exception as e:
            error_msg = f"{type(e).__name__}: {str(e)}"
            self.events.emit(run_id, "agent.failed", agent_id=task.agent, task_id=task.id,
                             payload={"error": error_msg, "summary": error_msg})
            return AgentResult(
                task_id=task.id, agent=task.agent, status="failed",
                summary=error_msg,
            )

    def _cancelled(self, task: DagTask) -> AgentResult:
        return AgentResult(task_id=task.id, agent=task.agent, status="cancelled",
                           summary="任务已取消")
