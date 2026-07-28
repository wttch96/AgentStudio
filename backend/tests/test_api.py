import time
from pathlib import Path

from app.config import Settings


def test_health_is_local_only(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json == {"status": "ok", "access": "local-only"}


def test_status_never_exposes_keys(client):
    response = client.get("/api/status")
    assert response.status_code == 200
    assert "api_key" not in response.get_data(as_text=True).lower()
    assert response.json["demo_mode"] is True


def test_balance_reports_unconfigured_without_exposing_a_key(client):
    response = client.get("/api/deepseek/balance")

    assert response.status_code == 200
    assert response.json == {
        "configured": False,
        "available": False,
        "infos": [],
        "error": "DeepSeek API Key 未配置",
    }
    assert "api_key" not in response.get_data(as_text=True).lower()


def test_local_deepseek_usage_starts_empty(client):
    response = client.get("/api/deepseek/usage")

    assert response.status_code == 200
    assert response.json["local"] is True
    assert response.json["estimated"] is True
    assert response.json["today"]["total_tokens"] == 0
    assert response.json["month"]["estimated_cost_usd"] == "0.00000000"


def test_cc_switch_token_configures_claude():
    settings = Settings(
        deepseek_api_key="deepseek-test",
        anthropic_auth_token="PROXY_MANAGED",
        anthropic_base_url="http://127.0.0.1:15721",
    )
    assert settings.claude_configured is True
    assert settings.claude_route == "cc-switch"
    assert settings.demo_mode is False


def test_only_expected_execution_agents_are_registered(client):
    response = client.get("/api/agents", query_string={"project_id": "test-project"})
    assert response.status_code == 200
    agents = response.json["items"]
    names = {agent["name"] for agent in agents}
    assert {"frontend-agent", "backend-agent", "rag"} <= names
    assert "master-brain" not in names
    assert all("capabilities" in agent and "priority" in agent for agent in agents)


def test_project_has_no_persistent_mode(client):
    detail = client.get("/api/projects/test-project")
    assert detail.status_code == 200
    assert "mode" not in detail.json

    invalid = client.put(
        "/api/projects/test-project",
        json={"mode": "unsafe"},
    )
    assert invalid.status_code == 400
    assert "不能保存为项目属性" in invalid.json["error"]


def test_http_requests_include_request_id_and_lifecycle_logs(client, caplog):
    caplog.set_level("INFO", logger="app")

    response = client.get("/api/projects")

    assert response.status_code == 200
    assert response.headers["X-Request-ID"]
    messages = [record.getMessage() for record in caplog.records]
    assert any("http.started" in message for message in messages)
    assert any("http.completed" in message and "status=200" in message for message in messages)


def test_plan_conversation_mode_creates_plan_without_starting_agents(client):
    response = client.post(
        "/api/runs",
        json={
            "objective": "修改前后端并补充自动化测试",
            "project_id": "test-project",
            "mode": "plan",
        },
    )
    assert response.status_code == 202
    run_id = response.json["id"]

    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        run = client.get(f"/api/runs/{run_id}").json
        if run["status"] in {"completed", "failed", "cancelled"}:
            break
        time.sleep(0.1)

    assert run["status"] == "completed"
    assert "Plan 模式" in run["final_answer"]
    event_types = [event["type"] for event in run["events"]]
    assert "conversation.mode" in event_types
    assert "plan.created" in event_types
    assert "agent.started" not in event_types


def test_invalid_conversation_mode_is_rejected(client):
    response = client.post(
        "/api/runs",
        json={
            "objective": "修改一个接口",
            "project_id": "test-project",
            "mode": "unsafe",
        },
    )
    assert response.status_code == 400


def test_skill_creation_and_agent_assignment(client):
    created = client.post(
        "/api/skills",
        json={
            "name": "netty-framing",
            "description": "处理 Netty 帧边界",
            "content": "使用长度字段解码器，并覆盖半包和超长帧测试。",
            "project_id": "test-project",
        },
    )
    assert created.status_code == 201

    agent = client.get(
        "/api/agents/backend-agent", query_string={"project_id": "test-project"}
    ).json
    agent["skills"] = ["netty-framing"]
    updated = client.put(
        "/api/projects/test-project/agents/backend-agent",
        json={"skills": agent["skills"], "tools": ["Read", "Skill"]},
    )
    assert updated.status_code == 200
    assert updated.json["skills"] == ["netty-framing"]
    assert "tools" not in updated.json
    skill_path = (
        client.application.extensions["services"].settings.workspace_root
        / ".workspace" / "test-project" / "skills" / "netty-framing.yaml"
    )
    assert skill_path.is_file()


def test_workspace_can_be_selected_and_persisted(client):
    original = Path(client.get("/api/workspace").json["path"])
    selected = original / "selected-project"
    selected.mkdir()

    browse = client.get("/api/workspace/directories", query_string={"path": original})
    assert browse.status_code == 200
    assert str(selected) in {item["path"] for item in browse.json["directories"]}

    updated = client.put("/api/workspace", json={"path": str(selected)})
    assert updated.status_code == 200
    assert updated.json == {"path": str(selected.resolve())}
    assert client.get("/api/workspace").json["path"] == str(selected.resolve())

    config_path = (
        client.application.extensions["services"].settings.workspace_root
        / ".workspace" / "test-project" / "workspace.yaml"
    )
    assert config_path.exists()
    assert str(selected.resolve()) in config_path.read_text(encoding="utf-8")


def test_workspace_rejects_missing_directory(client):
    missing = Path(client.get("/api/workspace").json["path"]) / "does-not-exist"
    response = client.put("/api/workspace", json={"path": str(missing)})
    assert response.status_code == 400
    assert "不存在" in response.json["error"]


def test_deleting_current_project_clears_pointer_and_keeps_data(client):
    services = client.application.extensions["services"]
    project_dir = (
        services.settings.workspace_root / ".workspace" / "test-project"
    )

    response = client.delete("/api/projects/test-project")

    assert response.status_code == 204
    assert client.get("/api/projects/current").json == {"project_id": ""}
    assert project_dir.is_dir()
    assert not (project_dir / "project.yaml").exists()
    assert (project_dir / "agents").is_dir()


def test_scheduler_configuration_is_validated_and_persisted(client):
    current = client.get("/api/scheduler")
    assert current.status_code == 200
    assert current.json["max_concurrent_agents"] == 3

    payload = {
        "max_concurrent_agents": 4,
        "recursion_limit": 160,
        "agent_max_turns": 20,
        "agent_timeout_seconds": 1200,
    }
    updated = client.put("/api/scheduler", json=payload)
    assert updated.status_code == 200
    assert updated.json == payload
    assert client.get("/api/scheduler").json == payload

    config_path = (
        client.application.extensions["services"].settings.workspace_root
        / ".workspace" / "test-project" / "scheduler.yaml"
    )
    assert config_path.exists()
    assert "max_concurrent_agents: 4" in config_path.read_text(encoding="utf-8")

    invalid = client.put("/api/scheduler", json={**payload, "max_concurrent_agents": 0})
    assert invalid.status_code == 400


def test_brain_prompts_are_editable_and_persisted_locally(client):
    current = client.get("/api/brain")
    assert current.status_code == 200
    assert "任务分级" in current.json["orchestration_prompt"]
    default = client.get("/api/brain/default")
    assert default.status_code == 200
    assert default.json == current.json

    payload = {"orchestration_prompt": (
        "优先根据项目发现证据选择真实项目，再定义共享接口契约并拆分实施任务。"
        "汇总实际选择的项目、契约、改动、测试和遗留风险，不得编造结果。"
    )}
    updated = client.put("/api/brain", json=payload)
    assert updated.status_code == 200
    assert updated.json == payload
    assert client.get("/api/brain").json == payload
    assert client.get("/api/brain/default").json == default.json

    config_path = (
        client.application.extensions["services"].settings.workspace_root
        / ".workspace" / "test-project" / "brain.yaml"
    )
    assert config_path.exists()
    assert "共享接口契约" in config_path.read_text(encoding="utf-8")

    invalid = client.put("/api/brain", json={"orchestration_prompt": "太短"})
    assert invalid.status_code == 400


def test_demo_run_completes(client):
    response = client.post("/api/runs", json={"objective": "创建一个本地任务面板"})
    assert response.status_code == 202
    run_id = response.json["id"]

    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        run = client.get(f"/api/runs/{run_id}").json
        if run["status"] in {"completed", "failed"}:
            break
        time.sleep(0.1)

    assert run["status"] == "completed"
    assert run["workspace_root"] == client.get("/api/workspace").json["path"]
    event_types = {event["type"] for event in run["events"]}
    assert {"plan.created", "agent.started", "brain.synthesizing", "run.completed"} <= event_types
    plan_events = [event for event in run["events"] if event["type"] == "plan.created"]
    assert [event["payload"]["stage"] for event in plan_events] == [
        "discovery",
        "execution",
    ]
    plan_event = plan_events[-1]
    assert plan_event["payload"]["coordination_contract"]
    assert len(plan_event["payload"]["tasks"]) >= 3
    planned_agents = {task["agent"] for task in plan_event["payload"]["tasks"]}
    assert {"frontend-agent", "backend-agent"} <= planned_agents


def test_follow_up_run_inherits_upstream_context_and_workspace(client):
    services = client.application.extensions["services"]
    workspace = client.get("/api/workspace").json["path"]
    parent = services.store.create_run("parent-run", "先分析项目问题", workspace)
    services.events.emit(
        parent["id"],
        "agent.completed",
        agent_id="backend-agent",
        task_id="analysis",
        payload={"summary": "发现需要补充任务延续能力"},
    )
    services.store.update_run(
        parent["id"],
        "completed",
        final_answer="建议下一步实现对话链并继承上游输出。",
    )

    response = client.post(
        "/api/runs",
        json={"objective": "按刚才建议继续实现", "parent_run_id": parent["id"]},
    )

    assert response.status_code == 202
    child = response.json
    assert child["parent_run_id"] == parent["id"]
    assert child["conversation_id"] == parent["conversation_id"]
    assert child["turn_index"] == 2
    assert child["workspace_root"] == workspace
    context = services.runs._continuation_context(parent["id"])
    assert "先分析项目问题" in context
    assert "发现需要补充任务延续能力" in context
    assert "建议下一步实现对话链" in context

    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        child = client.get(f"/api/runs/{child['id']}").json
        if child["status"] in {"completed", "failed", "cancelled"}:
            break
        time.sleep(0.1)
    assert child["status"] == "completed"


def test_follow_up_rejects_an_active_upstream(client):
    services = client.application.extensions["services"]
    parent = services.store.create_run(
        "active-parent", "仍在处理上游", client.get("/api/workspace").json["path"]
    )

    response = client.post(
        "/api/runs",
        json={"objective": "现在继续", "parent_run_id": parent["id"]},
    )

    assert response.status_code == 409
    assert "仍在执行" in response.json["error"]


def test_direct_agent_command_bypasses_deepseek_planning(client):
    response = client.post("/api/runs", json={"objective": "/flask-backend 检查后端接口"})
    assert response.status_code == 202
    run_id = response.json["id"]

    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        run = client.get(f"/api/runs/{run_id}").json
        if run["status"] in {"completed", "failed", "cancelled"}:
            break
        time.sleep(0.1)

    assert run["status"] == "completed"
    event_types = {event["type"] for event in run["events"]}
    assert "planner.bypassed" in event_types
    assert "planner.started" not in event_types
    assert "brain.synthesizing" not in event_types
    plan = next(event for event in run["events"] if event["type"] == "plan.created")
    assert [task["agent"] for task in plan["payload"]["tasks"]] == ["flask-backend"]


def test_removed_retry_command_is_rejected(client):
    services = client.application.extensions["services"]
    workspace = client.get("/api/workspace").json["path"]
    parent = services.store.create_run("retry-parent", "实现协议功能", workspace)
    services.events.emit(
        parent["id"],
        "plan.created",
        payload={
            "summary": "协议任务",
            "tasks": [
                {
                    "id": "parse-packet",
                    "title": "解析数据包",
                    "objective": "实现 Netty 数据包解析",
                    "agent": "netty-agent",
                    "depends_on": [],
                    "write_scope": ["netty/"],
                }
            ],
        },
    )
    services.events.emit(
        parent["id"],
        "agent.failed",
        agent_id="netty-agent",
        task_id="parse-packet",
        payload={"summary": "解析失败", "error": "达到最大交互轮次"},
    )
    services.store.update_run(parent["id"], "completed", final_answer="节点失败，等待重试")

    response = client.post(
        "/api/runs",
        json={"objective": "/retry parse-packet", "parent_run_id": parent["id"]},
    )
    assert response.status_code == 400
    assert "Agent" in response.json["error"] or "不存在" in response.json["error"]


def test_single_task_can_be_aborted_without_cancelling_run(client):
    from app.services.todo_state import TodoStateOps

    services = client.application.extensions["services"]
    run = services.store.create_run("task-abort-run", "并行任务", "/tmp")
    state = {"run_id": run["id"], "todos": {}, "blackboard": {}}
    TodoStateOps(state).init([{
        "id": "frontend-task",
        "content": "实现前端",
        "assigned_to": "vue-frontend",
        "status": "in_progress",
    }])
    services.runs.save_graph_state(run["id"], state)

    response = client.post(
        f"/api/runs/{run['id']}/interrupt",
        json={"target": "task", "action": "abort", "target_task": "frontend-task"},
    )

    assert response.status_code == 202
    assert services.interrupt_router.is_task_aborted(run["id"], "frontend-task")
    saved = services.runs.load_graph_state(run["id"])
    assert TodoStateOps(saved).get("frontend-task").status == "cancelled"


def test_terminal_run_can_be_deleted_with_all_events(client):
    response = client.post("/api/runs", json={"objective": "创建可删除的本地任务记录"})
    run_id = response.json["id"]

    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        run = client.get(f"/api/runs/{run_id}").json
        if run["status"] in {"completed", "failed", "cancelled"}:
            break
        time.sleep(0.1)

    assert run["events"]
    assert client.delete(f"/api/runs/{run_id}").status_code == 204
    assert client.get(f"/api/runs/{run_id}").status_code == 404

    services = client.application.extensions["services"]
    assert services.events.list_events(run_id) == []


def test_active_run_must_not_be_deleted(client):
    run = client.post("/api/runs", json={"objective": "仍在执行的测试任务"}).json

    response = client.delete(f"/api/runs/{run['id']}")

    assert response.status_code == 409
    assert "先停止" in response.json["error"]
    assert client.post(f"/api/runs/{run['id']}/cancel").status_code == 202


def test_orphaned_active_run_can_be_stopped_and_deleted(client):
    services = client.application.extensions["services"]
    run = services.store.create_run("orphan-run", "重启遗留任务", "/tmp")

    stopped = client.post(f"/api/runs/{run['id']}/cancel")
    assert stopped.status_code == 202
    assert services.store.get_run(run["id"])["status"] == "cancelled"

    assert client.delete(f"/api/runs/{run['id']}").status_code == 204


def test_interrupted_runs_are_recovered_to_terminal_state(client):
    services = client.application.extensions["services"]
    services.store.create_run("interrupted-run", "被重启中断", "/tmp")

    assert services.store.recover_interrupted_runs() == 1
    recovered = services.store.get_run("interrupted-run")
    assert recovered["status"] == "failed"
    assert "进程已重启" in recovered["error"]
