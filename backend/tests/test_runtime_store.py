from app.storage.runtime_store import RuntimeStore


def test_runtime_store_persists_non_rag_data_as_project_files(tmp_path):
    store = RuntimeStore(tmp_path)
    run = store.create_run("run-1", "objective", "/workspace", project_id="demo")
    store.update_run(run["id"], "running")
    store.insert_memory({
        "id": "memory-1",
        "run_id": run["id"],
        "conversation_id": run["conversation_id"],
        "level": "project",
        "phase": "test",
        "summary": "remember this",
        "created_at": "2026-07-28T00:00:00+00:00",
    })
    store.insert_interrupt_command({
        "id": "interrupt-1",
        "run_id": run["id"],
        "target": "all",
        "action": "pause",
    })
    store.save_flow_trace({
        "run_id": run["id"],
        "node_id": "node-1",
        "sequence": 1,
        "result_status": "completed",
    })

    assert store.get_run(run["id"])["status"] == "running"
    assert store.query_memories(run["conversation_id"])[0]["id"] == "memory-1"
    assert store.get_pending_interrupts(run["id"])[0]["id"] == "interrupt-1"
    assert store.list_flow_traces(run["id"])[0]["node_id"] == "node-1"
    assert (tmp_path / "runs" / "run-1" / "run.json").is_file()
    assert (tmp_path / "runs" / "run-1" / "interrupts.json").is_file()
    assert (tmp_path / "runs" / "run-1" / "flow-traces.json").is_file()
    assert (tmp_path / "memory" / "memories.jsonl").is_file()


def test_sqlite_schema_contains_only_knowledge_tables(tmp_path):
    from app.services.rag._store import RAGStore

    store = RAGStore(tmp_path / "rag.db", vector_dimensions=3)
    with store.database.connection_context():
        connection = store.database.connection()
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
            ).fetchall()
        }

    application_tables = {
        name for name in tables
        if not name.startswith("sqlite_")
        and not name.startswith("knowledge_fts_")
        and not name.startswith("knowledge_vec_")
    }
    assert application_tables == {
        "knowledge_entries",
        "knowledge_chunks",
        "knowledge_relations",
        "knowledge_feedback",
        "knowledge_fts",
        "knowledge_vec",
    }
