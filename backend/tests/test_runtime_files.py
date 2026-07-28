from app.storage.runtime_files import RuntimeFiles


def test_runtime_files_are_human_readable_and_append_events(tmp_path):
    store = RuntimeFiles(tmp_path)

    store.save_state("run-1", {"status": "running", "objective": "test"})
    store.append_event("run-1", {"sequence": 1, "type": "run.started"})
    store.append_event("run-1", {"sequence": 2, "type": "run.completed"})

    assert store.load_state("run-1") == {"status": "running", "objective": "test"}
    assert store.list_events("run-1") == [
        {"sequence": 1, "type": "run.started"},
        {"sequence": 2, "type": "run.completed"},
    ]
    assert (tmp_path / "runs" / "run-1" / "events.jsonl").is_file()


def test_settings_paths_are_scoped_to_current_project(tmp_path):
    from app.config import Settings

    workspace = tmp_path / "workspace"
    current = workspace / ".workspace" / "current-project.yaml"
    current.parent.mkdir(parents=True)
    current.write_text("project_id: demo\n", encoding="utf-8")
    settings = Settings(workspace_root=workspace)

    project_dir = workspace / ".workspace" / "demo"
    assert settings.runtime_dir == project_dir
    assert settings.database_path == project_dir / "db" / "rag.db"
