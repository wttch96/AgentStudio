"""知识库存储服务 —— 混合检索（BM25 + 向量）、知识关系图、反馈评分、过期清理。

BM25 全文检索通过 SQLite FTS5 实现。
向量检索通过 sqlite-vec 扩展实现（如可用），否则降级为纯 BM25。
Embedding 使用 DeepSeek API。
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from app.config import Settings
from app.storage.sqlite_store import SQLiteStore


class KnowledgeStore:
    """知识库 CRUD + 混合检索 + 关系 + 反馈。"""

    def __init__(self, store: SQLiteStore, settings: Settings) -> None:
        self.store = store
        self.settings = settings

    # ── CRUD ──────────────────────────────────────────

    def add(self, title: str, content: str, category: str = "general",
            tags: list[str] | None = None, source: str = "",
            expires_at: str | None = None, score: float = 0.0) -> str:
        """添加知识条目，返回 entry_id。"""
        entry_id = uuid.uuid4().hex
        self.store.insert_knowledge({
            "id": entry_id, "title": title, "content": content,
            "category": category, "tags": tags or [],
            "source": source, "score": score,
            "expires_at": expires_at,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        return entry_id

    def update(self, entry_id: str, **fields: Any) -> bool:
        return self.store.update_knowledge(entry_id, fields)

    def delete(self, entry_id: str) -> bool:
        return self.store.delete_knowledge(entry_id)

    def get(self, entry_id: str) -> dict[str, Any] | None:
        return self.store.get_knowledge(entry_id)

    def list(self, category: str | None = None, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        return self.store.list_knowledge(category=category, limit=limit, offset=offset)

    # ── 混合检索 ──────────────────────────────────────

    def search(self, query: str, category: str | None = None, top_k: int = 10) -> list[dict[str, Any]]:
        """混合检索：BM25 (FTS5) + 向量检索，RRF 融合排序。"""
        # 自动清理过期条目
        self.store.cleanup_expired_knowledge()

        # 1. BM25 全文搜索
        bm25_ids = self.store.search_knowledge_fts(query, category=category, limit=top_k * 2)

        # 2. 向量检索（如可用）
        vec_results: list[tuple[str, float]] = self._vector_search(query, limit=top_k)

        # 3. RRF 融合
        merged = self._rrf_merge(bm25_ids, vec_results, k=60)

        # 4. 加载完整条目并按融合得分排序
        results = []
        for entry_id, rrf_score in merged[:top_k]:
            entry = self.store.get_knowledge(entry_id)
            if entry:
                entry["_rrf_score"] = round(rrf_score, 4)
                results.append(entry)

        # 5. 如果融合结果不足，用 BM25 补足
        if len(results) < top_k:
            seen = {r["id"] for r in results}
            for entry_id in bm25_ids:
                if entry_id not in seen:
                    entry = self.store.get_knowledge(entry_id)
                    if entry:
                        entry["_rrf_score"] = 0.0
                        results.append(entry)
                        seen.add(entry_id)
                    if len(results) >= top_k:
                        break

        return [r for r in results if r is not None]

    def _vector_search(self, query: str, limit: int = 10) -> list[tuple[str, float]]:
        """使用 sqlite-vec 进行向量相似度搜索。不可用时返回空列表。"""
        try:
            embedding = self._embed(query)
            if embedding is None:
                return []
            # sqlite-vec: 余弦相似度查询
            emb_str = ",".join(str(v) for v in embedding)
            with self.store._connect() as conn:
                try:
                    rows = conn.execute(
                        f"SELECT entry_id, vec_distance_cosine(embedding, '[{emb_str}]') as dist "
                        "FROM knowledge_vec ORDER BY dist LIMIT ?",
                        (limit,),
                    ).fetchall()
                    return [(row["entry_id"], 1.0 / (1.0 + float(row["dist"]))) for row in rows]
                except Exception:
                    return []
        except Exception:
            return []

    def _embed(self, text: str) -> list[float] | None:
        """调用 DeepSeek API 获取 embedding。"""
        if not self.settings.deepseek_api_key:
            return None
        try:
            from openai import OpenAI
            client = OpenAI(
                api_key=self.settings.deepseek_api_key,
                base_url=self.settings.deepseek_base_url,
            )
            response = client.embeddings.create(
                model="deepseek-chat", input=text[:8000],
            )
            return response.data[0].embedding
        except Exception:
            return None

    @staticmethod
    def _rrf_merge(
        bm25_ids: list[str],
        vec_results: list[tuple[str, float]],
        k: int = 60,
    ) -> list[tuple[str, float]]:
        """RRF (Reciprocal Rank Fusion) 融合 BM25 和向量检索结果。"""
        scores: dict[str, float] = {}
        for rank, entry_id in enumerate(bm25_ids):
            scores[entry_id] = scores.get(entry_id, 0.0) + 1.0 / (k + rank + 1)
        for rank, (entry_id, vec_score) in enumerate(vec_results):
            scores[entry_id] = scores.get(entry_id, 0.0) + 1.0 / (k + rank + 1)
        return sorted(scores.items(), key=lambda x: x[1], reverse=True)

    # ── 关系管理 ──────────────────────────────────────

    def add_relation(self, source_id: str, target_id: str, relation_type: str) -> str:
        return self.store.add_knowledge_relation(source_id, target_id, relation_type)

    def get_relations(self, entry_id: str) -> list[dict[str, Any]]:
        return self.store.get_knowledge_relations(entry_id)

    # ── 反馈评分 ──────────────────────────────────────

    def add_feedback(self, entry_id: str, feedback: str) -> None:
        if feedback not in ("up", "down"):
            raise ValueError("feedback must be 'up' or 'down'")
        self.store.add_knowledge_feedback(entry_id, feedback)

    # ── 统计 ──────────────────────────────────────────

    def stats(self) -> dict[str, Any]:
        return self.store.knowledge_stats()

    def cleanup(self) -> int:
        return self.store.cleanup_expired_knowledge()
