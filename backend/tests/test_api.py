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
    response = client.get("/api/agents")
    assert response.status_code == 200
    names = {agent["name"] for agent in response.json["items"]}
    assert names == {"frontend-agent", "backend-agent", "netty-agent"}
    assert all(agent["builtin"] is True for agent in response.json["items"])


def test_skill_creation_and_agent_assignment(client):
    created = client.post(
        "/api/skills",
        json={
            "name": "netty-framing",
            "description": "处理 Netty 帧边界",
            "content": "使用长度字段解码器，并覆盖半包和超长帧测试。",
        },
    )
    assert created.status_code == 201

    agent = client.get("/api/agents/netty-agent").json
    agent["skills"] = ["netty-framing"]
    agent.pop("name")
    agent.pop("skill_count")
    agent.pop("builtin")
    updated = client.put("/api/agents/netty-agent", json=agent)
    assert updated.status_code == 200
    assert updated.json["skills"] == ["netty-framing"]
    assert updated.json["skill_count"] == 1


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

    config_path = client.application.extensions["services"].workspace.config_path
    assert config_path.exists()
    assert str(selected.resolve()) in config_path.read_text(encoding="utf-8")


def test_workspace_rejects_missing_directory(client):
    missing = Path(client.get("/api/workspace").json["path"]) / "does-not-exist"
    response = client.put("/api/workspace", json={"path": str(missing)})
    assert response.status_code == 400
    assert "不存在" in response.json["error"]


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

    config_path = client.application.extensions["services"].scheduler.config_path
    assert config_path.exists()
    assert '"max_concurrent_agents": 4' in config_path.read_text(encoding="utf-8")

    invalid = client.put("/api/scheduler", json={**payload, "max_concurrent_agents": 0})
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
    plan_event = next(event for event in run["events"] if event["type"] == "plan.created")
    planned_agents = {task["agent"] for task in plan_event["payload"]["tasks"]}
    assert planned_agents == {"frontend-agent", "backend-agent", "netty-agent"}


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
    response = client.post("/api/runs", json={"objective": "/backend 检查后端接口"})
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
    assert [task["agent"] for task in plan["payload"]["tasks"]] == ["backend-agent"]


def test_failed_subtask_can_be_retried_without_replanning(client):
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
    assert response.status_code == 202
    run_id = response.json["id"]

    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        run = client.get(f"/api/runs/{run_id}").json
        if run["status"] in {"completed", "failed", "cancelled"}:
            break
        time.sleep(0.1)

    plan = next(event for event in run["events"] if event["type"] == "plan.created")
    task = plan["payload"]["tasks"][0]
    assert task["id"] == "retry-parse-packet"
    assert task["agent"] == "netty-agent"
    assert task["write_scope"] == ["netty/"]
    assert "达到最大交互轮次" in task["objective"]


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
    assert services.store.list_events(run_id) == []


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
