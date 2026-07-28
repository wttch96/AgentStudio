from dataclasses import replace
from unittest.mock import Mock

import pytest
import yaml

from app.config import Settings
from app.services.rag import _knowledge_store
from app.services.rag._knowledge_store import DEFAULT_RAG_CONFIG, KnowledgeStore
from app.services.rag._store import RAGStore


def build_store(tmp_path, monkeypatch):
    test_settings = replace(
        Settings(),
        instance_dir=tmp_path,
        workspace_root=tmp_path,
        deepseek_api_key="",
    )
    config = {
        "embedding_model": "test-embedding",
        "vector_dimensions": 3,
        "chunk_size": 50,
        "chunk_overlap": 5,
        "search": {
            "vector_weight": 0.5,
            "bm25_weight": 0.3,
            "score_weight": 0.2,
            "candidate_multiplier": 3,
        },
    }
    (tmp_path / "rag.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")
    persistence = RAGStore(tmp_path / "rag.db", vector_dimensions=3)
    monkeypatch.setattr(_knowledge_store, "settings", test_settings)
    service = KnowledgeStore(persistence)
    monkeypatch.setattr(
        service,
        "_embed_documents",
        lambda chunks: [[1.0, 0.0, 0.0] for _ in chunks],
    )
    return service


def test_splits_plain_and_markdown_text(tmp_path, monkeypatch):
    service = build_store(tmp_path, monkeypatch)

    assert service.split_text("first paragraph\n\nsecond paragraph")
    assert service.split_text("# Intro\n\n## Details\nBody", "markdown") == [
        "Intro\nDetails\nBody",
    ]


def test_indexes_and_searches_with_fts_and_score(tmp_path, monkeypatch):
    service = build_store(tmp_path, monkeypatch)
    first = service.add("Python guide", "Peewee SQLite database patterns")
    second = service.add("Other", "Unrelated content")
    service.add_feedback(first, "up")
    service.add_feedback(second, "down")

    results = service.search("Peewee")

    assert results[0]["id"] == first
    assert results[0]["_bm25_score"] > 0
    assert results[0]["score"] == 100.0


def test_vector_search_uses_sqlite_vec(tmp_path, monkeypatch):
    service = build_store(tmp_path, monkeypatch)
    entry_id = service.add("Vectors", "semantic retrieval")

    results = service.store.search_vectors([1.0, 0.0, 0.0], 5)

    assert results[0][0] == entry_id
    assert results[0][1] > 0.99


def settings_for(tmp_path, *, api_key=""):
    return replace(
        Settings(),
        instance_dir=tmp_path,
        workspace_root=tmp_path,
        deepseek_api_key=api_key,
    )


def configured_service(
    tmp_path, monkeypatch, persistence=None, *, search=None, api_key=""
):
    config = {
        **DEFAULT_RAG_CONFIG,
        "vector_dimensions": 3,
        "search": {
            **DEFAULT_RAG_CONFIG["search"],
            **(search or {}),
        },
    }
    (tmp_path / "rag.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")
    monkeypatch.setattr(
        _knowledge_store, "settings", settings_for(tmp_path, api_key=api_key)
    )
    return KnowledgeStore(persistence)


def test_missing_config_is_created_with_defaults(tmp_path, monkeypatch):
    config_path = tmp_path / "rag.yaml"
    monkeypatch.setattr(_knowledge_store, "settings", settings_for(tmp_path))

    service = KnowledgeStore()

    assert config_path.is_file()
    assert yaml.safe_load(config_path.read_text(encoding="utf-8")) == DEFAULT_RAG_CONFIG
    assert service.config["search"]["vector_weight"] == 0.55


def test_partial_search_config_merges_defaults(tmp_path, monkeypatch):
    (tmp_path / "rag.yaml").write_text(
        yaml.safe_dump({"search": {"score_weight": 0.4}}),
        encoding="utf-8",
    )

    monkeypatch.setattr(_knowledge_store, "settings", settings_for(tmp_path))
    service = KnowledgeStore()

    assert service.config["search"] == {
        "vector_weight": 0.55,
        "bm25_weight": 0.35,
        "score_weight": 0.4,
        "candidate_multiplier": 3,
    }


def test_all_zero_weights_are_rejected(tmp_path, monkeypatch):
    (tmp_path / "rag.yaml").write_text(
        yaml.safe_dump(
            {
                "search": {
                    "vector_weight": 0,
                    "bm25_weight": 0,
                    "score_weight": 0,
                }
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(_knowledge_store, "settings", settings_for(tmp_path))
    with pytest.raises(ValueError, match="at least one positive"):
        KnowledgeStore()


def test_embedding_client_is_lazy_and_uses_project_config(tmp_path, monkeypatch):
    fake_client = Mock()
    constructor = Mock(return_value=fake_client)
    monkeypatch.setattr(_knowledge_store, "OpenAIEmbeddings", constructor)
    service = configured_service(tmp_path, monkeypatch, Mock(), api_key="secret")

    assert service._embeddings is None
    assert service._embedding_client() is fake_client
    assert service._embedding_client() is fake_client
    constructor.assert_called_once_with(
        model="text-embedding-3-small",
        api_key="secret",
        base_url=_knowledge_store.settings.deepseek_base_url,
        dimensions=3,
    )


def test_embedding_client_is_disabled_without_api_key(tmp_path, monkeypatch):
    service = configured_service(tmp_path, monkeypatch, Mock())

    assert service._embedding_client() is None
    assert service._embed_documents(["one", "two"]) == [None, None]


def test_embedding_failure_degrades_each_chunk_to_none(tmp_path, monkeypatch):
    client = Mock()
    client.embed_documents.side_effect = RuntimeError("offline")
    service = configured_service(tmp_path, monkeypatch, Mock(), api_key="secret")
    monkeypatch.setattr(service, "_embedding_client", lambda: client)

    assert service._embed_documents(["one", "two"]) == [None, None]


def test_add_persists_metadata_and_indexes_chunks(tmp_path, monkeypatch):
    persistence = Mock()
    service = configured_service(tmp_path, monkeypatch, persistence)
    monkeypatch.setattr(service, "split_text", lambda text, type: ["chunk-a", "chunk-b"])
    monkeypatch.setattr(
        service, "_embed_documents", lambda chunks: [[1, 0, 0], [0, 1, 0]]
    )

    entry_id = service.add(
        "Title",
        "Body",
        category="docs",
        tags=["rag"],
        source="guide.md",
        project_id="project-a",
    )

    record = persistence.insert_entry.call_args.args[0]
    assert record["id"] == entry_id
    assert record["project_id"] == "project-a"
    persistence.replace_chunks.assert_called_once_with(
        entry_id,
        "Title",
        "docs",
        ["rag"],
        ["chunk-a", "chunk-b"],
        [[1, 0, 0], [0, 1, 0]],
    )


def test_update_only_reindexes_searchable_fields(tmp_path, monkeypatch):
    persistence = Mock()
    persistence.update_entry.return_value = True
    persistence.get_entry.return_value = {
        "id": "entry-1",
        "title": "Updated",
        "content": "Body",
        "category": "docs",
        "tags": [],
        "source": "",
    }
    service = configured_service(tmp_path, monkeypatch, persistence)
    index = Mock()
    monkeypatch.setattr(service, "_index", index)

    assert service.update("entry-1", score=25)
    index.assert_not_called()
    assert service.update("entry-1", content="Changed")
    index.assert_called_once_with(persistence.get_entry.return_value)


def test_update_does_not_reindex_missing_or_unchanged_entry(tmp_path, monkeypatch):
    persistence = Mock()
    persistence.update_entry.side_effect = [False, True]
    persistence.get_entry.return_value = None
    service = configured_service(tmp_path, monkeypatch, persistence)
    index = Mock()
    monkeypatch.setattr(service, "_index", index)

    assert not service.update("missing", content="Changed")
    assert service.update("deleted-concurrently", content="Changed")
    index.assert_not_called()


def test_search_applies_configured_three_way_weights_and_filters(tmp_path, monkeypatch):
    persistence = Mock()
    persistence.search_fts.return_value = [("first", 0.8), ("second", 0.4)]
    persistence.search_vectors.return_value = [("first", 0.2), ("second", 0.9)]
    entries = {
        "first": {
            "id": "first", "project_id": "p1", "category": "docs", "score": 100
        },
        "second": {
            "id": "second", "project_id": "p1", "category": "docs", "score": 0
        },
    }
    persistence.get_entry.side_effect = entries.get
    service = configured_service(
        tmp_path,
        monkeypatch,
        persistence,
        search={"bm25_weight": 0.5, "vector_weight": 0.3, "score_weight": 0.2},
        api_key="secret",
    )
    embedding_client = Mock()
    embedding_client.embed_query.return_value = [1, 0, 0]
    monkeypatch.setattr(service, "_embedding_client", lambda: embedding_client)
    monkeypatch.setattr(service, "cleanup", Mock(return_value=0))

    results = service.search("query", category="docs", top_k=2, project_id="p1")

    assert [item["id"] for item in results] == ["first", "second"]
    assert results[0]["_search_score"] == pytest.approx(0.66)
    assert results[1]["_search_score"] == pytest.approx(0.47)
    persistence.search_fts.assert_called_once_with("query", 6, "docs", "p1")
    persistence.search_vectors.assert_called_once_with([1, 0, 0], 6)


def test_search_degrades_to_bm25_when_vector_query_fails(tmp_path, monkeypatch):
    persistence = Mock()
    persistence.search_fts.return_value = [("entry-1", 0.7)]
    persistence.search_vectors.side_effect = RuntimeError("vec unavailable")
    persistence.get_entry.return_value = {
        "id": "entry-1",
        "project_id": "",
        "category": "general",
        "score": 0,
    }
    service = configured_service(
        tmp_path, monkeypatch, persistence, api_key="secret"
    )
    client = Mock()
    client.embed_query.return_value = [1, 0, 0]
    monkeypatch.setattr(service, "_embedding_client", lambda: client)
    monkeypatch.setattr(service, "cleanup", Mock(return_value=0))

    results = service.search("query")

    assert [item["id"] for item in results] == ["entry-1"]
    assert results[0]["_vector_score"] == 0


def test_search_discards_entries_outside_requested_scope(tmp_path, monkeypatch):
    persistence = Mock()
    persistence.search_fts.return_value = [("wrong-project", 1), ("wrong-category", 1)]
    persistence.get_entry.side_effect = {
        "wrong-project": {
            "id": "wrong-project", "project_id": "p2", "category": "docs", "score": 0
        },
        "wrong-category": {
            "id": "wrong-category", "project_id": "p1", "category": "other", "score": 0
        },
    }.get
    service = configured_service(tmp_path, monkeypatch, persistence)
    monkeypatch.setattr(service, "cleanup", Mock(return_value=0))

    assert service.search("query", category="docs", project_id="p1") == []


def test_import_file_resolves_workspace_path_and_indexes_content(tmp_path, monkeypatch):
    source = tmp_path / "docs" / "guide.md"
    source.parent.mkdir()
    source.write_text("# Guide\n\nUseful content", encoding="utf-8")
    service = configured_service(tmp_path, monkeypatch, Mock())
    add = Mock(return_value="entry-1")
    monkeypatch.setattr(service, "add", add)

    result = service.import_file("docs/guide.md", "docs", project_id="p1")

    assert result["entries"] == ["entry-1"]
    add.assert_called_once_with(
        title="guide",
        content="# Guide\n\nUseful content",
        category="docs",
        source="docs/guide.md",
        source_type="import",
        project_id="p1",
    )


def test_import_file_rejects_missing_and_empty_files(tmp_path, monkeypatch):
    service = configured_service(tmp_path, monkeypatch, Mock())
    with pytest.raises(FileNotFoundError):
        service.import_file("missing.md")

    empty = tmp_path / "empty.txt"
    empty.write_text("   ", encoding="utf-8")
    with pytest.raises(ValueError, match="为空"):
        service.import_file(str(empty))


def test_relation_feedback_stats_cleanup_and_crud_delegate_to_store(
    tmp_path, monkeypatch
):
    persistence = Mock()
    persistence.delete_entry.return_value = True
    persistence.get_entry.return_value = {"id": "entry-1"}
    persistence.list_entries.return_value = [{"id": "entry-1"}]
    persistence.add_relation.return_value = "relation-1"
    persistence.get_relations.return_value = [{"id": "relation-1"}]
    persistence.add_feedback.return_value = 75.0
    persistence.stats.return_value = {"total": 1}
    persistence.cleanup_expired.return_value = 2
    service = configured_service(tmp_path, monkeypatch, persistence)

    assert service.delete("entry-1")
    assert service.get("entry-1") == {"id": "entry-1"}
    assert service.list("docs", 5, 1, "p1") == [{"id": "entry-1"}]
    assert service.add_relation("a", "b", "related") == "relation-1"
    assert service.get_relations("a") == [{"id": "relation-1"}]
    assert service.add_feedback("entry-1", "up") == 75.0
    assert service.stats("p1") == {"total": 1}
    assert service.cleanup() == 2

    with pytest.raises(ValueError, match="up.*down"):
        service.add_feedback("entry-1", "invalid")
