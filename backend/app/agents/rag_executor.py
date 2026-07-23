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
                    f"[{r.get('id','')[:8]}] {r.get('title','')}\n{r.get('content','')[:1000]}"
                    for r in results
                )
            except Exception as e:
                return f"Search error: {e}"

        def get_knowledge(entry_id: str) -> str:
            """Get full details of a knowledge entry by ID."""
            try:
                entry = ks.get(entry_id)
                if not entry:
                    return f"Entry {entry_id} not found."
                return f"Title: {entry.get('title')}\nCategory: {entry.get('category')}\n\n{entry.get('content','')}"
            except Exception as e:
                return f"Get error: {e}"

        def add_knowledge(title: str, content: str, category: str = "general") -> str:
            """Add a new knowledge entry to the knowledge base."""
            try:
                eid = ks.add(title=title, content=content, category=category, project_id=pid)
                return f"Knowledge entry created: {eid}"
            except Exception as e:
                return f"Add error: {e}"

        def list_knowledge(category: str = "") -> str:
            """List knowledge entries, optionally filtered by category."""
            try:
                results = ks.list(category=category or None, limit=20, project_id=pid)
                if not results:
                    return "No knowledge entries found."
                return "\n".join(
                    f"- [{r.get('id','')[:8]}] {r.get('title','')} ({r.get('category','')})"
                    for r in results
                )
            except Exception as e:
                return f"List error: {e}"

        search_knowledge.__name__ = "search_knowledge"
        get_knowledge.__name__ = "get_knowledge"
        add_knowledge.__name__ = "add_knowledge"
        list_knowledge.__name__ = "list_knowledge"

        tools = [search_knowledge, get_knowledge, add_knowledge, list_knowledge]

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
                if hasattr(msg, "content") and getattr(msg, "type", "") == "ai":
                    output = str(msg.content) if msg.content else ""
                    if output:
                        break
            self.events.emit(
                run_id, "agent.message",
                agent_id=task.agent, task_id=task.id,
                payload={"text": output},
            )
            return AgentResult(
                task_id=task.id, agent=task.agent, status="completed",
                summary=output[:6000] or "RAG Agent 已完成，但没有返回文本摘要。",
            )
        except TimeoutError:
            return AgentResult(
                task_id=task.id, agent=task.agent, status="failed",
                summary="RAG Agent 执行超时",
                error=f"超过 {timeout_seconds} 秒",
            )
        except Exception as error:
            error_detail = f"{type(error).__name__}: {str(error) or repr(error)}"
            return AgentResult(
                task_id=task.id, agent=task.agent, status="failed",
                summary="RAG Agent 执行失败",
                error=error_detail,
            )

    @staticmethod
    def _cancelled(task: DagTask) -> AgentResult:
        return AgentResult(
            task_id=task.id, agent=task.agent, status="cancelled",
            summary="任务已按用户请求取消",
        )
