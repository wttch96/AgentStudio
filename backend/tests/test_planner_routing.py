"""测试用户显式领域要求不会被主脑的单节点计划吞掉。"""

from pathlib import Path

from app.agents.registry import AgentProfile
from app.domain.models import DagTask, TaskDag
from app.planning.deepseek_planner import DeepSeekPlanner


def backend_only_dag() -> TaskDag:
    return TaskDag(
        summary="分析项目",
        tasks=[
            DagTask(
                id="analyze-project",
                title="分析项目",
                objective="分析整体项目",
                agent="backend-agent",
            )
        ],
    )


def test_frontend_and_backend_request_enforces_two_parallel_agents():
    repaired = DeepSeekPlanner._enforce_requested_agents(
        backend_only_dag(),
        "不要修改代码，看看前后端两个项目具体干了啥",
    )

    assert {task.agent for task in repaired.tasks} == {
        "frontend-agent",
        "backend-agent",
    }
    assert all(task.depends_on == [] for task in repaired.tasks)
    assert all(task.write_scope == [] for task in repaired.tasks)


def test_explicit_netty_exclusion_removes_model_generated_node():
    dag = TaskDag(
        summary="分析前后端",
        tasks=[
            *backend_only_dag().tasks,
            DagTask(
                id="netty",
                title="分析 Netty",
                objective="分析 Netty",
                agent="netty-agent",
            ),
        ],
    )
    repaired = DeepSeekPlanner._enforce_requested_agents(
        dag,
        "分析前后端项目，不用 Netty",
    )
    assert {task.agent for task in repaired.tasks} == {
        "frontend-agent",
        "backend-agent",
    }


def test_workspace_context_is_shallow_and_ignores_secrets(tmp_path: Path):
    (tmp_path / "frontend").mkdir()
    (tmp_path / "frontend" / "package.json").write_text("{}", encoding="utf-8")
    (tmp_path / "backend").mkdir()
    (tmp_path / ".env").write_text("SECRET=value", encoding="utf-8")

    context = DeepSeekPlanner._workspace_context(str(tmp_path))

    assert "frontend/" in context
    assert "package.json" in context
    assert "backend/" in context
    assert ".env" not in context
    assert "SECRET" not in context


def test_discovery_dag_searches_only_explicit_frontend_and_backend_domains():
    planner = DeepSeekPlanner.__new__(DeepSeekPlanner)

    dag = planner.create_discovery_dag(
        "给现有前后端项目增加一个新 API 功能，不用 Netty",
        project_agents=[
            AgentProfile(name="frontend-agent", display_name="前端", sub_dir="frontend"),
            AgentProfile(name="backend-agent", display_name="后端", sub_dir="backend"),
        ],
    )

    assert {task.agent for task in dag.tasks} == {
        "frontend-agent",
        "backend-agent",
    }
    assert all(task.id.startswith("workspace-discovery-") for task in dag.tasks)
    assert all(task.write_scope == [] for task in dag.tasks)
    assert all("不要假设固定目录名" in task.objective for task in dag.tasks)


def test_agent_enforcement_preserves_brain_contract():
    dag = backend_only_dag().model_copy(
        update={"coordination_contract": "POST /api/items 使用统一请求和响应字段"}
    )

    repaired = DeepSeekPlanner._enforce_requested_agents(dag, "修改后端 API")

    assert repaired.coordination_contract == dag.coordination_contract
