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
            source_type: str = "manual",
            expires_at: str | None = None, score: float = 0.0,
            project_id: str = "") -> str:
        """添加知识条目，返回 entry_id。
        source_type: "manual" (用户手动), "import" (文件导入), "auto" (Agent 自学)
        """
        entry_id = uuid.uuid4().hex
        self.store.insert_knowledge({
            "id": entry_id, "title": title, "content": content,
            "category": category, "tags": tags or [],
            "source": source, "source_type": source_type,
            "score": score,
            "expires_at": expires_at,
            "project_id": project_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        return entry_id
    def import_file(self, filepath: str, category: str = "general",
                    project_id: str = "") -> dict:
        """从工作区文件导入知识。按 Markdown 标题拆分为多个条目。"""
        from pathlib import Path
        path = Path(filepath)
        if path.is_absolute():
            full_path = path.resolve()
        else:
            root = self.settings.workspace_root
            full_path = (root / filepath).resolve()
        if not full_path.is_file():
            raise FileNotFoundError(f"文件不存在: {filepath}")

        raw = full_path.read_text(encoding="utf-8", errors="replace")
        if not raw.strip():
            raise ValueError("文件内容为空")

        lines = raw.splitlines()
        stem = full_path.stem
        suffix = full_path.suffix.lower()
        is_md = suffix in (".md", ".markdown")
        NL = chr(10)

        entries = []
        if is_md and any(line.startswith("## ") for line in lines):
            # Markdown: 按 ## 标题拆分为多个条目
            current_title = stem
            current_lines = []
            for line in lines:
                if line.startswith("# ") and not current_lines:
                    current_title = line[2:].strip()
                elif line.startswith("## "):
                    if current_lines:
                        content = NL.join(current_lines).strip()
                        if content:
                            entries.append({"title": current_title, "content": content[:50000]})
                    current_title = line[3:].strip()
                    current_lines = []
                else:
                    current_lines.append(line)
            if current_lines:
                content = NL.join(current_lines).strip()
                if content:
                    entries.append({"title": current_title, "content": content[:50000]})
        else:
            # 普通文本：整个文件作为一个条目
            title = stem
            for line in lines:
                if line.startswith("# "):
                    title = line[2:].strip()
                    break
            entries.append({"title": title, "content": raw[:50000]})

        imported = 0
        imported_ids = []
        for entry in entries:
            if not entry["content"].strip():
                continue
            eid = self.add(
                title=entry["title"], content=entry["content"],
                category=category, source=filepath, source_type="import",
                project_id=project_id,
            )
            imported_ids.append(eid)
            imported += 1

        return {
            "imported": imported,
            "total_blocks": len(entries),
            "entries": imported_ids,
            "source": filepath,
        }

    def update(self, entry_id: str, **fields: Any) -> bool:
        return self.store.update_knowledge(entry_id, fields)

    def delete(self, entry_id: str) -> bool:
        return self.store.delete_knowledge(entry_id)

    def get(self, entry_id: str) -> dict[str, Any] | None:
        return self.store.get_knowledge(entry_id)

    def list(self, category: str | None = None, limit: int = 50, offset: int = 0,
             project_id: str = "") -> list[dict[str, Any]]:
        return self.store.list_knowledge(category=category, limit=limit, offset=offset,
                                         project_id=project_id)

    # ── 混合检索 ──────────────────────────────────────

    def search(self, query: str, category: str | None = None, top_k: int = 10,
               project_id: str = "") -> list[dict[str, Any]]:
        """混合检索：BM25 (FTS5) + 向量检索，RRF 融合排序。"""
        # 自动清理过期条目
        self.store.cleanup_expired_knowledge()

        # 1. BM25 全文搜索
        bm25_ids = self.store.search_knowledge_fts(query, category=category, limit=top_k * 2,
                                                    project_id=project_id)

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
                model="deepseek-v4-pro", input=text[:8000],
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

    def stats(self, project_id: str = "") -> dict[str, Any]:
        return self.store.knowledge_stats(project_id=project_id)

    def cleanup(self) -> int:
        return self.store.cleanup_expired_knowledge()
