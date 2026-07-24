"""RAG Agent -- LangChain 驱动的知识库检索与管理 Agent。

将 KnowledgeStore 的方法包装为工具，通过 DeepSeek 推理决定检索策略并综合答案。
可在 DAG 中作为知识检索节点被调度执行。
"""

from __future__ import annotations

import asyncio
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from langchain.agents import create_agent
from langchain_openai import ChatOpenAI

from app.agents.registry import AgentRegistry
from app.config import Settings
from app.domain.models import AgentResult, DagTask
from app.events.publisher import EventPublisher
from app.services.knowledge_store import KnowledgeStore


class RAGAgentExecutor:
    """基于 LangChain + DeepSeek 的 RAG Agent。

    将知识库 CRUD 和检索包装为工具，让 Agent 能自主决定：
    - 何时检索知识库
    - 何时录入新知识
    - 如何综合检索结果回答问题
    """

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
        profile = self.registry.get(project_id, task.agent)
        dep_context = "\n".join(
            f"- {r.task_id}: {r.summary}" for r in dependency_results
        ) or "无前置任务"

        system_prompt = (
            f"{profile.prompt}\n\n"
            "你是知识库管理 Agent，可以检索知识库中的内容，也可以录入新的知识条目。\n"
            "使用 search_knowledge 工具搜索知识库，使用 add_knowledge 工具录入知识，\n"
            "使用 get_knowledge 工具查看条目详情。\n"
            "优先从知识库中检索相关信息，综合后回答用户问题。"
        )
        task_prompt = (
            f"任务 ID：{task.id}\n任务目标：{task.objective}\n"
            f"前置任务结果：\n{dep_context}"
        )

        # Build RAG tools wrapping KnowledgeStore
        ks = self.knowledge_store
        pid = project_id

        def search_knowledge(query: str) -> str:
            """Search the knowledge base for relevant entries."""
            try:
                results = ks.search(query, top_k=5, project_id=pid)
                if not results:
                    return "No matching knowledge entries found."
                return "\n\n---\n".join(
                    f"[{r.get('id','')[:8]}] {r.get('title','')} [{r.get('source_type','manual')}]\n{r.get('content','')[:1000]}"
                    for r in results
                )
            except Exception as e:
                return f"Search error: {e}"

        def get_knowledge(entry_id: str) -> str:
            """Get full details of a knowledge entry by ID."""
            entry = ks.get(entry_id)
            if not entry:
                return f"Knowledge entry {entry_id} not found."
            return (
                f"Title: {entry.get('title', '')}\n"
                f"Category: {entry.get('category', '')}\n"
                f"Source: {entry.get('source_type', 'manual')}\n"
                f"Content:\n{entry.get('content', '')[:2000]}"
            )
       