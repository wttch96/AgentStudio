"""Unit tests for the Peewee/FTS5/sqlite-vec persistence layer."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.services.rag._store import (
    KnowledgeChunk,
    KnowledgeFeedback,
    KnowledgeRelation,
    RAGStore,
)


@pytest.fixture()
def store(tmp_path):
    value = RAGStore(tmp_path / "rag.db", vector_dimensions=3)
    yield value
    if not value.database.is_closed():
        value.database.close()


def entry_record(
    entry_id: str,
    *,
    project_id: str = "project-a",
    title: str = "Peewee guide",
    content: str = "SQLite persistence with Peewee",
    category: str = "backend",
    tags: list[str] | None = None,
    expires_at: str | None = None,
) -> dict:
    return {
        "id": entry_id,
        "project_id": project_id,
        "title": title,
        "content": content,
        "category": category,
        "tags": tags or ["sqlite", "python"],
        "source": "manual",
        "source_type": "manual",
        "score": 0.0,
        "expires_at": expires_at,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def index_entry(
    store: RAGStore,
    entry_id: str,
    *,
    title: str = "Peewee guide",
    category: str = "backend",
    chunks: list[str] | None = None,
    embeddings: list[list[float] | None] | None = None,
) -> None:
    chunks = chunks or ["Peewee provides a compact SQLite ORM"]
    embeddings = embeddings or [[1.0, 0.0, 0.0]]
    store.replace_chunks(
        entry_id, title, category, ["sqlite", "python"], chunks, embeddings
    )


def test_initializes_peewee_fts_and_vec_schema(store):
    names = {
        row[0]
        for row in store.database.execute_sql(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }

    assert {
        "knowledge_entries",
        "knowledge_chunks",
        "knowledge_relations",
        "knowledge_feedback",
        "knowledge_fts",
        "knowledge_vec",
    } <= names
    assert store.database.execute_sql("SELECT vec_version()").fetchone()[0]


def test_entry_crud_serializes_tags_and_rejects_unknown_updates(store):
    assert store.insert_entry(entry_record("entry-1")) == "entry-1"
    assert store.get_entry("entry-1")["tags"] == ["sqlite", "python"]

    assert store.update_entry(
        "entry-1",
        {"title": "Updated", "tags": ["orm"], "project_id": "not-allowed"},
    )
    updated = store.get_entry("entry-1")
    assert updated["title"] == "Updated"
    assert updated["tags"] == ["orm"]
    assert updated["project_id"] == "project-a"
    assert not store.update_entry("entry-1", {"unknown": "value"})
    assert store.get_entry("missing") is None


def test_list_entries_filters_and_orders_by_quality_score(store):
    store.insert_entry(entry_record("low", project_id="p1"))
    store.insert_entry(entry_record("high", project_id="p1"))
    store.insert_entry(entry_record("other", project_id="p2", category="docs"))
    store.update_entry("low", {"score": 10})
    store.update_entry("high", {"score": 90})

    assert [
        item["id"] for item in store.list_entries("backend", 10, 0, "p1")
    ] == ["high", "low"]
    assert [item["id"] for item in store.list_entries(None, 1, 1, "p1")] == ["low"]


def test_fts_search_filters_and_aggregates_chunks_to_entry(store):
    store.insert_entry(entry_record("wanted", project_id="p1"))
    store.insert_entry(entry_record("wrong-project", project_id="p2"))
    index_entry(
        store,
        "wanted",
        chunks=["Peewee database patterns", "Advanced Peewee transactions"],
        embeddings=[None, None],
    )
    index_entry(
        store,
        "wrong-project",
        chunks=["Peewee elsewhere"],
        embeddings=[None],
    )

    results = store.search_fts("Peewee", 10, "backend", "p1")

    assert [entry_id for entry_id, _ in results] == ["wanted"]
    assert 0 < results[0][1] <= 1


def test_vector_search_uses_best_chunk_per_entry(store):
    store.insert_entry(entry_record("first"))
    store.insert_entry(entry_record("second"))
    index_entry(
        store,
        "first",
        chunks=["near", "far"],
        embeddings=[[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
    )
    index_entry(
        store,
        "second",
        chunks=["opposite"],
        embeddings=[[-1.0, 0.0, 0.0]],
    )

    results = store.search_vectors([1.0, 0.0, 0.0], 10)

    assert results[0][0] == "first"
    assert results[0][1] > 0.99
    assert len([item for item in results if item[0] == "first"]) == 1


def test_replace_chunks_removes_old_fts_and_vector_rows(store):
    store.insert_entry(entry_record("entry-1"))
    index_entry(store, "entry-1")

    index_entry(
        store,
        "entry-1",
        chunks=["Entirely new material"],
        embeddings=[[0.0, 1.0, 0.0]],
    )

    # “compact” only existed in the old chunk; the title still contains “Peewee”.
    assert store.search_fts("compact", 10, None, "") == []
    assert store.search_fts("Entirely", 10, None, "")[0][0] == "entry-1"
    assert store.search_vectors([0.0, 1.0, 0.0], 5)[0][0] == "entry-1"
    assert KnowledgeChunk.select().where(KnowledgeChunk.entry == "entry-1").count() == 1


def test_delete_entry_cascades_and_removes_virtual_indexes(store):
    store.insert_entry(entry_record("entry-1"))
    index_entry(store, "entry-1")
    store.add_feedback("entry-1", "up")

    assert store.delete_entry("entry-1")
    assert not store.delete_entry("entry-1")
    assert store.get_entry("entry-1") is None
    assert KnowledgeChunk.select().count() == 0
    assert KnowledgeFeedback.select().count() == 0
    assert store.search_fts("Peewee", 10, None, "") == []
    assert store.search_vectors([1.0, 0.0, 0.0], 5) == []


def test_relations_are_unique_and_removed_with_entry(store):
    store.insert_entry(entry_record("source"))
    store.insert_entry(entry_record("target"))

    store.add_relation("source", "target", "related")
    store.add_relation("source", "target", "related")

    relations = store.get_relations("source")
    assert len(relations) == 1
    assert relations[0]["target_id"] == "target"
    store.delete_entry("target")
    assert KnowledgeRelation.select().count() == 0


def test_feedback_recalculates_percentage_score(store):
    store.insert_entry(entry_record("entry-1"))

    assert store.add_feedback("entry-1", "up") == 100.0
    assert store.add_feedback("entry-1", "down") == 50.0
    assert store.add_feedback("entry-1", "down") == pytest.approx(100 / 3)
    assert store.get_entry("entry-1")["score"] == pytest.approx(100 / 3)


def test_cleanup_expired_and_stats_are_project_scoped(store):
    expired = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    store.insert_entry(entry_record("expired", project_id="p1", expires_at=expired))
    store.insert_entry(entry_record("active", project_id="p1", expires_at=future))
    store.insert_entry(entry_record("other", project_id="p2", category="docs"))

    assert store.cleanup_expired() == 1
    stats = store.stats("p1")
    assert stats["total"] == 1
    assert stats["by_category"] == {"backend": 1}
