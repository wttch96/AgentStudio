"""RAG 知识处理与混合检索服务。

本模块负责读取项目配置、文本/Markdown 分块、Embedding 调用和多路结果融合；
底层 Peewee、FTS5、sqlite-vec 的读写全部委托给 ``rag._store``。

最终排名为：
``BM25 × bm25_weight + vector × vector_weight + quality × score_weight``。

Embedding 服务不可用时，知识仍会写入普通表和 FTS，搜索自动退化为 BM25。
权重不在降级时重新归一化，以保持不同运行状态下的评分尺度可观测。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import yaml
from langchain_openai import OpenAIEmbeddings
from langchain_text_splitters import (
    MarkdownHeaderTextSplitter,
    RecursiveCharacterTextSplitter,
)

from app.config import settings
from app.services.rag._store import RAGStore


# 新项目没有 rag.yaml 时使用并写入这一份默认配置。
DEFAULT_RAG_CONFIG = {
    "embedding_model": "deepseek-v4-flash",
    "vector_dimensions": 1536,
    "chunk_size": 500,
    "chunk_overlap": 50,
    "search": {
        "vector_weight": 0.55,
        "bm25_weight": 0.35,
        "score_weight": 0.10,
        "candidate_multiplier": 3,
    },
}


class KnowledgeStore:
    """编排知识分块、索引和混合检索，持久化委托给 RAGStore。"""

    def __init__(self, store: RAGStore | None = None) -> None:
        """创建当前项目的知识服务。

        配置直接使用 ``app.config.settings``；store 注入主要用于测试，正常运行
        自动使用项目目录中的 ``db/rag.db``。
        """
        # 获取项目下的 rag.yaml 配置，若不存在则写入默认配置。
        self.config = self._load_config(settings.project_data_dir / "rag.yaml")
        self.store = store or RAGStore(
            settings.database_path, int(self.config["vector_dimensions"])
        )
        # 按段落、换行和空格逐级寻找切点，尽量保留自然语义边界。
        self._text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=int(self.config["chunk_size"]),
            chunk_overlap=int(self.config["chunk_overlap"]),
            separators=["\n\n", "\n", " ", ""],
        )
        # 标题先进入 Document.metadata，split_text 再将它补回块文本。
        self._markdown_splitter = MarkdownHeaderTextSplitter(
            headers_to_split_on=[("#", "H1"), ("##", "H2"), ("###", "H3")]
        )
        # 延迟创建客户端：纯 FTS 使用场景不需要初始化网络依赖。
        self._embeddings: OpenAIEmbeddings | None = None

    @staticmethod
    def _load_config(path: Path) -> dict[str, Any]:
        """读取项目 rag.yaml，并与默认值合并。

        search 是嵌套字典，需单独合并，避免只覆盖一个权重时丢失其他默认项。
        三个权重不要求总和为 1，但至少需要一个正值。
        """

        config = {
            **DEFAULT_RAG_CONFIG,
            "search": DEFAULT_RAG_CONFIG["search"].copy(),
        }
        if path.is_file():
            supplied = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            config.update({key: value for key, value in supplied.items() if key != "search"})
            config["search"].update(supplied.get("search") or {})
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                yaml.safe_dump(config, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
        weights = config["search"]
        if sum(float(weights[key]) for key in (
            "vector_weight", "bm25_weight", "score_weight"
        )) <= 0:
            raise ValueError("RAG search weights must contain at least one positive value")
        return config

    def _embedding_client(self) -> OpenAIEmbeddings | None:
        """按需创建 OpenAI 兼容 Embedding 客户端。

        API Key 和 base URL 沿用 Settings；模型和维度由项目 rag.yaml 管理。
        没有 API Key 时返回 None，让调用方走纯 BM25。
        """

        if not settings.deepseek_api_key:
            return None
        if self._embeddings is None:
            self._embeddings = OpenAIEmbeddings(
                model=str(self.config["embedding_model"]),
                api_key=settings.deepseek_api_key,
                base_url=settings.deepseek_base_url,
                dimensions=int(self.config["vector_dimensions"]),
            )
        return self._embeddings

    def split_text(self, text: str, type: Literal["text", "markdown"] = "markdown") -> list[str]:
        """把原文切成可独立召回的文本块。

        Markdown 会把 H1/H2/H3 拼回正文，让分块仍保留章节语义；普通文本使用
        递归字符切分器。
        """

        if type == "markdown":
            documents = self._markdown_splitter.split_text(text)
            chunks = []
            for document in documents:
                headings = [
                    str(document.metadata[key])
                    for key in ("H1", "H2", "H3")
                    if document.metadata.get(key)
                ]
                value = "\n".join([*headings, document.page_content]).strip()
                if value:
                    chunks.append(value)
            return chunks
        return [chunk for chunk in self._text_splitter.split_text(text) if chunk.strip()]

    def _embed_documents(self, chunks: list[str]) -> list[list[float] | None]:
        """批量生成向量；失败时为每块返回 None。

        这里选择降级而不是中断写入。存储层会跳过 None 向量，但照常写入 FTS。
        """

        client = self._embedding_client()
        if client is None:
            return [None] * len(chunks)
        try:
            return list(client.embed_documents(chunks))
        except Exception:
            return [None] * len(chunks)

    def _index(self, entry: dict[str, Any]) -> None:
        """从知识原文构建分块、全文索引和向量索引。

        来源扩展名决定 Markdown 或普通文本切分；新增与更新共用同一索引路径。
        """

        source_type = "markdown" if str(entry.get("source", "")).lower().endswith(
            (".md", ".markdown")
        ) else "text"
        chunks = self.split_text(entry["content"], source_type)
        if not chunks:
            chunks = [entry["content"]]
        self.store.replace_chunks(
            entry["id"], entry["title"], entry["category"], entry["tags"],
            chunks, self._embed_documents(chunks),
        )

    def add(
        self, title: str, content: str, category: str = "general",
        tags: list[str] | None = None, source: str = "", source_type: str = "manual",
        expires_at: str | None = None, score: float = 0.0, project_id: str = "",
    ) -> str:
        """新增知识原文，并立即建立 FTS/向量分块索引。"""

        record = {
            "id": uuid.uuid4().hex,
            "title": title,
            "content": content,
            "category": category,
            "tags": tags or [],
            "source": source,
            "source_type": source_type,
            "expires_at": expires_at,
            "score": score,
            "project_id": project_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self.store.insert_entry(record)
        self._index(record)
        return record["id"]

    def update(self, entry_id: str, **fields: Any) -> bool:
        """更新知识；只有检索字段变化时才重新分块和生成向量。"""

        changed = self.store.update_entry(entry_id, fields)
        if changed and {"title", "content", "category", "tags"} & fields.keys():
            entry = self.store.get_entry(entry_id)
            if entry:
                self._index(entry)
        return changed

    def delete(self, entry_id: str) -> bool:
        """删除知识及其全部派生索引。"""

        return self.store.delete_entry(entry_id)

    def get(self, entry_id: str) -> dict[str, Any] | None:
        """获取一条完整知识。"""

        return self.store.get_entry(entry_id)

    def list(
        self, category: str | None = None, limit: int = 50, offset: int = 0,
        project_id: str = "",
    ) -> list[dict[str, Any]]:
        """按项目和分类分页列出知识，不执行相关性搜索。"""

        return self.store.list_entries(category, limit, offset, project_id)

    def search(
        self, query: str, category: str | None = None, top_k: int = 10,
        project_id: str = "",
    ) -> list[dict[str, Any]]:
        """执行 BM25、向量和质量分的可配置加权检索。

        candidate_multiplier 控制每一路先召回的候选数量，再取并集精排。返回结果
        附带三个观测字段：``_search_score``、``_bm25_score`` 和 ``_vector_score``。
        """

        # 过期知识不应进入任一路召回。
        self.cleanup()
        search_config = self.config["search"]
        candidate_limit = top_k * int(search_config["candidate_multiplier"])
        # 关键词召回始终可用，是向量服务异常时的基础路径。
        bm25 = self.store.search_fts(query, candidate_limit, category, project_id)
        vector: list[tuple[str, float]] = []
        client = self._embedding_client()
        # Embedding 或 vec 查询失败只关闭本次向量分支，不影响 BM25 结果。
        if client is not None:
            try:
                vector = self.store.search_vectors(client.embed_query(query), candidate_limit)
            except Exception:
                vector = []

        bm25_scores = dict(bm25)
        vector_scores = dict(vector)
        # 两路取并集，兼顾关键词精确匹配和无共同词的语义匹配。
        candidate_ids = set(bm25_scores) | set(vector_scores)
        ranked: list[tuple[float, dict[str, Any]]] = []
        for entry_id in candidate_ids:
            entry = self.store.get_entry(entry_id)
            if not entry:
                continue
            if category and entry["category"] != category:
                continue
            if project_id and entry["project_id"] != project_id:
                continue
            # 持久化质量分是 0～100，需要先归一化到 0～1。
            total = (
                float(search_config["bm25_weight"]) * bm25_scores.get(entry_id, 0.0)
                + float(search_config["vector_weight"]) * vector_scores.get(entry_id, 0.0)
                + float(search_config["score_weight"]) * float(entry["score"]) / 100.0
            )
            entry["_search_score"] = round(total, 6)
            entry["_bm25_score"] = round(bm25_scores.get(entry_id, 0.0), 6)
            entry["_vector_score"] = round(vector_scores.get(entry_id, 0.0), 6)
            ranked.append((total, entry))
        ranked.sort(key=lambda item: item[0], reverse=True)
        return [entry for _, entry in ranked[:top_k]]

    def import_file(
        self, filepath: str, category: str = "general", project_id: str = ""
    ) -> dict[str, Any]:
        """从工作区文件导入知识。

        相对路径以 workspace_root 为基准；分块仍统一经过 add/_index，避免导入
        场景形成另一套索引规则。
        """

        path = Path(filepath)
        full_path = path.resolve() if path.is_absolute() else (
            settings.workspace_root / path
        ).resolve()
        if not full_path.is_file():
            raise FileNotFoundError(f"文件不存在: {filepath}")
        content = full_path.read_text(encoding="utf-8", errors="replace")
        if not content.strip():
            raise ValueError("文件内容为空")
        entry_id = self.add(
            title=full_path.stem,
            content=content[:50000],
            category=category,
            source=filepath,
            source_type="import",
            project_id=project_id,
        )
        return {"imported": 1, "total_blocks": 1, "entries": [entry_id], "source": filepath}

    def add_relation(self, source_id: str, target_id: str, relation_type: str) -> str:
        """添加两条知识之间的语义关系。"""

        return self.store.add_relation(source_id, target_id, relation_type)

    def get_relations(self, entry_id: str) -> list[dict[str, Any]]:
        """读取指定知识相关的关系集合。"""

        return self.store.get_relations(entry_id)

    def add_feedback(self, entry_id: str, feedback: str) -> float:
        """校验并记录人工反馈，返回更新后的 0～100 质量分。"""

        if feedback not in ("up", "down"):
            raise ValueError("feedback must be 'up' or 'down'")
        return self.store.add_feedback(entry_id, feedback)

    def stats(self, project_id: str = "") -> dict[str, Any]:
        """返回指定项目的知识库统计。"""

        return self.store.stats(project_id)

    def cleanup(self) -> int:
        """清理过期知识并返回删除数量。"""

        return self.store.cleanup_expired()
