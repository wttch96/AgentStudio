import threading
from pathlib import Path

import pytest
import yaml

from app.domain.models import AgentResult
from app.flow_engine.model import FlowDefinition
from app.flow_engine.yaml_compiler import YamlCompiler


REPOSITORY = Path(__file__).resolve().parents[2]
DEMO_PATH = REPOSITORY / "templates" / "project" / "flows" / "refund-review.yaml"


class FakeExecutor:
    registry = None

    def __init__(self) -> None:
        self.executed: list[str] = []
        self.parallel_barrier = threading.Barrier(2)

    def execute(
        self,
        run_id,
        task,
        dependency_results,
        cancel_event,
        workspace_root,
        max_turns,
        timeout_seconds,
        project_id,
    ):
        if task.id in {"policy_check", "fulfillment_check"}:
            self.parallel_barrier.wait(timeout=2)
        self.executed.append(task.id)
        return AgentResult(
            task_id=task.id,
            agent=task.agent,
            status="completed",
            summary=f"{task.id} completed",
        )


def load_demo() -> FlowDefinition:
    return FlowDefinition.model_validate(
        yaml.safe_load(DEMO_PATH.read_text(encoding="utf-8"))
    )


@pytest.mark.parametrize(
    ("amount", "risk", "selected", "skipped"),
    [
        (299, "low", "auto_approve", "manual_review"),
        (1200, "high", "manual_review", "auto_approve"),
    ],
)
def test_refund_demo_runs_parallel_checks_then_selects_one_branch(
    amount,
    risk,
    selected,
    skipped,
):
    executor = FakeExecutor()
    flow = load_demo()
    output = YamlCompiler(executor=executor).compile(flow).invoke({
        "run_id": f"refund-{risk}",
        "flow_name": flow.name,
        "workspace_root": str(REPOSITORY),
        "project_id": "",
        "inputs": {
            "order_id": "ORD-001",
            "refund_amount": amount,
            "risk_level": risk,
            "reason": "商品破损",
        },
        "blackboard": {},
        "loop_counters": {},
    })

    task_ids = [result["task_id"] for result in output["results"]]
    assert task_ids[0] == "intake"
    assert {"policy_check", "fulfillment_check"} <= set(task_ids)
    assert selected in task_ids
    assert skipped not in task_ids
    assert len(task_ids) == 4


def test_existing_extended_flow_compiles():
    path = REPOSITORY / "templates" / "project" / "flows" / "feature-delivery.yaml"
    flow = FlowDefinition.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))

    YamlCompiler().compile(flow)
