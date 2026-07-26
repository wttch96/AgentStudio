"""Flow engine domain models — YAML-defined pipeline types.

Supports two schema versions:
  - v1.0 (legacy): nodes with depends_on, executed via topological waves
  - v1.1+ (extended): nodes + conditions + loops + parallels, compiled to LangGraph
"""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator


class FlowNode(BaseModel):
    """A single agent execution node."""

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


class ConditionBlock(BaseModel):
    """If/Else conditional branching.

    The condition is a Jinja2 expression evaluated against the blackboard at runtime.
    e.g. ``blackboard.code_score > 0.8``
    """

    id: str = Field(pattern=r"^[a-zA-Z0-9_-]+$")
    condition: str = Field(min_length=1, max_length=2000)
    then_branch: str = Field(min_length=1, max_length=256)  # node id or block id
    else_branch: str | None = None  # node id or block id (optional)


class LoopBlock(BaseModel):
    """While-loop construct.

    The body is re-executed while the condition evaluates to true.
    ``max_iterations`` acts as a hard safety cap.
    """

    id: str = Field(pattern=r"^[a-zA-Z0-9_-]+$")
    condition: str = Field(min_length=1, max_length=2000)
    body: str = Field(min_length=1, max_length=256)  # node id or block id
    max_iterations: int = Field(default=10, ge=1, le=100)


class ParallelBlock(BaseModel):
    """Parallel execution of multiple nodes/blocks.

    All items are launched concurrently via LangGraph Send fan-out.
    A barrier collects results before proceeding.
    """

    id: str = Field(pattern=r"^[a-zA-Z0-9_-]+$")
    items: list[str] = Field(min_length=1, max_length=20)  # node ids or block ids
    max_concurrency: int | None = None


class FlowSynthesize(BaseModel):
    """Final answer template for a flow."""

    template: str = Field(min_length=1, max_length=8000)


class FlowDefinition(BaseModel):
    """Complete YAML-defined flow pipeline.

    Supports two modes:
    - Legacy (v1.0): only ``nodes`` with ``depends_on`` — topo-wave execution
    - Extended (v1.1+): ``nodes`` + ``conditions`` + ``loops`` + ``parallels``
      + ``steps`` — compiled to a LangGraph subgraph
    """

    name: str = Field(pattern=r"^[a-zA-Z0-9_-]+$")
    description: str = Field(default="", max_length=500)
    version: str = Field(default="1.0", pattern=r"^\d+\.\d+$")
    keywords: list[str] = Field(default_factory=list)
    nodes: list[FlowNode] = Field(default_factory=list, min_length=1)
    conditions: list[ConditionBlock] = Field(default_factory=list)
    loops: list[LoopBlock] = Field(default_factory=list)
    parallels: list[ParallelBlock] = Field(default_factory=list)
    steps: list[str] = Field(default_factory=list)
    synthesize: FlowSynthesize | None = None

    # ------------------------------------------------------------------
    # 向后兼容属性
    # ------------------------------------------------------------------

    @property
    def is_extended(self) -> bool:
        """Returns True if this flow uses the extended schema (v1.1+)."""
        return bool(
            self.conditions or self.loops or self.parallels or self.steps
        )

    @property
    def all_block_ids(self) -> set[str]:
        """Collect all block ids for reference validation."""
        ids: set[str] = {n.id for n in self.nodes}
        ids.update(c.id for c in self.conditions)
        ids.update(l.id for l in self.loops)
        ids.update(p.id for p in self.parallels)
        return ids

    # ------------------------------------------------------------------
    # 校验
    # ------------------------------------------------------------------

    @model_validator(mode="after")
    def validate_graph(self) -> "FlowDefinition":
        # --- Node ID uniqueness ---
        ids = {n.id for n in self.nodes}
        if len(ids) != len(self.nodes):
            raise ValueError("流程节点 ID 不能重复")

        # --- Block ID uniqueness ---
        block_ids = set()
        for c in self.conditions:
            if c.id in block_ids:
                raise ValueError(f"条件块 ID 重复: {c.id}")
            block_ids.add(c.id)
        for l in self.loops:
            if l.id in block_ids:
                raise ValueError(f"循环块 ID 重复: {l.id}")
            block_ids.add(l.id)
        for p in self.parallels:
            if p.id in block_ids:
                raise ValueError(f"并行块 ID 重复: {p.id}")
            block_ids.add(p.id)

        all_ids = ids | block_ids

        # --- depends_on references ---
        for node in self.nodes:
            unknown = set(node.depends_on) - all_ids
            if unknown:
                raise ValueError(
                    f"节点 {node.id} 引用了未知依赖: {sorted(unknown)}"
                )
            if node.id in node.depends_on:
                raise ValueError(f"节点 {node.id} 不能依赖自身")

        # --- condition references ---
        for c in self.conditions:
            if c.then_branch not in all_ids:
                raise ValueError(
                    f"条件块 {c.id} 的 then_branch 引用了未知目标: {c.then_branch}"
                )
            if c.else_branch and c.else_branch not in all_ids:
                raise ValueError(
                    f"条件块 {c.id} 的 else_branch 引用了未知目标: {c.else_branch}"
                )

        # --- loop references ---
        for l in self.loops:
            if l.body not in all_ids:
                raise ValueError(
                    f"循环块 {l.id} 的 body 引用了未知目标: {l.body}"
                )

        # --- parallel references ---
        for p in self.parallels:
            for item in p.items:
                if item not in all_ids:
                    raise ValueError(
                        f"并行块 {p.id} 的 items 引用了未知目标: {item}"
                    )

        # --- steps references ---
        for s in self.steps:
            if s not in all_ids:
                raise ValueError(f"steps 引用了未知目标: {s}")

        # --- Cycle detection (depends_on only — blocks are acyclic by construction) ---
        visiting: set[str] = set()
        visited: set[str] = set()
        dep_map = {node.id: node.depends_on for node in self.nodes}

        def visit(node_id: str) -> None:
            if node_id in visiting:
                raise ValueError("流程节点依赖中存在循环")
            if node_id in visited:
                return
            visiting.add(node_id)
            for dep in dep_map.get(node_id, []):
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
