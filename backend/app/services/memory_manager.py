"""分层记忆管理器 —— LangGraph Checkpointer + LangMem 集成。

三层记忆架构：
  短期（会话内）：LangGraph SqliteSaver checkpoint 自动保存图状态，天然支持断点续传。
  长期（跨会话）：LangMem create_memory_store_manager 负责重要信息提取 / 记忆合并 / 检索。
  策略引擎：根据 MemoryConfiguration 决定何时压缩、归档、重建 thread。
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from langmem import create_memory_store_manager, create_thread_extractor

from app.config import Settings
from app.domain.configuration import MemoryConfiguration
from app.domain.models import MemoryLevel
from app.storage.runtime_store import RuntimeStore


# LangMem 记忆提取 prompt — 从对话中提取长期有价值的记忆
MEMORY_EXTRACTION_INSTRUCTIONS = """你是 Agent Studio 的长期记忆管理器。从多 Agent 协作对话中提取对后续任务有价值的记忆。

关注以下类型的信息：
1. **项目结构认知**：用户项目的目录结构、技术栈、关键文件位置
2. **决策与理由**：主脑做了哪些架构决策，为什么
3. **Agent 能力评估**：各 Agent 擅长/不擅长的任务类型
4. **经验教训**：哪些策略有效、哪些失败、原因
5. **用户偏好**：用户明确表达的偏好、风格要求、约束

只记录有价值的信息；忽略临时的调试日志和无关对话。使用中文。"""

# Thread 摘要 prompt
THREAD_SUMMARY_INSTRUCTIONS = """总结以下 Agent Studio 会话。保留：
1. 用户原始目标
2. 主脑的规划策略和 DAG 结构
3. 各 Agent 完成的关键任务和结果
4. 遗留问题和风险
使用简洁中文，不超过 500 字。"""


class StrategyEngine:
    """配置驱动的策略引擎 — 决定何时触发压缩 / 归档 / 重建。"""

    def __init__(self, config: MemoryConfiguration) -> None:
        self.config = config

    def should_compress(self, token_count: int) -> bool:
        """Token 超过阈值时触发压缩。"""
        return token_count > self.config.compress_trigger_tokens

    def should_archive(self, turn_count: int, last_active: datetime | None = None) -> bool:
        """轮次超限或闲置超时触发归档。"""
        if turn_count > self.config.max_conversation_turns:
            return True
        if last_active and self.config.session_archive_after_hours > 0:
            elapsed = (datetime.now(timezone.utc) - last_active).total_seconds() / 3600
            if elapsed > self.config.session_archive_after_hours:
                return True
        return False

    def decay_importance(self, current: float) -> float:
        """按衰减率降低记忆重要性。"""
        return max(0.1, current * self.config.importance_decay_rate)


class MemoryManager:
    """基于 LangMem 的分层记忆管理器。

    短期记忆由 LangGraph SqliteSaver 自动处理（图状态 checkpoint）。
    本管理器负责长期记忆的提取、存储和检索。
    """

    def __init__(
        self,
        settings: Settings,
        store: RuntimeStore,
        memory_config: MemoryConfiguration,
    ) -> None:
        self.settings = settings
        self.store = store
        self.config = memory_config
        self.strategy = StrategyEngine(memory_config)

        # LangMem: 记忆存储管理器 — 跨会话提取、合并、检索记忆
        self._mem_store_manager = None
        if settings.deepseek_api_key:
            try:
                self._mem_store_manager = create_memory_store_manager(
                    f"openai:{settings.deepseek_model}",
                    instructions=MEMORY_EXTRACTION_INSTRUCTIONS,
                    namespace=("agent_studio", "long_term"),
                    enable_inserts=True,
                    enable_deletes=True,
                )
            except Exception:
                self._mem_store_manager = None

        # LangMem: Thread 提取器 — 会话结束后生成摘要
        self._thread_extractor = None
        if settings.deepseek_api_key:
            try:
                self._thread_extractor = create_thread_extractor(
                    f"openai:{settings.deepseek_model}",
                    instructions=THREAD_SUMMARY_INSTRUCTIONS,
                )
            except Exception:
                self._thread_extractor = None

    # ── 长期记忆：跨会话提取 ──────────────────────────

    def extract_long_term_memory(
        self,
        conversation_id: str,
        run_id: str,
        session_summary: str,
        agent_results: list[dict] | None = None,
    ) -> dict[str, Any] | None:
        """运行结束后，用 LangMem 从对话中提取长期有价值的信息。

        策略引擎判断：只有当轮次超限或 session_summary 包含实质内容时才触发。
        """
        if not self._mem_store_manager or not session_summary:
            return None

        try:
            # 构建供 LangMem 提取的 messages
            messages = [
                {"role": "user", "content": f"会话 {conversation_id} 的执行摘要：\n{session_summary}"},
            ]
            if agent_results:
                results_text = json.dumps(agent_results[-10:], ensure_ascii=False, indent=2)
                messages.append({"role": "assistant", "content": f"Agent 执行结果：\n{results_text}"})

            # LangMem 自动提取、比较、合并记忆到 Store
            result = self._mem_store_manager.invoke({"messages": messages})
            extracted = result.get("messages", []) if isinstance(result, dict) else []

            # 持久化到本地 SQLite
            record = {
                "id": uuid.uuid4().hex,
                "run_id": run_id,
                "conversation_id": conversation_id,
                "level": MemoryLevel.PROJECT.value,
                "phase": "extraction",
                "summary": session_summary[:4000],
                "structured_data": {"langmem_result": str(extracted)[:8000]},
                "token_count_before": len(session_summary),
                "token_count_after": len(str(extracted)),
                "importance": 0.7,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            self.store.insert_memory(record)
            return record
        except Exception:
            return None

    # ── 会话摘要：Thread 提取 ──────────────────────────

    def summarize_thread(
        self,
        conversation_id: str,
        messages: list[dict],
    ) -> str:
        """会话结束后生成 Thread 摘要，供后续对话的 continuation_context 使用。"""
        if not self._thread_extractor:
            return self._fallback_summary(messages)

        try:
            result = self._thread_extractor.invoke({"messages": messages})
            if hasattr(result, "content"):
                summary = result.content
            elif isinstance(result, dict):
                summary = result.get("summary", str(result)[:2000])
            else:
                summary = str(result)[:2000]

            # 持久化到 session_summaries 表
            self.store.upsert_session_summary(
                conversation_id,
                summary=summary,
                total_tokens=sum(len(str(m.get("content", ""))) for m in messages),
            )
            return summary
        except Exception:
            return self._fallback_summary(messages)

    # ── Agent 层压缩：滑动窗口 + 摘要 ───────────────────

    def compress_agent_messages(
        self,
        agent_id: str,
        conversation_id: str,
        messages: list[dict],
    ) -> list[dict]:
        """Agent 层压缩：Token 超阈值时用 LLM 压缩全部历史为摘要。

        压缩失败时保留全部原始消息，绝不丢弃数据。
        """
        token_count = sum(len(str(m.get("content", ""))) // 2 for m in messages)
        if not self.strategy.should_compress(token_count):
            return messages

        summary = self._summarize_chunk(messages)

        # 压缩失败（fallback 摘要质量太低）→ 保留全部原始消息，不丢弃
        if not summary or summary == self._fallback_summary(messages):
            return messages

        # 持久化压缩记录
        self.store.insert_memory({
            "id": uuid.uuid4().hex,
            "run_id": "",
            "conversation_id": conversation_id,
            "level": MemoryLevel.AGENT.value,
            "agent_id": agent_id,
            "phase": "compression",
            "summary": summary,
            "token_count_before": token_count,
            "token_count_after": len(summary) // 2,
            "importance": 0.4,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })

        # 摘要 + 最后几条消息保持上下文连贯
        keep_recent = min(len(messages), self.config.compress_keep_recent)
        recent = messages[-keep_recent:] if keep_recent > 0 else []
        return [{"role": "system", "content": f"[历史摘要]\n{summary}"}, *recent]
    def extract_planner_memory(
        self,
        run_id: str,
        conversation_id: str,
        planning_context: str,
        agent_results: list[dict],
    ) -> dict[str, Any]:
        """主脑层：从规划上下文 + 执行结果中提取记忆。"""
        decisions = self._extract_decisions(planning_context, agent_results)

        self.store.insert_memory({
            "id": uuid.uuid4().hex,
            "run_id": run_id,
            "conversation_id": conversation_id,
            "level": MemoryLevel.PLANNER.value,
            "phase": "planning",
            "summary": planning_context[:4000],
            "structured_data": decisions,
            "token_count_before": len(planning_context) // 2,
            "token_count_after": len(json.dumps(decisions, ensure_ascii=False)) // 2,
            "importance": 0.6,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })

        # 更新主脑状态
        existing = self.store.get_planner_memory_state(conversation_id) or {}
        decision_log = existing.get("decision_log", [])
        decision_log.extend(decisions.get("decisions", [])[:5])
        self.store.save_planner_memory_state(conversation_id, {
            "decision_log": decision_log[-20:],
            "agent_capability_notes": decisions.get("agent_performance", {}),
            "contract_history": existing.get("contract_history", []),
        })

        return decisions

    # ── 记忆检索 ──────────────────────────────────────

    def retrieve_memories(
        self,
        conversation_id: str,
        level: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """检索历史记忆，按重要性排序。"""
        return self.store.query_memories(conversation_id, level=level, limit=limit)

    def get_stats(self, conversation_id: str) -> dict[str, Any]:
        return self.store.get_memory_stats(conversation_id)

    # ── 内部工具方法 ──────────────────────────────────

    def _summarize_chunk(self, messages: list[dict]) -> str:
        """用 LLM 压缩消息块。"""
        if not self.settings.deepseek_api_key:
            return self._fallback_summary(messages)

        from openai import OpenAI
        try:
            client = OpenAI(
                api_key=self.settings.deepseek_api_key,
                base_url=self.settings.deepseek_base_url,
            )
            text = "\n".join(
                f"[{m.get('role', '?')}] {str(m.get('content', ''))[:1500]}"
                for m in messages[-30:]
            )
            response = client.chat.completions.create(
                model=self.config.summarizer_model,
                messages=[
                    {"role": "system", "content": "将以下对话压缩为简洁摘要，保留关键操作、发现、错误和未完成事项。不超过 300 字。"},
                    {"role": "user", "content": text},
                ],
                temperature=0.1,
                max_tokens=600,
            )
            return response.choices[0].message.content or ""
        except Exception:
            return self._fallback_summary(messages)

    @staticmethod
    def _fallback_summary(messages: list[dict]) -> str:
        lines = []
        for msg in messages[-8:]:
            content = str(msg.get("content", ""))[:200]
            if content.strip():
                lines.append(f"- {content}")
        return "\n".join(lines) if lines else "无内容"

    @staticmethod
    def _extract_decisions(context: str, results: list[dict]) -> dict:
        """从上下文和结果中简单提取决策（不调用 LLM 的快速版本）。"""
        decisions = []
        for line in context.split("\n"):
            for keyword in ["选择", "决定", "采用", "使用", "方案"]:
                if keyword in line and len(line) > 10:
                    decisions.append({"what": line.strip()[:200], "why": "来自主脑规划上下文"})
                    break
            if len(decisions) >= 5:
                break
        return {
            "decisions": decisions,
            "agent_performance": {
                r.get("agent", "unknown"): r.get("status", "unknown")
                for r in results[-10:]
            },
            "files_changed": [],
            "issues": [],
        }
