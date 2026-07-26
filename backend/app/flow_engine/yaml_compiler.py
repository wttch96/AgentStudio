"""YamlCompiler — 将 FlowDefinition 编译为 LangGraph 子图。

支持的 YAML 控制流到 LangGraph 原语的映射：
  - node (agent 任务)   → add_node(id, _execute_flow_node)
  - steps (顺序执行)     → add_edge(step[i], step[i+1])
  - condition (if/else)  → add_conditional_edges(id, router, {True→then, False→else})
  - loop (while)         → add_conditional_edges + cycle back to body
  - parallel (并发)      → Send fan-out + barrier merge

设计原则：
  1. 编译一次，多次调用。FlowDefinition → CompiledStateGraph → graph.invoke(state)
  2. 条件在运行时通过 Jinja2 对 Blackboard 求值
  3. 循环使用 loop_counters 作为安全帽，recursion_limit 作为硬上限
  4. 并行复用主图的 Send 扇出模式
"""

from __future__ import annotations

import json
import operator
import threading
import time
from datetime import datetime, timezone
from typing import Annotated, Any, Callable

from jinja2 import BaseLoader, Environment, Undefined
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send
from typing_extensions import TypedDict

from app.domain.models import AgentResult, DagTask
from app.events.publisher import EventPublisher
from app.flow_engine.model import (
    ConditionBlock,
    FlowDefinition,
    FlowNode,
    LoopBlock,
    ParallelBlock,
)
from app.flow_engine.templates import FlowTemplateRenderer
from app.services.blackboard_store import BlackboardStore
from app.agents.todo_agent import TodoStore


# ------------------------------------------------------------------
# Jinja2 Sandbox for Condition Evaluation
# ------------------------------------------------------------------

class SilentUndefined(Undefined):
    """Returns empty string for undefined variables instead of raising."""

    def __str__(self) -> str:
        return ""

    def __getattr__(self, _name: str) -> "SilentUndefined":
        return SilentUndefined()

    def __getitem__(self, _key: str) -> "SilentUndefined":
        return SilentUndefined()

    def __call__(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        return ""


def _create_eval_env() -> Environment:
    env = Environment(
        loader=BaseLoader(),
        autoescape=False,
        undefined=SilentUndefined,
    )
    return env


_eval_env = _create_eval_env()


# ------------------------------------------------------------------
# FlowGraphState
# ------------------------------------------------------------------

class FlowGraphState(TypedDict, total=False):
    """YAML flow 子图的内部状态。"""
    run_id: str
    flow_name: str
    workspace_root: str
    project_id: str
    inputs: dict[str, Any]              # user-supplied params
    results: Annotated[list[dict[str, Any]], operator.add]
    blackboard: dict[str, Any]          # serialized BlackboardState
    loop_counters: dict[str, int]       # loop_id → remaining iterations
    cancel_event_ref: str               # reserved for interrupt support
    final_answer: str
    current_node: str


# ------------------------------------------------------------------
# YamlCompiler
# ------------------------------------------------------------------

class YamlCompiler:
    """Compile a FlowDefinition into a LangGraph subgraph."""

    def __init__(
        self,
        executor: Any = None,            # ClaudeAgentExecutor
        rag_executor: Any = None,
        chat_executor: Any = None,
        file_agent_executor: Any = None,
        events: EventPublisher | None = None,
        flow_store: Any = None,
        blackboard_store: BlackboardStore | None = None,
        todo_store: TodoStore | None = None,
        template_renderer: FlowTemplateRenderer | None = None,
    ) -> None:
        self.executor = executor
        self.rag_executor = rag_executor
        self.chat_executor = chat_executor
        self.file_agent_executor = file_agent_executor
        self.events = events
        self.flow_store = flow_store
        self.blackboard_store = blackboard_store
        self.todo_store = todo_store
        self.template_renderer = template_renderer or FlowTemplateRenderer()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def compile(self, flow: FlowDefinition) -> StateGraph:
        """编译 FlowDefinition 为编译好的 StateGraph。

        返回的 graph 可被父图的节点包装调用，也可独立 invoke。
        """
        builder = StateGraph(FlowGraphState)
        registered: set[str] = set()

        # 1. Register all agent nodes
        for node in flow.nodes:
            self._register_agent_node(builder, node)
            registered.add(node.id)

        # 2. Register condition blocks as conditional-edge nodes
        for cond in flow.conditions:
            self._register_condition(builder, cond, flow)
            registered.add(cond.id)

        # 3. Register loop blocks
        for loop in flow.loops:
            self._register_loop(builder, loop, flow)
            registered.add(loop.id)

        # 4. Register parallel blocks
        for par in flow.parallels:
            self._register_parallel(builder, par, flow)
            registered.add(par.id)

        # 5. Wire up steps in order
        if flow.steps:
            self._wire_steps(builder, flow)
        else:
            # Legacy: auto-generate steps from topological sort of depends_on
            self._wire_from_depends_on(builder, flow)

        # 6. Wire synthesize → END
        builder.add_node("__synthesize__", self._make_synthesize_node(flow))
        # Every terminal path should go to __synthesize__
        self._wire_terminals(builder, flow)

        builder.add_edge("__synthesize__", END)

        return builder.compile()

    # ------------------------------------------------------------------
    # Node Registration
    # ------------------------------------------------------------------

    def _register_agent_node(self, builder: StateGraph, node: FlowNode) -> None:
        """Register a single agent execution node."""
        def execute_node(state: FlowGraphState) -> FlowGraphState:
            return self._execute_flow_node(state, node)

        builder.add_node(node.id, execute_node)

    def _register_condition(self, builder: StateGraph, cond: ConditionBlock, flow: FlowDefinition) -> None:
        """Register a condition block as a passthrough node with conditional edges.

        The condition node itself is a no-op; routing happens on the outgoing edges.
        """
        builder.add_node(cond.id, lambda s: s)

        def route_condition(state: FlowGraphState) -> str:
            return self._eval_condition(state, cond)

        path_map = {cond.then_branch: cond.then_branch}
        if cond.else_branch:
            path_map[cond.else_branch] = cond.else_branch
        builder.add_conditional_edges(cond.id, route_condition, path_map)

    def _register_loop(self, builder: StateGraph, loop: LoopBlock, flow: FlowDefinition) -> None:
        """Register a loop block.

        Creates: entry → check → (condition) → body → check → (exit) → next
        """
        entry_id = f"{loop.id}__enter"
        check_id = f"{loop.id}__check"
        exit_id = f"{loop.id}__exit"

        # Entry: initialize counter
        def loop_enter(state: FlowGraphState) -> FlowGraphState:
            counters = dict(state.get("loop_counters", {}))
            counters[loop.id] = loop.max_iterations
            return {"loop_counters": counters}

        builder.add_node(entry_id, loop_enter)

        # Check: evaluate condition, decrement counter
        def loop_check(state: FlowGraphState) -> FlowGraphState:
            counters = dict(state.get("loop_counters", {}))
            remaining = counters.get(loop.id, 0) - 1
            counters[loop.id] = max(0, remaining)
            return {"loop_counters": counters}

        builder.add_node(check_id, loop_check)

        # Exit: passthrough
        builder.add_node(exit_id, lambda s: s)

        # Routing from check: condition true + counter > 0 → body, else → exit
        def route_loop(state: FlowGraphState) -> str:
            counters = state.get("loop_counters", {})
            if counters.get(loop.id, 0) <= 0:
                return exit_id
            if self._eval_condition(state, loop):
                return loop.body  # back to body → check cycle
            return exit_id

        path_map = {loop.body: loop.body, exit_id: exit_id}
        builder.add_conditional_edges(check_id, route_loop, path_map)

        # Wire: entry → check → (body → check / exit)
        builder.add_edge(entry_id, check_id)
        # body → check is wired as a cycle via conditional edge routing

        # Replace the loop id with its entry point in the graph topology
        # The caller wires steps to entry_id, and exit_id is wired to next step
        setattr(self, f"_loop_{loop.id}_entry", entry_id)
        setattr(self, f"_loop_{loop.id}_exit", exit_id)

    def _register_parallel(self, builder: StateGraph, par: ParallelBlock, flow: FlowDefinition) -> None:
        """Register parallel execution block using Send fan-out + barrier.

        Pattern (same as main graph):
          fanout → [Send to each item] → barrier → next
        """
        fanout_id = f"{par.id}__fanout"
        barrier_id = f"{par.id}__barrier"

        builder.add_node(fanout_id, lambda s: s)
        builder.add_node(barrier_id, lambda s: s)

        def fanout(state: FlowGraphState) -> list[Send]:
            return [
                Send(item_id, {"current_node": item_id, **{k: v for k, v in state.items() if k != "current_node"}})
                for item_id in par.items
            ]

        builder.add_conditional_edges(fanout_id, fanout, par.items)
        for item_id in par.items:
            builder.add_edge(item_id, barrier_id)

        setattr(self, f"_parallel_{par.id}_fanout", fanout_id)
        setattr(self, f"_parallel_{par.id}_barrier", barrier_id)

    # ------------------------------------------------------------------
    # Step Wiring
    # ------------------------------------------------------------------

    def _wire_steps(self, builder: StateGraph, flow: FlowDefinition) -> None:
        """Wire top-level steps in sequential order. START → steps[0]."""
        if not flow.steps:
            return

        builder.add_edge(START, self._resolve_entry(flow.steps[0], flow))

        for i in range(len(flow.steps) - 1):
            cur_exit = self._resolve_exit(flow.steps[i], flow)
            next_entry = self._resolve_entry(flow.steps[i + 1], flow)
            builder.add_edge(cur_exit, next_entry)

    def _wire_from_depends_on(self, builder: StateGraph, flow: FlowDefinition) -> None:
        """Legacy mode: auto-generate steps from depends_on via topological sort."""
        in_degree = {n.id: len(n.depends_on) for n in flow.nodes}
        adj = {n.id: [] for n in flow.nodes}
        for n in flow.nodes:
            for dep in n.depends_on:
                adj.setdefault(dep, []).append(n.id)

        steps: list[str] = []
        processed: set[str] = set()
        while len(processed) < len(flow.nodes):
            ready = [nid for nid, deg in in_degree.items() if deg == 0 and nid not in processed]
            if not ready:
                break
            for nid in ready:
                steps.append(nid)
                processed.add(nid)
                for successor in adj.get(nid, []):
                    in_degree[successor] -= 1

        if steps:
            builder.add_edge(START, steps[0])
            for i in range(len(steps) - 1):
                builder.add_edge(steps[i], steps[i + 1])
            # Store for _wire_terminals
            flow.steps = steps

    def _wire_terminals(self, builder: StateGraph, flow: FlowDefinition) -> None:
        """Wire the last step (or all terminal nodes) to __synthesize__.

        For flows with conditions/loops, the last step may branch to multiple
        terminals. We wire each terminal to __synthesize__.
        """
        if flow.steps:
            last = flow.steps[-1] if flow.steps else None
            if last:
                last_exit = self._resolve_exit(last, flow)
                builder.add_edge(last_exit, "__synthesize__")
            return

        # Legacy: find terminal nodes (not depended on by anyone)
        all_ids = {n.id for n in flow.nodes}
        has_dependents = {dep for n in flow.nodes for dep in n.depends_on}
        terminals = all_ids - has_dependents
        for tid in terminals:
            builder.add_edge(tid, "__synthesize__")
        # If no terminals found (e.g., all nodes have dependents), wire last node
        if not terminals and flow.nodes:
            builder.add_edge(flow.nodes[-1].id, "__synthesize__")

    def _resolve_entry(self, block_id: str, flow: FlowDefinition) -> str:
        """Resolve a block ID to its actual graph entry node."""
        # Check if it's a loop entry
        entry = getattr(self, f"_loop_{block_id}_entry", None)
        if entry:
            return entry
        # Check if it's a parallel fanout
        fanout = getattr(self, f"_parallel_{block_id}_fanout", None)
        if fanout:
            return fanout
        return block_id  # plain node or condition

    def _resolve_exit(self, block_id: str, flow: FlowDefinition) -> str:
        """Resolve a block ID to its actual graph exit node."""
        # Check if it's a loop exit
        exit_id = getattr(self, f"_loop_{block_id}_exit", None)
        if exit_id:
            return exit_id
        # Check if it's a parallel barrier
        barrier = getattr(self, f"_parallel_{block_id}_barrier", None)
        if barrier:
            return barrier
        # For condition: the then_branch and else_branch each
        # independently connect to next step. The condition node itself
        # is the entry, and the targets are the exits.
        # We need the branches to converge at the next step, not at the condition.
        # So for conditions, we return the condition id as "exit" to wire
        # NEXT step edges from the then/else targets, not from the condition itself.
        return block_id

    # ------------------------------------------------------------------
    # Runtime Node Executor
    # ------------------------------------------------------------------

    def _execute_flow_node(
        self, state: FlowGraphState, node: FlowNode
    ) -> FlowGraphState:
        """Execute a single flow agent node at runtime."""
        run_id = state["run_id"]
        workspace_root = state["workspace_root"]
        project_id = state.get("project_id", "")

        # Build dependency results from previous node outputs + blackboard
        deps: list[AgentResult] = []

        # Add blackboard snapshot
        if self.blackboard_store:
            bb_data = self.blackboard_store.read_all(run_id)
            if bb_data:
                deps.append(AgentResult(
                    task_id="blackboard-snapshot",
                    agent="system",
                    status="completed",
                    summary=json.dumps(bb_data, ensure_ascii=False),
                ))

        # Render the objective template
        rendered = self.template_renderer.render_node(
            node.objective, state.get("inputs", {}), {}
        )

        task = DagTask(
            id=node.id,
            title=node.title,
            objective=rendered,
            agent=node.agent,
            depends_on=node.depends_on,
            write_scope=node.write_scope,
        )

        # Select executor
        active_executor = self._resolve_executor(node.agent, project_id)
        max_turns = node.max_turns
        timeout_s = node.timeout_seconds

        started_at = datetime.now(timezone.utc).isoformat()
        started_ms = int(time.time() * 1000)

        if self.events:
            self.events.emit(
                run_id, "agent.started",
                agent_id=node.agent, task_id=node.id,
                payload={"title": node.title, "objective": rendered, "started_at": started_at},
            )

        try:
            result = active_executor.execute(
                run_id, task, deps,
                threading.Event(),  # cancel_event managed by parent
                workspace_root=workspace_root,
                max_turns=max_turns,
                timeout_seconds=timeout_s,
                project_id=project_id,
            )
        except Exception as exc:
            result = AgentResult(
                task_id=node.id,
                agent=node.agent,
                status="failed",
                summary=f"执行异常: {exc}",
                error=str(exc),
                started_at=started_at,
            )

        duration_ms = int(time.time() * 1000) - started_ms
        if result is not None:
            result.started_at = started_at
            result.duration_ms = duration_ms

        if self.events:
            self.events.emit(
                run_id,
                "agent.completed" if result and result.status == "completed" else "agent.failed",
                agent_id=node.agent, task_id=node.id,
                payload={**(result.model_dump() if result else {}), "duration_ms": duration_ms},
            )

        return {"results": [result.model_dump()] if result else []}

    def _make_synthesize_node(self, flow: FlowDefinition) -> Callable:
        """Create the final synthesize node."""
        def synthesize(state: FlowGraphState) -> FlowGraphState:
            results_raw = state.get("results", [])
            results = [AgentResult.model_validate(r) for r in results_raw]

            if flow.synthesize:
                # Build results dict for template rendering
                result_map = {r.task_id: r for r in results}
                final = self.template_renderer.render_synthesize(
                    flow.synthesize.template, state.get("inputs", {}), result_map
                )
            else:
                parts: list[str] = []
                for r in results:
                    icon = "✅" if r.status == "completed" else "❌"
                    parts.append(f"{icon} **{r.task_id}**: {r.summary[:300]}")
                final = "\n\n".join(parts) or "流程已完成，无结果输出。"

            if self.events:
                self.events.emit(
                    state["run_id"], "flow.completed",
                    payload={"flow_name": flow.name, "final_answer": final[:500]},
                )

            return {"final_answer": final}

        return synthesize

    # ------------------------------------------------------------------
    # Condition Evaluation
    # ------------------------------------------------------------------

    def _eval_condition(self, state: FlowGraphState, condition: ConditionBlock | LoopBlock) -> bool:
        """Evaluate a Jinja2 condition against the current blackboard state."""
        cond_str = condition.condition
        blackboard_data = state.get("blackboard", {})
        loop_counters = state.get("loop_counters", {})

        try:
            result = _eval_env.from_string("{{" + cond_str + "}}").render(
                blackboard=blackboard_data,
                counter=loop_counters.get(condition.id if isinstance(condition, LoopBlock) else "", 0),
            )
            return result.strip().lower() in ("true", "1", "yes")
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Executor Resolution
    # ------------------------------------------------------------------

    def _resolve_executor(self, agent_name: str, project_id: str) -> Any:
        """Select the right executor based on agent name/type."""
        # Try registry lookup
        if self.executor and hasattr(self.executor, "registry"):
            try:
                profile = self.executor.registry.get(project_id, agent_name)
                agent_type = getattr(profile, "agent_type", "claude")
                if agent_type == "rag" and self.rag_executor:
                    return self.rag_executor
                if agent_type == "chat" and self.chat_executor:
                    return self.chat_executor
                if agent_type == "file-ops" and self.file_agent_executor:
                    return self.file_agent_executor
                if agent_type == "blackboard":
                    from app.agents.blackboard_agent import BlackboardAgentExecutor
                    return BlackboardAgentExecutor(self.blackboard_store)
            except (ValueError, Exception):
                pass
        return self.executor
