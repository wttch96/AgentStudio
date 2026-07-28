
from app.services.rag._knowledge_store import DEFAULT_RAG_CONFIG


def test_default_rag_weights_are_valid():
    search = DEFAULT_RAG_CONFIG["search"]
    assert sum(
        search[key] for key in ("vector_weight", "bm25_weight", "score_weight")
    ) == 1.0
