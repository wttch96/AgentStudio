"""使用 DeepSeek 将自然语言目标转换为受约束的任务 DAG。"""

from __future__ import annotations

import json
from pathlib import Path

from openai import OpenAI

from app.config import Settings
from app.domain.models import AgentResult, DagTask, TaskDag
from app.services.brain_settings import BrainSettings
from app.services.deepseek_usage import DeepSeekUsageService


STRUCTURE_GUARD_BASE = """
你是 Agent Studio 的主脑编排器。**少即是多**——不要为简单问题创建任务。

## 输出规则（首要）

如果用户的请求是以下类型，你**必须只输出纯文本回复**，绝不输出 JSON，绝不创建任务：
- 闲聊对话（"你好"、"你是谁"、"今天怎么样"）
- 概念解释（"什么是 xxx"、"解释一下 xxx"）
- 能从训练数据直接回答的知识性问题
- 对已有执行结果的追问、澄清、分析或总结
- 纯分析建议，不涉及代码读写、文件操作或命令执行

**只有在用户目标明确要求执行具体操作时**，才输出 JSON 任务图：
- 读取/写入/编辑代码文件
- 运行命令或测试
- 检索知识库
- 搜索文件内容
- 目录浏览和文件管理

需要 Agent 操作时输出任务图，严格遵守以下协议：

1. 只使用可用 Agent 列表中列出的精确名称，不要编造 agent 名。
2. 分析和编码任务分配给 Claude/DeepSeek/文件操作 Agent；RAG Agent 用于知识检索。
3. 主脑自主决策何时读写 RAG——可以在任务前检索已有知识，也可以在任务后存储新发现。
4. 用户说"先...然后..."/"再..."时，then 后的任务 depends_on 于前面的任务。
5. 无真实依赖的任务可以并行；有数据或逻辑依赖时建立 depends_on。
6. write_scope 使用 Agent 声明的工作子目录，没有工作目录的 Agent 不限制写入范围。
7. 每个 Agent 自己完成测试和自检，不创建独立测试 Agent。
8. 不要把跨领域工作全部塞给一个 Agent；与目标无关的 Agent 不要调用。
9. 上游上下文是已有任务的延续，结合上游理解指代；不要重复已完成的工作。
10. 不要创建 workspace-discovery- 前缀的任务（发现阶段已完成）。
11. 跨项目接口写入 coordination_contract。
12. 输出 JSON 时不要用 markdown 代码块包裹，直接输出纯 JSON 对象。
""".strip()


def _fallback_dag(objective: str, project_agents: list | None = None) -> TaskDag:
    """当 JSON 解析失败时的兜底方案。"""
    agent = "brain"
    if project_agents:
        for a in project_agents:
            if getattr(a, 'agent_type', '') in ('claude',):
                agent = getattr(a, 'name', 'brain')
                break
    return TaskDag(
        summary=f"围绕{objective[:60]}的自动规划",
        tasks=[
            DagTask(
                id="auto-plan",
                title="主脑直接分析",
                objective=f"用户目标：{objective}。由主脑直接分析工作空间并给出方案。",
                agent=agent,
                write_scope=[],
            )
        ],
    )


class DeepSeekPlanner:
    def __init__(
        self,
        settings: Settings,
        usage: DeepSeekUsageService | None = None,
        brain: BrainSettings | None = None,
        knowledge_store=None,
    ) -> None:
        self.settings = settings
        self.usage = usage
        self.brain = brain or BrainSettings()
        self.knowledge_store = knowledge_store

    def create_discovery_dag(self, objective: str,
                              project_agents: list | None = None) -> TaskDag:
        """创建只读项目发现图；相关专业 Agent 会在所选工作空间内并行过滤候选项目。
        调用方需保证 project_agents 非空，否则应先跳过发现阶段直接规划。"""

        selected = [
            a for a in (project_agents or [])
            if getattr(a, 'agent_type', '') not in ('brain',)
        ]
        tasks = []
        for agent_obj in selected:
            agent_name = agent_obj.name if hasattr(agent_obj, 'name') else str(agent_obj)
            label = getattr(agent_obj, 'display_name', agent_name)
            sub_dir = getattr(agent_obj, 'sub_dir', '.')
            tasks.append(
                DagTask(
                    id=f"workspace-discovery-{agent_name}",
                    title=f"搜索并过滤{label}",
                    objective=(
                        f"在用户选择的整个工作空间中递归搜索与目标相关的{label}，不要假设固定目录名。"
                        f"用户目标：{objective}\n"
                        "本阶段严格只读，不修改任何文件。检查构建清单、框架配置、源码入口、"
                        "README 和已有接口定义，返回：候选项目相对路径、技术栈证据、与目标的"
                        "匹配理由、关键入口、现有接口或协议、推荐 write_scope，以及需要主脑"
                        "协调的跨项目问题。若没有合适项目，也要明确说明搜索范围和排除依据。"
                    )[:4000],
                    agent=agent_obj.name if hasattr(agent_obj, 'name') else str(agent_obj),
                    write_scope=[sub_dir] if sub_dir and sub_dir != '.' else [],
                )
            )
        return TaskDag(summary="并行搜索工作空间并过滤候选项目", tasks=tasks)

    def create_dag(
        self,
        objective: str,
        workspace_root: str | None = None,
        run_id: str | None = None,
        guidance: str = "",
        discovery_results: list[AgentResult] | None = None,
        project_agents: list | None = None,
    ) -> TaskDag:
        """基于项目发现结果生成实施 DAG；未设置密钥时返回代表性演示图。"""

        if not self.settings.deepseek_api_key:
            return self._enforce_requested_agents(self._demo_dag(objective), objective, project_agents)

        client = OpenAI(
            api_key=self.settings.deepseek_api_key,
            base_url=self.settings.deepseek_base_url,
        )
        schema = TaskDag.model_json_schema()
        discovery_context = json.dumps(
            [result.model_dump() for result in discovery_results or []],
            ensure_ascii=False,
            indent=2,
        )
        brain = self.brain.current()
        # 动态生成 Agent 路由提示词
        agent_guard = ""
        if project_agents:
            agent_list = []
            for a in project_agents:
                name = getattr(a, 'name', str(a))
                dtype = getattr(a, 'display_name', name)
                atype = getattr(a, 'agent_type', 'claude')
                sd = getattr(a, 'sub_dir', '.')
                agent_list.append(f"- {name} (类型:{atype}): {dtype}（工作子目录: {sd}）")
            agent_guard = (
                "可用的执行 Agent：\n" + "\n".join(agent_list) + "\n\n"
                "只允许把执行任务交给以上列出的 Agent，必须使用上面列出的精确名称。\n"
                "每个 Agent 的 write_scope 必须使用其指定的工作子目录。\n"
                "不要使用 frontend-agent、backend-agent 等占位名称。"
            )
        guard = STRUCTURE_GUARD_BASE + "\n\n" + agent_guard

        # 从知识库中检索与目标相关的内容，注入主脑规划上下文
        knowledge_context = ""
        if self.knowledge_store:
            try:
                kb_results = self.knowledge_store.search(objective, top_k=3, project_id="")
                if kb_results:
                    knowledge_context = "相关知识库条目：\n" + "\n".join(
                        f"- [{r.get('category', '')}] {r.get('title', '')}: {r.get('content', '')[:500]}"
                        for r in kb_results
                    ) + "\n\n"
            except Exception:
                pass

        response = client.chat.completions.create(
            model=self.settings.deepseek_model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        f"{brain.orchestration_prompt}\n\n"
                        "【最重要规则】你是主脑编排器，不是执行 Agent。\n"
                        "用户问你问题、让你分析结果、闲聊、解释概念 → 直接纯文本回答，绝不输出 JSON。\n"
                        "用户让你读写文件、运行命令、搜索代码、操作知识库 → 输出 JSON 任务图。\n"
                        "拿不准时选择纯文本。\n\n"
                        f"{guard}\n\n"
                        "【输出格式】\n"
                        "- 纯文本回答：直接写中文/英文，一个自然段即可\n"
                        "- JSON 任务图：直接写 { ... } 对象，不要用 ``` 包裹\n"
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"用户目标：\n{objective}\n\n"
                        f"{knowledge_context}"
                        f"上游对话上下文：\n{guidance or '无，这是新任务'}\n\n"
                        f"专业 Agent 的工作空间搜索与项目过滤结果：\n{discovery_context or '[]'}\n\n"
                        f"工作区结构索引（仅用于补充，不得覆盖 Agent 的过滤证据）：\n"
                        f"{self._workspace_context(workspace_root)}\n\n"
                        f"现在判断：用户是否要求执行具体操作？\n"
                        f"如果没有 → 用纯文本直接回答（你说的话会直接展示给用户）。\n"
                        f"如果有 → 按以下 Schema 输出 JSON 任务图（只包含必要的 Agent）：\n"
                        f"{json.dumps(schema, ensure_ascii=False)}"
                    ),
                },
            ],
            temperature=0.1,
        )
        if self.usage:
            self.usage.record(response, phase="planning", run_id=run_id)
        content = response.choices[0].message.content
        if not content:
            raise RuntimeError("DeepSeek 返回了空计划")
        # 尝试解析 JSON 任务图；如果返回的是纯文本或混合内容，提取 JSON 部分
        content_stripped = content.strip()
        # DeepSeek 有时会在 JSON 前加文字说明，或在 JSON 后追加
        # 找到第一个 { 和最后一个 }
        json_start = content_stripped.find("{")
        json_end = content_stripped.rfind("}")
        if json_start != -1 and json_end > json_start:
            json_part = content_stripped[json_start:json_end + 1]
            try:
                dag = TaskDag.model_validate_json(json_part)
            except Exception:
                dag = _fallback_dag(objective, project_agents)
        else:
            # 纯文本：主脑选择直接回答，不创建任务
            dag = TaskDag(
                summary=content_stripped[:1000],
                tasks=[],
            )
        return self._enforce_requested_agents(dag, objective, project_agents)


    @classmethod
    def _resolve_agent_name(cls, role: str, project_agents: list | None) -> str | None:
        """将概念角色映射到实际项目 Agent 名称。"""
        if not project_agents:
            return None
        role_map = {
            "frontend-agent": ("claude", "vue-frontend", "react-frontend"),
            "backend-agent": ("claude", "flask-backend", "springboot-backend"),
            "netty-agent": ("claude", "springboot-netty"),
        }
        candidates = role_map.get(role, ())
        for a in project_agents:
            name = getattr(a, 'name', '')
            if name in candidates:
                return name
        # fallback: any claude agent for frontend/backend, any agent for others
        for a in project_agents:
            if getattr(a, 'agent_type', '') in ('claude',):
                return getattr(a, 'name', None)
        return None

    @classmethod
    def _enforce_requested_agents(cls, dag: TaskDag, objective: str,
                                   project_agents: list | None = None) -> TaskDag:
        """把用户明确点名的领域从软提示提升为确定性的 DAG 约束。"""

        # 主脑选择直接回复（没有任务），不做修改直接返回
        if not dag.tasks:
            return dag

        renamed = {}
        if project_agents:
            name_map = {"frontend-agent": "frontend-agent", "backend-agent": "backend-agent",
                        "netty-agent": "netty-agent", "knowledge-agent": "knowledge-agent"}
            for role in name_map:
                actual = cls._resolve_agent_name(role, project_agents)
                if actual and actual != role:
                    renamed[role] = actual
            # Apply renames to all tasks
            tasks = []
            for task in dag.tasks:
                new_agent = renamed.get(task.agent, task.agent)
                new_deps = [renamed.get(d, d) for d in task.depends_on]
                tasks.append(task.model_copy(update={"agent": new_agent, "depends_on": new_deps}))
            if tasks:
                dag = dag.model_copy(update={"tasks": tasks})

        lowered = objective.lower().replace(" ", "")
        # Resolve actual agent names
        frontend_agent = cls._resolve_agent_name("frontend-agent", project_agents) or "frontend-agent"
        backend_agent = cls._resolve_agent_name("backend-agent", project_agents) or "backend-agent"
        netty_agent = cls._resolve_agent_name("netty-agent", project_agents) or "netty-agent"

        exclusions = {
            frontend_agent: any(
                phrase in lowered
                for phrase in ("不用前端", "不要前端", "不需要前端", "仅后端", "只看后端", "只改后端")
            ),
            backend_agent: any(
                phrase in lowered
                for phrase in ("不用后端", "不要后端", "不需要后端", "仅前端", "只看前端", "只改前端")
            ),
            netty_agent: any(
                phrase in lowered for phrase in ("不用netty", "不要netty", "不需要netty", "排除netty")
            ),
        }
        requested = {
            frontend_agent: "前后端" in lowered
            or any(word in lowered for word in ("前端", "frontend", "vue", "react", "页面")),
            backend_agent: "前后端" in lowered
            or any(word in lowered for word in ("后端", "backend", "flask", "服务端", "api")),
            netty_agent: "netty" in lowered,
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
            frontend_agent: ("frontend", "前端项目", ["."]),
            backend_agent: ("backend", "后端项目", ["."]),
            netty_agent: ("netty", "Netty 数据链路", ["."]),
        }
        existing_ids = {task.id for task in tasks}
        for agent, is_requested in requested.items():
            if not is_requested or exclusions.get(agent, False) or agent in present:
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
                        "先根据前置项目发现结果确定真实项目根目录，只处理本领域并给出"
                        "可供主脑汇总的明确结果。"
                    ),
                    agent=agent,
                    depends_on=[],
                    write_scope=[] if read_only else write_scope,
                )
            )
            existing_ids.add(task_id)
            present.add(agent)

        # 兜底: 只有当用户明确点名了领域但 tasks 被意外清空时，才补上强制任务
        # 如果用户没有点名（闲聊/概念题），保留空 tasks（主脑直接回答了）
        if not tasks and has_explicit_scope:
            fallback_agent = backend_agent if backend_agent != "backend-agent" else (
                frontend_agent if frontend_agent != "frontend-agent" else "brain"
            )
            tasks.append(
                DagTask(
                    id="fallback-analysis",
                    title="主脑直接分析",
                    objective=f"用户目标：{objective}。由于没有匹配的专业 Agent，由主脑直接分析并给出方案。",
                    agent=fallback_agent,
                    depends_on=[],
                    write_scope=[],
                )
            )

        return TaskDag(
            summary=dag.summary,
            coordination_contract=dag.coordination_contract,
            tasks=tasks,
        )

    def summarize(
        self,
        objective: str,
        dag: TaskDag,
        results: list[AgentResult],
        run_id: str | None = None,
        guidance: str = "",
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
                {"role": "system", "content": self.brain.current().orchestration_prompt},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "objective": objective,
                            "upstream_context": guidance,
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
    def _workspace_context(workspace_root: str | None) -> str:
        """生成工作空间的结构概览，帮助主脑理解目录布局。"""
        if not workspace_root:
            return "未提供工作空间路径"
        root = Path(workspace_root)
        if not root.is_dir():
            return f"工作空间路径不存在: {workspace_root}"
        lines = [f"工作空间根目录: {workspace_root}"]
        try:
            entries = sorted(root.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))
            for entry in entries[:40]:
                marker = "/" if entry.is_dir() else ""
                lines.append(f"  {entry.name}{marker}")
            remaining = len(entries) - 40
            if remaining > 0:
                lines.append(f"  ... 还有 {remaining} 项")
        except PermissionError:
            lines.append("  (无权限读取目录)")
        return "\n".join(lines)

    @staticmethod
    def _demo_dag(objective: str, project_agents: list | None = None) -> TaskDag:
        """演示模式用执行 Agent 验证并行分发和结果汇合。"""

        short_objective = objective[:800]
        demo_tasks = [
            DagTask(
                id="demo-analyze",
                title="分析项目结构（演示）",
                objective=f"分析当前工作空间结构并撰写简要发现报告。用户目标：{short_objective}",
                agent="flask-backend" if any(
                    a for a in (project_agents or [])
                    if getattr(a, 'name', '') == 'flask-backend'
                ) else "flask-backend",
                write_scope=[],
            ),
            DagTask(
                id="demo-code",
                title="代码实施（演示）",
                objective=f"基于分析结果选择最佳实现方案并说明理由。用户目标：{short_objective}",
                agent="vue-frontend" if any(
                    a for a in (project_agents or [])
                    if getattr(a, 'name', '') == 'vue-frontend'
                ) else "vue-frontend",
                depends_on=["demo-analyze"],
                write_scope=["frontend"],
            ),
            DagTask(
                id="demo-verify",
                title="验证总结（演示）",
                objective=f"验证前两步结果并汇总报告。用户目标：{short_objective}",
                agent="vue-frontend" if any(
                    a for a in (project_agents or [])
                    if getattr(a, 'name', '') == 'vue-frontend'
                ) else "vue-frontend",
                depends_on=["demo-code"],
                write_scope=[],
            ),
        ]
        return TaskDag(
            summary=f"Around '{short_objective[:60]}' - demo task graph",
            coordination_contract=(
                "演示共享契约：跨项目实现应先约定接口路径、方法、请求/响应字段与错误行为；"
                "真实模式由 DeepSeek 根据项目发现结果生成具体契约。"
            ),
            tasks=demo_tasks,
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
