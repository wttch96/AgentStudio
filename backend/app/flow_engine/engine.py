"""Deterministic YAML-defined pipeline execution engine.

Reuses existing executors (Claude, RAG, File) but replaces LangGraph's dynamic
planning/ scheduling with a topologically-sorted wave-based loop.
"""

from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any

from app.agents.chat_executor import ChatExecutor
from app.agents.claude_executor import ClaudeAgentExecutor
from app.agents.file_agent_executor import FileAgentExecutor
from app.agents.rag_executor import RAGAgentExecutor
from app.domain.configuration import SchedulerConfiguration
from app.domain.models import AgentResult, DagTask
from app.events.publisher import EventPublisher
from app.flow_engine.model import FlowDefinition, FlowNode, FlowTrace
from app.flow_engine.templates import FlowTemplateRenderer
from app.services.interrupt_router import InterruptRouter
from app.storage.sqlite_store import SQLiteStore


class FlowEngine:
    """Execute a FlowDefinition using deterministic wave-based scheduling."""

    def __init__(
        self,
        executor: ClaudeAgentExecutor,
        events: EventPublisher,
        store: SQLiteStore,
        flow_store: Any = None,
        rag_executor: RAGAgentExecutor | None = None,
        chat_executor: ChatExecutor | None = None,
        file_agent_executor: FileAgentExecutor | None = None,
    ) -> None:
        self.executor = executor
        self.events = events
        self.store = store
        self.flow_store = flow_store
        self.rag_executor = rag_executor
        self.chat_executor = chat_executor
        self.file_agent_executor = file_agent_executor
        self.template_renderer = FlowTemplateRenderer()

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def execute(
        self,
        flow: FlowDefinition,
        inputs: dict[str, str],
        run_id: str,
        workspace_root: str,
        cancel_event: threading.Event,
        interrupt_router: InterruptRouter | None,
        scheduler: SchedulerConfiguration,
        project_id: str = "",
    ) -> dict[str, Any]:
        """Run a flow to completion, returning final_answer and results."""
        waves = self._topological_waves(flow.nodes)
        results: dict[str, AgentResult] = {}
        all_traces: list[dict] = []

        # Emit plan.created so frontend composables (useNodeGraph, useRunTimeline)
        # can render flow nodes in DAG and timeline views.
        self.events.emit(
            run_id, "plan.created",
            payload={
                "flow_name": flow.name,
                "flow_version": flow.version,
                "stage": "execution",
                "tasks": [
                    {
                        "id": n.id,
                        "title": n.title,
                        "objective": n.objective,
                        "agent": n.agent,
                        "depends_on": n.depends_on,
                        "write_scope": n.write_scope,
                    }
                    for n in flow.nodes
                ],
                "summary": flow.description,
                "coordination_contract": (
                    f"流程 {flow.name} v{flow.version}: {flow.description}"
                ),
            },
        )
        self.events.emit(
            run_id, "flow.started",
            payload={
                "flow_name": flow.name,
                "flow_version": flow.version,
                "node_count": len(flow.nodes),
                "wave_count": len(waves),
            },
        )
        _seq_counter = 0

        for wave_idx, wave in enumerate(waves):
            # ---- Interrupt check before each wave ----
            if interrupt_router:
                self._check_interrupts(run_id, interrupt_router, cancel_event)
            if cancel_event.is_set():
                break

            node_ids = [n.id for n in wave]
            self.events.emit(
                run_id, "wave.started",
                payload={
                    "wave": wave_idx + 1,
                    "task_ids": node_ids,
                    "flow_name": flow.name,
                },
            )

            # Render prompts (dependency results are available from prior waves)
            tasks: dict[str, DagTask] = {}
            for node in wave:
                dep_results = self._dependency_results(node, results)
                rendered_objective = self.template_renderer.render_node(
                    node.objective, inputs, results
                )
                task = DagTask(
                    id=node.id,
                    title=node.title,
                    objective=rendered_objective,
                    agent=node.agent,
                    depends_on=node.depends_on,
                    write_scope=node.write_scope,
                )
                tasks[node.id] = task
                # Save initial trace
                trace = {
                    "run_id": run_id,
                    "node_id": node.id,
                    "sequence": _seq_counter,
                    "rendered_prompt": rendered_objective,
                    "inputs_json": json.dumps(inputs, ensure_ascii=False),
                    "result_status": "pending",
                }
                _seq_counter += 1
                all_traces.append(trace)
                self.store.save_flow_trace(trace)

            # ---- Execute wave in parallel ----
            with ThreadPoolExecutor(max_workers=scheduler.max_concurrent_agents) as pool:
                futures = {}
                for node in wave:
                    dag_task = tasks[node.id]
                    dep_results = self._dependency_results(node, results)

                    # Per-node pause check
                    if node.interruptible and interrupt_router:
                        interrupt_router.wait_for_node_resume(
                            run_id, node.id, cancel_event,
                        )
                    if cancel_event.is_set():
                        break

                    # Select executor
                    active_executor = self._resolve_executor(dag_task.agent, project_id)
                    max_turns = node.max_turns or scheduler.agent_max_turns
                    timeout_s = node.timeout_seconds or scheduler.agent_timeout_seconds

                    # Mark trace as running
                    for t in all_traces:
                        if t["node_id"] == node.id:
                            t["result_status"] = "running"
                            t["started_at"] = datetime.now(timezone.utc).isoformat()
                            self.store.save_flow_trace(t)

                    # Submit
                    future = pool.submit(
                        active_executor.execute,
                        run_id,
                        dag_task,
                        dep_results,
                        cancel_event,
                        workspace_root,
                        max_turns,
                        timeout_s,
                        project_id,
                    )
                    futures[future] = node.id

                # Collect results as they complete
                for future in as_completed(futures):
                    node_id = futures[future]
                    try:
                        result = future.result()
                    except Exception as exc:
                        result = AgentResult(
                            task_id=node_id,
                            agent=tasks[node_id].agent,
                            status="failed",
                            summary="节点执行异常",
                            error=f"{type(exc).__name__}: {exc}",
                        )
                    results[node_id] = result
                    # Update trace
                    for t in all_traces:
                        if t["node_id"] == node_id:
                            t["outputs_json"] = result.model_dump_json()
                            t["result_status"] = result.status
                            t["completed_at"] = datetime.now(timezone.utc).isoformat()
                            if result.started_at and t.get("started_at"):
                                try:
                                    start = datetime.fromisoformat(result.started_at)
                                    end = datetime.fromisoformat(t["completed_at"])
                                    t["duration_ms"] = int((end - start).total_seconds() * 1000)
                                except (ValueError, TypeError):
                                    pass
                            self.store.save_flow_trace(t)

            self.events.emit(
                run_id, "wave.completed",
                payload={
                    "wave": wave_idx + 1,
                    "task_ids": node_ids,
                    "flow_name": flow.name,
                },
            )

        # ---- Synthesize final answer ----
        final_answer = self._synthesize(flow, inputs, results)

        self.events.emit(
            run_id, "flow.completed",
            payload={
                "flow_name": flow.name,
                "final_answer": final_answer[:500],
                "node_statuses": {nid: r.status for nid, r in results.items()},
            },
        )

        return {
            "final_answer": final_answer,
            "results": [r.model_dump() for r in results.values()],
            "flow_name": flow.name,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _topological_waves(nodes: list[FlowNode]) -> list[list[FlowNode]]:
        """Group nodes into execution waves by dependency depth."""
        node_map = {n.id: n for n in nodes}
        in_degree: dict[str, int] = {n.id: len(n.depends_on) for n in nodes}
        waves: list[list[FlowNode]] = []
        processed: set[str] = set()

        while len(processed) < len(nodes):
            wave = [
                node_map[nid]
                for nid, deg in in_degree.items()
                if deg == 0 and nid not in processed
            ]
            if not wave:
                # Should not happen (validated for cycles), but guard
                break
            waves.append(wave)
            for n in wave:
                processed.add(n.id)
                # Decrease in-degree of dependents
                for other in nodes:
                    if n.id in other.depends_on:
                        in_degree[other.id] -= 1

        return waves

    @staticmethod
    def _dependency_results(
        node: FlowNode, results: dict[str, AgentResult]
    ) -> list[AgentResult]:
        """Collect completed results for a node's dependencies."""
        return [results[dep] for dep in node.depends_on if dep in results]

    def _resolve_executor(self, agent_name: str, project_id: str):
        """Select the right executor based on agent type."""
        profile = self.executor.registry.get(project_id, agent_name)
        agent_type = getattr(profile, "agent_type", "claude")
        if agent_type == "rag" and self.rag_executor:
            return self.rag_executor
        if agent_type == "chat" and self.chat_executor:
            return self.chat_executor
        if agent_type == "file-ops" and self.file_agent_executor:
            return self.file_agent_executor
        return self.executor

    def _synthesize(
        self, flow: FlowDefinition, inputs: dict, results: dict[str, AgentResult]
    ) -> str:
        """Build final answer from synthesize template or fallback."""
        if flow.synthesize:
            return self.template_renderer.render_synthesize(
                flow.synthesize.template, inputs, results
            )
        # Fallback: concatenate all results
        parts = []
        for nid, result in results.items():
            icon = "✅" if result.status == "completed" else "❌"
            parts.append(f"{icon} **{nid}**: {result.summary[:300]}")
        return "\n\n".join(parts) or "流程已完成，无结果输出。"

    # ---- Interrupt helpers ----

    @staticmethod
    def _check_interrupts(
        run_id: str,
        interrupt_router: InterruptRouter,
        cancel_event: threading.Event,
    ) -> None:
        """Process pending interrupt commands at wave boundaries."""
        pending = interrupt_router.check_and_clear(run_id)
        for cmd in pending:
            action = cmd.get("action", "")
            if action == "abort":
                cancel_event.set()
                return

    # ---- Flow store loader (used by RunManager) ----

    def _flow_store_loader(self, name: str) -> FlowDefinition | None:
        """Load a flow from the flow store (used by RunManager to avoid circular imports)."""
        if self.flow_store:
            try:
                return self.flow_store.load(name)
            except (KeyError, Exception):
                return None
        return None
