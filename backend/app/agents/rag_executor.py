"""RAG Agent -- LangChain 驱动的知识库检索与管理 Agent。"""

from __future__ import annotations

import asyncio
import json
import threading
from datetime import datetime, timezone
from typing import Any

from langchain.agents import create_agent
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI

from app.agents.registry import AgentRegistry
from app.config import Settings
from app.domain.models import AgentResult, DagTask
from app.events.publisher import EventPublisher
from app.services.rag._knowledge_store import KnowledgeStore


class RAGAgentExecutor:
    """基于 LangChain + DeepSeek 的 RAG Agent。"""

    def __init__(
        self,
        settings: Settings,
        registry: AgentRegistry,
        events: EventPublisher,
        knowledge_store: KnowledgeStore,
    ) -> None:
        self.settings = settings
        self.registry = registry
        self.events = events
        self.knowledge_store = knowledge_store

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
                         payload={"objective": task.objective, "agent_type": "rag"})

        profile = self.registry.get(project_id, task.agent)
        dep_context = "\n".join(
            f"- {r.task_id}: {r.summary}" for r in dependency_results
        ) or "无前置任务"

        from app.prompts.builder import PromptBuilder
        system_prompt = (
            PromptBuilder().add_common_protocol()
            .add_role_prompt("rag", profile)
            .add_system_prompt(profile).build_system()
            + "\n\n"
            "你是知识库管理 Agent，可以检索知识库中的内容，也可以录入新的知识条目。\n"
            "使用 search_knowledge 工具搜索知识库，使用 add_knowledge 工具录入知识。\n"
            "优先从知识库中检索相关信息，综合后回答用户问题。"
        )

        ks = self.knowledge_store
        pid = project_id

        @tool
        def search_knowledge(query: str) -> str:
            """搜索知识库中的相关条目。"""
            try:
                results = ks.search(query, top_k=5, project_id=pid)
                if not results:
                    return "未找到相关知识条目。"
                return "\n\n---\n".join(
                    f"[{r.get('id','')[:8]}] {r.get('title','')}\n{r.get('content','')[:1000]}"
                    for r in results
                )
            except Exception as e:
                return f"搜索出错: {e}"

        @tool
        def add_knowledge(title: str, content: str, category: str = "") -> str:
            """向知识库录入新知识条目。"""
            try:
                result = ks.create(title=title, content=content, category=category, project_id=pid)
                return f"知识条目已录入，ID: {result.get('id', 'unknown')}"
            except Exception as e:
                return f"录入出错: {e}"

        tools = [search_knowledge, add_knowledge]

        try:
            model_name = profile.model or self.settings.deepseek_model
            llm = ChatOpenAI(
                model=model_name,
                api_key=self.settings.deepseek_api_key,
                base_url=self.settings.deepseek_base_url,
                temperature=0.3,
            )
            agent = create_agent(llm, tools, system_prompt=system_prompt)

            task_prompt = (
                f"任务 ID：{task.id}\n任务目标：{task.objective}\n"
                f"前置任务结果：\n{dep_context}"
            )

            result = await agent.ainvoke({"messages": [("user", task_prompt)]})
            messages = result.get("messages", [])
            final_msg = messages[-1].content if messages else ""
            summary = str(final_msg)[:2000] if final_msg else "RAG Agent 完成检索"

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
