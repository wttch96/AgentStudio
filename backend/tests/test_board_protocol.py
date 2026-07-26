from pathlib import Path

from app.agents.todo_agent import TodoStore
from app.services.blackboard_store import BlackboardStore
from app.storage.sqlite_store import SQLiteStore


def test_todo_board_tracks_contract_results_and_workload(tmp_path: Path):
    board = BlackboardStore(SQLiteStore(tmp_path / "board.db"))
    todos = TodoStore(board)
    board.init("run-1")
    todos.init("run-1", [
        {
            "id": "design",
            "title": "冻结契约",
            "content": "冻结契约",
            "assigned_to": "api-designer",
            "status": "ready",
            "acceptance_criteria": ["接口字段明确"],
        },
        {
            "id": "implement",
            "title": "实现接口",
            "content": "实现接口",
            "assigned_to": "flask-backend",
            "status": "backlog",
            "depends_on": ["design"],
        },
    ])

    assert [item.id for item in todos.ready("run-1")] == ["design"]
    assert todos.workload("run-1") == {"api-designer": 1, "flask-backend": 1}

    result = todos.apply_result("run-1", "design", {
        "status": "completed",
        "artifacts": [{"type": "api", "path_or_id": "contract:v1"}],
        "decisions": [{"decision": "使用 JSON", "reason": "兼容"}],
        "risks": [],
        "verification_performed": ["schema validation"],
        "verification_result": "passed",
    }, "api-designer")

    assert result is not None
    assert result.status == "review"
    assert result.artifacts[0]["path_or_id"] == "contract:v1"
    assert result.verification["result"] == "passed"


def test_todo_board_accepts_planner_dict_and_upserts_by_id(tmp_path: Path):
    board = BlackboardStore(SQLiteStore(tmp_path / "board.db"))
    todos = TodoStore(board)
    board.init("run-2")
    todos.init("run-2", [{
        "id": "discover",
        "title": "发现项目",
        "content": "发现项目",
        "assigned_to": "rag",
    }])

    added = todos.add("run-2", {
        "id": "implement",
        "title": "实现功能",
        "objective": "实现并验证功能",
        "agent": "claude",
        "depends_on": ["discover"],
        "acceptance_criteria": ["构建通过"],
    }, "planner")
    todos.add("run-2", {
        "id": "implement",
        "title": "实现并测试功能",
        "agent": "claude",
        "depends_on": ["discover"],
    }, "planner")

    items = todos.list("run-2")
    assert added.assigned_to == "claude"
    assert [item.id for item in items] == ["discover", "implement"]
    assert items[1].title == "实现并测试功能"
