"""RAG 数据持久化层。

本模块只处理“数据如何保存和查询”，不负责分词、Embedding 调用或多路结果融合。
数据由同一个 SQLite 文件承载：

1. Peewee 普通表保存知识原文、分块元数据、关系和人工反馈。
2. FTS5 虚拟表保存分块后的全文索引，并提供 BM25 排名。
3. sqlite-vec ``vec0`` 虚拟表保存分块向量，并提供余弦距离 KNN 查询。

``KnowledgeChunk.id`` 是普通表、FTS 和向量索引之间的关联键。知识可以按多个块
参与召回，但最终仍能聚合回完整的知识条目。
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import peewee
import sqlite_vec


# 模型在模块加载时声明，而数据库路径取决于当前项目；代理用于延迟绑定数据库。
database_proxy = peewee.DatabaseProxy()


class VecDatabase(peewee.SqliteDatabase):
    """确保 Peewee 创建的每个新连接都加载 sqlite-vec 扩展。"""

    def _initialize_connection(self, connection) -> None:
        super()._initialize_connection(connection) # type: ignore
        # 动态扩展只在加载期间开放，完成后立即恢复禁用状态。
        connection.enable_load_extension(True)
        try:
            sqlite_vec.load(connection)
        finally:
            connection.enable_load_extension(False)


class BaseModel(peewee.Model):
    """RAG 普通业务表的 Peewee 基类。"""

    class Meta:
        arbitrary_types_allowed = True
        database = database_proxy


class KnowledgeEntry(BaseModel):
    """一条完整知识；score 是人工反馈形成的 0～100 质量分。"""

    id = peewee.TextField(primary_key=True)
    project_id = peewee.TextField(default="", index=True)
    title = peewee.TextField()
    content = peewee.TextField()
    category = peewee.TextField(default="general", index=True)
    tags = peewee.TextField(default="[]")
    source = peewee.TextField(default="")
    source_type = peewee.TextField(default="manual")
    score = peewee.FloatField(default=0.0)
    expires_at = peewee.TextField(null=True)
    created_at = peewee.TextField()
    updated_at = peewee.TextField()

    class Meta(BaseModel.Meta):
        table_name = "knowledge_entries"


class KnowledgeChunk(BaseModel):
    """知识分块；position 保留块在原文中的顺序。"""

    id = peewee.TextField(primary_key=True)
    entry = peewee.ForeignKeyField(
        KnowledgeEntry, backref="chunks", column_name="entry_id", on_delete="CASCADE"
    )
    position = peewee.IntegerField()
    content = peewee.TextField()

    class Meta(BaseModel.Meta):
        table_name = "knowledge_chunks"
        indexes = ((("entry", "position"), True),)


class KnowledgeRelation(BaseModel):
    """两条知识之间的有向语义关系。"""

    id = peewee.TextField(primary_key=True)
    source = peewee.ForeignKeyField(
        KnowledgeEntry, backref="outgoing_relations", column_name="source_id",
        on_delete="CASCADE",
    )
    target = peewee.ForeignKeyField(
        KnowledgeEntry, backref="incoming_relations", column_name="target_id",
        on_delete="CASCADE",
    )
    relation_type = peewee.TextField()
    created_at = peewee.TextField()

    class Meta(BaseModel.Meta):
        table_name = "knowledge_relations"
        indexes = ((("source", "target", "relation_type"), True),)


class KnowledgeFeedback(BaseModel):
    """用户对知识质量的一次赞或踩。"""

    id = peewee.AutoField()
    entry = peewee.ForeignKeyField(
        KnowledgeEntry, backref="feedback", column_name="entry_id", on_delete="CASCADE"
    )
    feedback = peewee.TextField(constraints=[peewee.Check("feedback IN ('up', 'down')")])
    created_at = peewee.TextField()

    class Meta(BaseModel.Meta):
        table_name = "knowledge_feedback"


class RAGStore:
    """封装 Peewee、FTS5 和 sqlite-vec 的全部数据库细节。"""

    def __init__(self, database_path: Path, vector_dimensions: int = 1536) -> None:
        """打开项目数据库。

        vector_dimensions 必须与 Embedding 输出维度一致；vec0 建表后维度固定，
        更换维度时需要重建 RAG 数据库。
        """
        self.database_path = Path(database_path)
        self.vector_dimensions = vector_dimensions
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        # WAL 支持并发读写；外键用于级联删除；busy_timeout 缓解短暂写锁冲突。
        self.database = VecDatabase(
            self.database_path,
            pragmas={"journal_mode": "wal", "foreign_keys": 1, "busy_timeout": 30000},
        )
        database_proxy.initialize(self.database)
        self.database.connect(reuse_if_open=True)
        self._initialize()

    def _initialize(self) -> None:
        """仅创建当前版本需要的结构，不执行旧表迁移或清理。"""

        # 结构化数据由 Peewee 管理。
        self.database.create_tables(
            [KnowledgeEntry, KnowledgeChunk, KnowledgeRelation, KnowledgeFeedback],
            safe=True,
        )
        # 两个 ID 字段只做关联，不进入倒排索引。
        self.database.execute_sql(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts USING fts5(
                chunk_id UNINDEXED, entry_id UNINDEXED, title, content, category, tags
            )
            """
        )
        # 余弦距离越小表示两个分块的语义越接近。
        self.database.execute_sql(
            f"""
            CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_vec USING vec0(
                chunk_id TEXT PRIMARY KEY,
                embedding FLOAT[{self.vector_dimensions}] distance_metric=cosine
            )
            """
        )

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _entry_dict(entry: KnowledgeEntry) -> dict[str, Any]:
        """将 Peewee 模型转成 API 字典，并把 tags JSON 还原为列表。"""

        data = entry.__data__.copy()
        data["tags"] = json.loads(data.get("tags") or "[]")
        return data

    def insert_entry(self, record: dict[str, Any]) -> str:
        """写入知识原文；派生分块和搜索索引由 replace_chunks 维护。"""

        now = self._now()
        KnowledgeEntry.create(
            id=record["id"],
            project_id=record.get("project_id", ""),
            title=record["title"],
            content=record["content"],
            category=record.get("category", "general"),
            tags=json.dumps(record.get("tags", []), ensure_ascii=False),
            source=record.get("source", ""),
            source_type=record.get("source_type", "manual"),
            score=record.get("score", 0.0),
            expires_at=record.get("expires_at"),
            created_at=record.get("created_at") or now,
            updated_at=now,
        )
        return record["id"]

    def replace_chunks(
        self,
        entry_id: str,
        title: str,
        category: str,
        tags: list[str],
        chunks: list[str],
        embeddings: list[list[float] | None],
    ) -> None:
        """原子替换某条知识的分块、FTS 索引和向量索引。

        原文更新后，三个位置必须同步替换，否则搜索会继续命中旧内容。
        embeddings 允许包含 None，使 Embedding 服务不可用时仍可建立 FTS 索引。
        """

        # 必须先保存旧 ID；删除普通块后将无法定位两个虚拟表中的对应记录。
        old_ids = [
            row.id for row in KnowledgeChunk.select(KnowledgeChunk.id).where(
                KnowledgeChunk.entry == entry_id
            )
        ]
        with self.database.atomic():
            if old_ids:
                placeholders = ",".join("?" for _ in old_ids)
                self.database.execute_sql(
                    f"DELETE FROM knowledge_fts WHERE chunk_id IN ({placeholders})", old_ids
                )
                self.database.execute_sql(
                    f"DELETE FROM knowledge_vec WHERE chunk_id IN ({placeholders})", old_ids
                )
            KnowledgeChunk.delete().where(KnowledgeChunk.entry == entry_id).execute()
            # FTS 检索自然文本，将结构化标签展平为以空格分隔的字符串。
            tag_text = " ".join(tags)
            for position, content in enumerate(chunks):
                chunk_id = uuid.uuid4().hex
                KnowledgeChunk.create(
                    id=chunk_id, entry=entry_id, position=position, content=content
                )
                self.database.execute_sql(
                    "INSERT INTO knowledge_fts"
                    "(chunk_id, entry_id, title, content, category, tags) VALUES (?, ?, ?, ?, ?, ?)",
                    (chunk_id, entry_id, title, content, category, tag_text),
                )
                # sqlite-vec 使用紧凑的 float32 二进制；无向量时不写伪数据。
                embedding = embeddings[position] if position < len(embeddings) else None
                if embedding is not None:
                    self.database.execute_sql(
                        "INSERT INTO knowledge_vec(chunk_id, embedding) VALUES (?, ?)",
                        (chunk_id, sqlite_vec.serialize_float32(embedding)),
                    )

    def get_entry(self, entry_id: str) -> dict[str, Any] | None:
        """按 ID 获取完整知识，不存在时返回 None。"""

        entry = KnowledgeEntry.get_or_none(KnowledgeEntry.id == entry_id)
        return self._entry_dict(entry) if entry else None

    def update_entry(self, entry_id: str, updates: dict[str, Any]) -> bool:
        """只更新允许公开修改的字段，保护主键和审计字段。"""

        allowed = {"title", "content", "category", "tags", "score", "expires_at"}
        fields = {key: value for key, value in updates.items() if key in allowed}
        if not fields:
            return False
        if "tags" in fields:
            fields["tags"] = json.dumps(fields["tags"], ensure_ascii=False)
        fields["updated_at"] = self._now()
        return (
            KnowledgeEntry.update(**fields)
            .where(KnowledgeEntry.id == entry_id)
            .execute()
            > 0
        )

    def delete_entry(self, entry_id: str) -> bool:
        """删除知识，同时清除 FTS 和向量虚拟表中的派生记录。"""

        chunk_ids = [
            row.id for row in KnowledgeChunk.select(KnowledgeChunk.id).where(
                KnowledgeChunk.entry == entry_id
            )
        ]
        with self.database.atomic():
            if chunk_ids:
                placeholders = ",".join("?" for _ in chunk_ids)
                self.database.execute_sql(
                    f"DELETE FROM knowledge_fts WHERE chunk_id IN ({placeholders})", chunk_ids
                )
                self.database.execute_sql(
                    f"DELETE FROM knowledge_vec WHERE chunk_id IN ({placeholders})", chunk_ids
                )
            return (
                KnowledgeEntry.delete().where(KnowledgeEntry.id == entry_id).execute() > 0
            )

    def list_entries(
        self, category: str | None, limit: int, offset: int, project_id: str
    ) -> list[dict[str, Any]]:
        """分页列出知识：质量分优先，同分按最近更新时间排序。"""

        query = KnowledgeEntry.select()
        if project_id:
            query = query.where(KnowledgeEntry.project_id == project_id)
        if category:
            query = query.where(KnowledgeEntry.category == category)
        query = query.order_by(
            KnowledgeEntry.score.desc(), KnowledgeEntry.updated_at.desc()
        ).limit(limit).offset(offset)
        return [self._entry_dict(entry) for entry in query]

    def search_fts(
        self, query: str, limit: int, category: str | None, project_id: str
    ) -> list[tuple[str, float]]:
        """执行 FTS5/BM25 召回并返回 ``(entry_id, score)``。

        FTS 的 BM25 值越小越好；这里将它转为越大越好的分数。同一知识可能命中
        多个分块，最终只保留其中最高分，避免长文因分块数量多而获得额外优势。
        """

        conditions = ["knowledge_fts MATCH ?"]
        params: list[Any] = [query]
        if category:
            conditions.append("e.category = ?")
            params.append(category)
        if project_id:
            conditions.append("e.project_id = ?")
            params.append(project_id)
        rows = self.database.execute_sql(
            "SELECT f.entry_id, bm25(knowledge_fts) AS rank "
            "FROM knowledge_fts f JOIN knowledge_entries e ON e.id=f.entry_id "
            f"WHERE {' AND '.join(conditions)} "
            "ORDER BY rank LIMIT ?",
            [*params, limit],
        ).fetchall()
        # 将 chunk 级结果聚合为 entry 级结果。
        scores: dict[str, float] = {}
        for entry_id, rank in rows:
            score = 1.0 / (1.0 + max(0.0, float(rank)))
            scores[entry_id] = max(scores.get(entry_id, 0.0), score)
        return list(scores.items())

    def search_vectors(
        self, embedding: list[float], limit: int
    ) -> list[tuple[str, float]]:
        """执行 sqlite-vec KNN 查询并返回知识级语义相似度。

        vec0 要求使用 ``embedding MATCH ? AND k = ?``。查询先召回 chunk，再经
        KnowledgeChunk 映射回 entry；余弦 distance 最后转成越大越好的 similarity。
        """

        rows = self.database.execute_sql(
            "SELECT chunk_id, distance FROM knowledge_vec "
            "WHERE embedding MATCH ? AND k = ? ORDER BY distance",
            (sqlite_vec.serialize_float32(embedding), limit),
        ).fetchall()
        chunk_ids = [row[0] for row in rows]
        if not chunk_ids:
            return []
        # vec0 只存 chunk_id，entry 归属以普通分块表为唯一事实来源。
        entry_by_chunk = {
            row.id: row.entry_id
            for row in KnowledgeChunk.select(
                KnowledgeChunk.id, KnowledgeChunk.entry
            ).where(KnowledgeChunk.id.in_(chunk_ids))
        }
        # 同一知识只采用最相似分块的得分。
        scores: dict[str, float] = {}
        for chunk_id, distance in rows:
            entry_id = entry_by_chunk.get(chunk_id)
            if entry_id:
                scores[entry_id] = max(
                    scores.get(entry_id, 0.0), max(0.0, 1.0 - float(distance))
                )
        return sorted(scores.items(), key=lambda item: item[1], reverse=True)

    def add_relation(self, source_id: str, target_id: str, relation_type: str) -> str:
        """添加知识关系；相同 source/target/type 的重复关系会被忽略。"""

        relation_id = uuid.uuid4().hex
        KnowledgeRelation.insert(
            id=relation_id,
            source=source_id,
            target=target_id,
            relation_type=relation_type,
            created_at=self._now(),
        ).on_conflict_ignore().execute()
        return relation_id

    def get_relations(self, entry_id: str) -> list[dict[str, Any]]:
        """读取以指定知识为起点或终点的全部关系。"""

        rows = KnowledgeRelation.select().where(
            (KnowledgeRelation.source == entry_id) | (KnowledgeRelation.target == entry_id)
        ).order_by(KnowledgeRelation.created_at.desc())
        return [
            {
                "id": row.id,
                "source_id": row.source_id,
                "target_id": row.target_id,
                "relation_type": row.relation_type,
                "created_at": row.created_at,
            }
            for row in rows
        ]

    def add_feedback(self, entry_id: str, feedback: str) -> float:
        """记录反馈并重算质量分。

        当前算法是点赞数占全部反馈数的百分比，结果范围为 0～100，之后由
        KnowledgeStore 按 score_weight 将它加入混合搜索排名。
        """

        KnowledgeFeedback.create(
            entry=entry_id, feedback=feedback, created_at=self._now()
        )
        total = KnowledgeFeedback.select().where(
            KnowledgeFeedback.entry == entry_id
        ).count()
        positive = KnowledgeFeedback.select().where(
            (KnowledgeFeedback.entry == entry_id)
            & (KnowledgeFeedback.feedback == "up")
        ).count()
        score = positive / total * 100 if total else 0.0
        KnowledgeEntry.update(score=score).where(KnowledgeEntry.id == entry_id).execute()
        return score

    def cleanup_expired(self) -> int:
        """删除已过期知识及全部派生索引，返回删除数量。"""

        expired_ids = [
            row.id for row in KnowledgeEntry.select(KnowledgeEntry.id).where(
                KnowledgeEntry.expires_at.is_null(False)
                & (KnowledgeEntry.expires_at < self._now())
            )
        ]
        for entry_id in expired_ids:
            self.delete_entry(entry_id)
        return len(expired_ids)

    def stats(self, project_id: str = "") -> dict[str, Any]:
        """生成指定项目的知识数量、分类及关系统计。"""

        base = KnowledgeEntry.select()
        if project_id:
            base = base.where(KnowledgeEntry.project_id == project_id)
        categories = (
            KnowledgeEntry.select(
                KnowledgeEntry.category, peewee.fn.COUNT(KnowledgeEntry.id).alias("count")
            )
            .group_by(KnowledgeEntry.category)
        )
        if project_id:
            categories = categories.where(KnowledgeEntry.project_id == project_id)
        return {
            "total": base.count(),
            "by_category": {row.category: row.count for row in categories},
            "expired": 0,
            "relations": KnowledgeRelation.select().count(),
        }
