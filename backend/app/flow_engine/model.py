"""Flow engine domain models — YAML-defined pipeline types."""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator


class FlowNode(BaseModel):
    """A single node in a flow pipeline."""

    id: str = Field(pattern=r"^[a-zA-Z0-9_-]+$")
    agent: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=120)
    objective: str = Field(min_length=1, max_length=8000)  # Jinja2 template
    write_scope: list[str] = Field(default_factory=list)
    timeout_seconds: int = Field(default=300, ge=30, le=3600)
    max_turns: int = Field(default=10, ge=1, le=100)
    interruptible: bool = True
    retry_on_failure: bool = False
    depends_on: list[str] = Field(default_factory=list)


class FlowSynthesize(BaseModel):
    """Final answer template for a flow."""

    template: str = Field(min_length=1, max_length=8000)


class FlowDefinition(BaseModel):
    """Complete YAML-defined flow pipeline."""

    name: str = Field(pattern=r"^[a-zA-Z0-9_-]+$")
    description: str = Field(default="", max_length=500)
    version: str = Field(default="1.0", pattern=r"^\d+\.\d+$")
    keywords: list[str] = Field(default_factory=list)
    nodes: list[FlowNode] = Field(default_factory=list, min_length=1)
    synthesize: FlowSynthesize | None = None

    @model_validator(mode="after")
    def validate_graph(self) -> "FlowDefinition":
        ids = {node.id for node in self.nodes}
        if len(ids) != len(self.nodes):
            raise ValueError("流程节点 ID 不能重复")

        for node in self.nodes:
            unknown = set(node.depends_on) - ids
            if unknown:
                raise ValueError(
                    f"节点 {node.id} 引用了未知依赖: {sorted(unknown)}"
                )
            if node.id in node.depends_on:
                raise ValueError(f"节点 {node.id} 不能依赖自身")

        # Cycle detection
        visiting: set[str] = set()
        visited: set[str] = set()
        dep_map = {node.id: node.depends_on for node in self.nodes}

        def visit(node_id: str) -> None:
            if node_id in visiting:
                raise ValueError("流程节点依赖中存在循环")
            if node_id in visited:
                return
            visiting.add(node_id)
            for dep in dep_map[node_id]:
                visit(dep)
            visiting.discard(node_id)
            visited.add(node_id)

        for node_id in ids:
            visit(node_id)
        return self


class FlowTrace(BaseModel):
    """Single node execution trace — input/output persisted per run."""

    run_id: str
    node_id: str
    sequence: int = 0
    rendered_prompt: str = ""
    inputs_json: str = "{}"
    outputs_json: str | None = None
    result_status: str = "pending"  # pending | running | completed | failed | cancelled
    started_at: str | None = None
    completed_at: str | None = None
    duration_ms: int | None = None
