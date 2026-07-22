"""使用 DeepSeek 将自然语言目标转换为受约束的任务 DAG。"""

from __future__ import annotations

import json
from pathlib import Path

from openai import OpenAI

from app.config import Settings
from app.domain.models import AgentResult, DagTask, TaskDag
from app.services.deepseek_usage import DeepSeekUsageService


SYSTEM_PROMPT = """
你是这个软件工程系统的主脑，负责架构判断、任务拆解、依赖决策和执行验收。
请把用户目标拆成小而清晰的有向无环任务图。
只允许把执行任务交给三个 Claude Agent：frontend-agent、backend-agent、netty-agent。

要求：
1. 架构分析、接口边界和验收策略由你直接体现在任务目标与依赖中，不创建独立架构 Agent。
2. Web 前端任务交给 frontend-agent，Flask/Python 后端任务交给 backend-agent。
3. Java Netty 的连接、数据接收、协议解析、编码和发送任务交给 netty-agent。
4. 不要把普通 Flask 业务接口交给 netty-agent，也不要把 Netty 传输链路交给 backend-agent。
5. 每个执行 Agent 必须自行完成相关测试和代码自检，不创建独立测试或审查 Agent。
6. 无文件冲突的任务可以并行，有真实协议或接口依赖时再建立 depends_on。
7. write_scope 使用相对于项目根目录的路径前缀。
8. 输出 JSON，结构严格符合提供的 schema，不要输出 Markdown。
9. 当目标是分析、审查或修改“整个项目”，且明显跨越前端和后端时，必须分别创建
   frontend-agent 与 backend-agent 节点；二者没有真实接口前置关系时 depends_on 置空，允许并行。
10. 不要把跨领域的整项目工作全部塞给一个 Agent。尊重用户明确排除的领域，例如用户说
    “不用 Netty”时不要创建 netty-agent 节点；与目标无关的 Agent 也不要为了凑并发而调用。
11. 若提供了上游对话上下文，当前指令是对已有任务的延续。必须结合上游输出理解“继续”、
    “按刚才方案修改”等指代，并把 Agent 节点目标写成无需猜测的完整指令。
""".strip()

SUMMARY_PROMPT = """
你是软件工程系统的主脑。请根据原始目标、任务计划和 Claude Agent 执行结果做最终验收与汇总。
明确说明完成了什么、验证情况、失败或跳过内容以及仍存在的风险。不要编造未执行的测试或修改。
使用简洁的中文 Markdown。
""".strip()


class DeepSeekPlanner:
    def __init__(self, settings: Settings, usage: DeepSeekUsageService | None = None) -> None:
        self.settings = settings
        self.usage = usage

    def create_dag(
        self,
        objective: str,
        workspace_root: str | None = None,
        run_id: str | None = None,
        continuation_context: str = "",
    ) -> TaskDag:
        """生成 DAG；未设置密钥时返回具有代表性的演示图。"""

        if not self.settings.deepseek_api_key:
            return self._enforce_requested_agents(self._demo_dag(objective), objective)

        client = OpenAI(
            api_key=self.settings.deepseek_api_key,
            base_url=self.settings.deepseek_base_url,
        )
        schema = TaskDag.model_json_schema()
        response = client.chat.completions.create(
            model=self.settings.deepseek_model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"用户目标：\n{objective}\n\n"
                        f"上游对话上下文：\n{continuation_context or '无，这是新任务'}\n\n"
                        f"工作区结构（仅名称，最多两层）：\n"
                        f"{self._workspace_context(workspace_root)}\n\n"
                        f"必须符合这个 JSON Schema：\n{json.dumps(schema, ensure_ascii=False)}"
                    ),
                },
            ],
            response_format={"type": "json_object"},
            temperature=0.1,
        )
        if self.usage:
            self.usage.record(response, phase="planning", run_id=run_id)
        content = response.choices[0].message.content
        if not content:
            raise RuntimeError("DeepSeek 返回了空计划")
        dag = TaskDag.model_validate_json(content)
        return self._enforce_requested_agents(dag, objective)

    @staticmethod
    def _workspace_context(workspace_root: str | None) -> str:
        """只读取两层路径名称，帮助主脑识别前端、后端和 Netty 子项目。"""

        if not workspace_root:
            return "未提供工作区目录"
        root = Path(workspace_root)
        ignored = {
            ".git",
            ".env",
            ".venv",
            "node_modules",
            "dist",
            "build",
            "__pycache__",
            "instance",
        }
        lines: list[str] = []
        try:
            children = sorted(root.iterdir(), key=lambda item: item.name.lower())[:80]
            for child in children:
                if child.name in ignored:
                    continue
                lines.append(f"- {child.name}{'/' if child.is_dir() else ''}")
                if not child.is_dir():
                    continue
                try:
                    nested = sorted(
                        (item for item in child.iterdir() if item.name not in ignored),
                        key=lambda item: item.name.lower(),
                    )[:30]
                    lines.extend(
                        f"  - {item.name}{'/' if item.is_dir() else ''}" for item in nested
                    )
                except OSError:
                    lines.append("  - [无法读取]")
        except OSError:
            return "工作区目录无法读取"
        return "\n".join(lines) or "工作区为空"

    @classmethod
    def _enforce_requested_agents(cls, dag: TaskDag, objective: str) -> TaskDag:
        """把用户明确点名的领域从软提示提升为确定性的 DAG 约束。"""

        lowered = objective.lower().replace(" ", "")
        exclusions = {
            "frontend-agent": any(
                phrase in lowered
                for phrase in ("不用前端", "不要前端", "不需要前端", "仅后端", "只看后端", "只改后端")
            ),
            "backend-agent": any(
                phrase in lowered
                for phrase in ("不用后端", "不要后端", "不需要后端", "仅前端", "只看前端", "只改前端")
            ),
            "netty-agent": any(
                phrase in lowered for phrase in ("不用netty", "不要netty", "不需要netty", "排除netty")
            ),
        }
        requested = {
            "frontend-agent": "前后端" in lowered
            or any(word in lowered for word in ("前端", "frontend", "vue", "react", "页面")),
            "backend-agent": "前后端" in lowered
            or any(word in lowered for word in ("后端", "backend", "flask", "服务端", "api")),
            "netty-agent": "netty" in lowered,
        }

        has_explicit_scope = any(requested.values())
        removed_ids = {
            task.id
            for task in dag.tasks
            if exclusions.get(task.agent, False)
            or (has_explicit_scope and not requested.get(task.agent, False))
        }
        tasks = [
            task.model_copy(
                update={
                    "depends_on": [
                        dependency
                        for dependency in task.depends_on
                        if dependency not in removed_ids
                    ]
                }
            )
            for task in dag.tasks
            if task.id not in removed_ids
        ]
        present = {task.agent for task in tasks}
        read_only = any(
            phrase in lowered
            for phrase in ("看看", "分析", "审查", "了解", "干了啥", "做了什么", "不要动", "不用动")
        )
        domain_details = {
            "frontend-agent": ("frontend", "前端项目", ["frontend/"]),
            "backend-agent": ("backend", "后端项目", ["backend/"]),
            "netty-agent": ("netty", "Netty 数据链路", ["netty/"]),
        }
        existing_ids = {task.id for task in tasks}
        for agent, is_requested in requested.items():
            if not is_requested or exclusions[agent] or agent in present:
                continue
            base_id, label, write_scope = domain_details[agent]
            task_id = f"required-{base_id}"
            suffix = 2
            while task_id in existing_ids:
                task_id = f"required-{base_id}-{suffix}"
                suffix += 1
            tasks.append(
                DagTask(
                    id=task_id,
                    title=f"{'分析' if read_only else '完成'}{label}",
                    objective=(
                        f"独立聚焦{label}完成用户目标：{objective}。"
                        "只处理本领域并给出可供主脑汇总的明确结果。"
                    ),
                    agent=agent,
                    depends_on=[],
                    write_scope=[] if read_only else write_scope,
                )
            )
            existing_ids.add(task_id)
            present.add(agent)

        return TaskDag(summary=dag.summary, tasks=tasks)

    def summarize(
        self,
        objective: str,
        dag: TaskDag,
        results: list[AgentResult],
        run_id: str | None = None,
        continuation_context: str = "",
    ) -> str:
        """由 DeepSeek 主脑验收并汇总执行结果；演示模式使用确定性汇总。"""

        if not self.settings.deepseek_api_key:
            return self._demo_summary(dag, results)

        client = OpenAI(
            api_key=self.settings.deepseek_api_key,
            base_url=self.settings.deepseek_base_url,
        )
        response = client.chat.completions.create(
            model=self.settings.deepseek_model,
            messages=[
                {"role": "system", "content": SUMMARY_PROMPT},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "objective": objective,
                            "upstream_context": continuation_context,
                            "dag": dag.model_dump(),
                            "results": [result.model_dump() for result in results],
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            temperature=0.1,
        )
        if self.usage:
            self.usage.record(response, phase="synthesis", run_id=run_id)
        content = response.choices[0].message.content
        if not content:
            raise RuntimeError("DeepSeek 返回了空汇总")
        return content

    @staticmethod
    def _demo_dag(objective: str) -> TaskDag:
        """演示模式用三个执行 Agent 验证并行分发和结果汇合。"""

        short_objective = objective[:800]
        return TaskDag(
            summary=f"围绕“{short_objective[:60]}”生成本地演示任务图",
            tasks=[
                DagTask(
                    id="backend",
                    title="实现并验证后端能力",
                    objective=f"按主脑拆解实现后端部分并完成后端测试：{short_objective}",
                    agent="backend-agent",
                    write_scope=["backend/"],
                ),
                DagTask(
                    id="frontend",
                    title="实现并验证前端体验",
                    objective=f"按主脑拆解实现前端部分并完成前端检查：{short_objective}",
                    agent="frontend-agent",
                    write_scope=["frontend/"],
                ),
                DagTask(
                    id="netty-transport",
                    title="实现并验证 Netty 数据链路",
                    objective=(
                        "按主脑拆解实现 Netty 数据接收、协议解析和编码发送，"
                        f"并完成相关测试：{short_objective}"
                    ),
                    agent="netty-agent",
                    write_scope=["netty/"],
                ),
            ],
        )

    @staticmethod
    def _demo_summary(dag: TaskDag, results: list[AgentResult]) -> str:
        result_by_id = {result.task_id: result for result in results}
        lines = [f"任务计划：{dag.summary}", ""]
        for task in dag.tasks:
            result = result_by_id.get(task.id)
            if result:
                lines.append(f"- [{result.status}] {task.title}：{result.summary}")
            else:
                lines.append(f"- [skipped] {task.title}：依赖失败或运行已取消")
        return "\n".join(lines)
