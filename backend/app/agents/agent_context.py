"""Agent 执行上下文构建与注入。

在执行前从 GraphState 中提取相关上下文，自动注入到 Agent Prompt 中，
避免每个 Agent 独立调用看板工具获取相同上下文。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from app.domain.models import AgentResult, DagTask, TaskDag


@dataclass
class AgentExecutionContext:
    """Agent 执行所需的所有上下文，统一打包。

    通过 to_prompt_xml() 生成格式化的 XML 上下文注入到 Agent prompt 中。
    """

    task: DagTask
    workspace_root: str
    agent_name: str = ""
    agent_type: str = ""
    agent_capabilities: tuple[str, ...] = ()
    agent_limitations: tuple[str, ...] = ()
    agent_tools: tuple[str, ...] = ()

    # 看板上下文
    board_task: dict[str, Any] | None = None
    board_snapshot: dict[str, Any] = field(default_factory=dict)

    # 上下游
    upstream_results: list[AgentResult] = field(default_factory=list)
    downstream_tasks: list[str] = field(default_factory=list)

    # 决策与产物
    relevant_decisions: list[dict[str, Any]] = field(default_factory=list)
    related_artifacts: list[dict[str, Any]] = field(default_factory=list)
    blockers: list[dict[str, Any]] = field(default_factory=list)

    # 协调
    coordination_contract: str = ""
    guidance: str = ""

    # 运行时限制
    max_iterations: int = 3
    allowed_tools: list[str] = field(default_factory=list)
    forbidden_actions: list[str] = field(default_factory=list)

    def to_prompt_xml(self) -> str:
        """生成 XML 格式的上下文注入块。"""
        sections: list[str] = []

        # Agent 身份
        identity = (
            f"<agent_identity>\n"
            f"  Agent: {self.agent_name}\n"
            f"  类型: {self.agent_type}\n"
            f"  能力: {', '.join(self.agent_capabilities) if self.agent_capabilities else '通用'}\n"
            f"  工作目录: {self.workspace_root}\n"
            f"</agent_identity>"
        )
        sections.append(identity)

        # 当前任务
        task_xml = (
            f"<current_task>\n"
            f"  ID: {self.task.id}\n"
            f"  标题: {self.task.title}\n"
            f"  目标: {self.task.objective}\n"
            f"  写入范围: {self.task.write_scope or '只读'}\n"
            f"  预期产物: {self.task.expected_outputs or '未单独声明'}\n"
            f"  验收标准: {self.task.acceptance_criteria or '完成目标并提供验证证据'}\n"
            f"  约束: {self.task.constraints or '无额外约束'}\n"
            f"  禁止操作: {self.task.forbidden_actions or '遵循系统安全规则'}\n"
            f"  最大迭代次数: {self.max_iterations}\n"
            f"</current_task>"
        )
        sections.append(task_xml)

        # 看板上下文
        if self.board_task or self.board_snapshot:
            board_parts = []
            if self.board_task:
                board_parts.append(
                    f"  当前看板任务: {json.dumps(self.board_task, ensure_ascii=False)[:500]}"
                )
            # Compact board snapshot
            if self.board_snapshot:
                compact = {}
                for k, v in self.board_snapshot.items():
                    if isinstance(v, str):
                        compact[k] = v[:200]
                    elif isinstance(v, dict):
                        compact[k] = {
                            sk: str(sv)[:100] for sk, sv in v.items()
                        }
                    else:
                        compact[k] = str(v)[:100]
                board_parts.append(
                    f"  看板快照: {json.dumps(compact, ensure_ascii=False)[:800]}"
                )
            board_xml = (
                f"<board_context>\n"
                + "\n".join(board_parts) +
                f"\n</board_context>"
            )
            sections.append(board_xml)

        # 上游结果
        if self.upstream_results:
            upstream_parts = []
            for r in self.upstream_results:
                summary_short = r.summary[:300] if r.summary else "(无摘要)"
                icon = "✓" if r.status == "completed" else "✗" if r.status == "failed" else "-"
                upstream_parts.append(
                    f"  {icon} [{r.task_id}] {r.agent}: {summary_short}"
                )
            upstream_xml = (
                f"<upstream_results>\n" +
                "\n".join(upstream_parts) +
                f"\n</upstream_results>"
            )
            sections.append(upstream_xml)
        else:
            sections.append("<upstream_results>无上游依赖</upstream_results>")

        # 下游消费者
        if self.downstream_tasks:
            sections.append(
                f"<downstream_tasks>\n  你的输出将被以下任务消费: {', '.join(self.downstream_tasks)}\n"
                f"  请确保输出格式与下游期望一致。\n</downstream_tasks>"
            )

        # 已有决策
        if self.relevant_decisions:
            dec_parts = []
            for d in self.relevant_decisions:
                dec_parts.append(
                    f"  - {d.get('decision', d.get('summary', str(d)[:200]))}"
                )
            sections.append(
                f"<decisions>\n" + "\n".join(dec_parts) + "\n</decisions>"
            )

        # 协调契约
        if self.coordination_contract:
            sections.append(
                f"<coordination_contract>\n{self.coordination_contract[:2000]}\n"
                f"  不得单方面修改以上契约。\n</coordination_contract>"
            )

        # 已有阻塞
        if self.blockers:
            block_parts = []
            for b in self.blockers:
                block_parts.append(
                    f"  - {b.get('description', str(b)[:200])}"
                )
            sections.append(
                f"<existing_blockers>\n" + "\n".join(block_parts) +
                f"\n  检查你的任务是否被以上阻塞影响。\n</existing_blockers>"
            )

        # 可用工具
        if self.allowed_tools or self.agent_tools:
            tools_list = self.allowed_tools if self.allowed_tools else list(self.agent_tools)
            sections.append(
                f"<available_tools>\n  {', '.join(tools_list)}\n</available_tools>"
            )

        # 输出要求
        output_xml = (
            "<output_schema>\n"
            "  最终回复必须以一个可解析 JSON 对象结束，至少包含:\n"
            "  - status: 执行状态\n"
            "  - summary: 执行摘要\n"
            "  - artifacts: 真实产物路径或黑板键\n"
            "  - changes: 修改的文件列表\n"
            "  - decisions: 做出的关键决策及其理由\n"
            "  - assumptions / risks / dependencies\n"
            "  - verification: performed、not_performed、result\n"
            "  - next_actions: 可执行的下一步\n"
            "</output_schema>"
        )
        sections.append(output_xml)

        return "\n\n".join(sections)

    def build_dependency_results(self) -> list[AgentResult]:
        """构建兼容现有 execute() 接口的 dependency_results。

        注入看板快照、协调契约和引导上下文作为虚拟 AgentResult。
        """
        results: list[AgentResult] = list(self.upstream_results)
        results.append(
            AgentResult(
                task_id="agent-execution-context",
                agent="system",
                status="completed",
                summary=self.to_prompt_xml(),
            )
        )

        if self.coordination_contract:
            results.append(
                AgentResult(
                    task_id="coordination-contract",
                    agent="brain",
                    status="completed",
                    summary=self.coordination_contract,
                )
            )

        if self.board_snapshot:
            results.append(
                AgentResult(
                    task_id="blackboard-snapshot",
                    agent="system",
                    status="completed",
                    summary=json.dumps(self.board_snapshot, ensure_ascii=False),
                )
            )

        if self.guidance:
            results.append(
                AgentResult(
                    task_id="user-guidance",
                    agent="system",
                    status="completed",
                    summary=self.guidance[-6000:],
                )
            )

        return results


class AgentContextBuilder:
    """从 GraphState 构建 AgentExecutionContext。

    在 worker 节点中调用，对相关信息进行筛选和压缩。
    """

    def __init__(
        self,
        blackboard_store: Any = None,
        todo_store: Any = None,
        agent_registry: Any = None,
    ) -> None:
        self._bb = blackboard_store
        self._todo = todo_store
        self._registry = agent_registry

    def build(
        self,
        state: dict[str, Any],
        task: DagTask,
        agent_profile: Any = None,
    ) -> AgentExecutionContext:
        """从 GraphState 和 DagTask 构建完整上下文。"""
        run_id = state.get("run_id", "")

        # Agent 信息
        agent_name = task.agent
        agent_type = "claude"
        capabilities: tuple[str, ...] = ()
        limitations: tuple[str, ...] = ()
        tools: tuple[str, ...] = ()

        if agent_profile is not None:
            agent_type = getattr(agent_profile, "agent_type", "claude")
            capabilities = getattr(agent_profile, "capabilities", ())
            limitations = getattr(agent_profile, "limitations", ())
            tools = getattr(agent_profile, "tools", ())

        # 上游依赖结果
        results_raw = state.get("results", [])
        all_results = [
            AgentResult.model_validate(r) if isinstance(r, dict) else r
            for r in results_raw
        ]
        upstream = [
            r for r in all_results
            if r.task_id in task.depends_on
        ]

        # 下游任务
        dag_raw = state.get("dag", {})
        try:
            dag = TaskDag.model_validate(dag_raw) if dag_raw else None
        except Exception:
            dag = None
        downstream = [
            t.id for t in (dag.tasks if dag else [])
            if task.id in t.depends_on
        ]

        # 看板快照
        board_snapshot: dict[str, Any] = {}
        if self._bb is not None:
            try:
                board_snapshot = self._bb.read_all(run_id)
            except Exception:
                pass

        # 看板中当前任务信息
        board_task: dict[str, Any] | None = None
        if self._todo is not None:
            try:
                todos = self._todo.list(run_id)
                for t in todos:
                    td = t.model_dump() if hasattr(t, "model_dump") else t
                    if td.get("id") == task.id:
                        board_task = td
                        break
            except Exception:
                pass

        # 已有决策
        decisions_raw = board_snapshot.get("all_reviews", [])
        relevant_decisions: list[dict[str, Any]] = (
            decisions_raw if isinstance(decisions_raw, list) else []
        )

        # 产物
        artifacts_raw = board_snapshot.get("all_results", [])
        related_artifacts: list[dict[str, Any]] = (
            artifacts_raw if isinstance(artifacts_raw, list) else []
        )

        # 阻塞
        blockers_raw = board_snapshot.get("blockers", [])
        blockers: list[dict[str, Any]] = (
            blockers_raw if isinstance(blockers_raw, list) else []
        )

        # 协调契约
        coordination_contract = ""
        if dag:
            coordination_contract = dag.coordination_contract

        return AgentExecutionContext(
            task=task,
            workspace_root=state.get("workspace_root", ""),
            agent_name=agent_name,
            agent_type=agent_type,
            agent_capabilities=capabilities,
            agent_limitations=limitations,
            agent_tools=tools,
            board_task=board_task,
            board_snapshot=board_snapshot,
            upstream_results=upstream,
            downstream_tasks=downstream,
            relevant_decisions=relevant_decisions,
            related_artifacts=related_artifacts,
            blockers=blockers,
            coordination_contract=coordination_contract,
            guidance=state.get("guidance", ""),
            max_iterations=getattr(agent_profile, "max_iterations", 3) if agent_profile else 3,
            allowed_tools=task.allowed_tools,
            forbidden_actions=task.forbidden_actions,
        )
