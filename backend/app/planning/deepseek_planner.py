"""使用 DeepSeek 将自然语言目标转换为受约束的任务 DAG。"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING

from openai import OpenAI

from app.config import Settings
from app.domain.models import AgentResult, DagTask, TaskDag
from app.services.brain_settings import BrainSettings

if TYPE_CHECKING:
    from app.planning.execution_plan import ExecutionPlan

logger = logging.getLogger(__name__)



class PlannerResult:
    """规划器返回结果，包含 DAG 和完整 LLM 输入信息。"""
    __slots__ = ("dag", "system_prompt", "user_prompt", "model", "duration_ms")

    def __init__(
        self,
        dag: TaskDag,
        system_prompt: str = "",
        user_prompt: str = "",
        model: str = "",
        duration_ms: float = 0,
    ):
        self.dag = dag
        self.system_prompt = system_prompt
        self.user_prompt = user_prompt
        self.model = model
        self.duration_ms = duration_ms
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
2. 分析和编码任务分配给编码类 Agent（claude/file-ops）；RAG Agent 用于知识检索。
3. **BlackboardAgent** 用于 Agent 间共享信息——在需要多个 Agent 协作时，先让 BlackboardAgent 存储共享合约（api_contract、data_models、architecture_decisions 等 key），其他 Agent 通过依赖链获取。
4. **含协调契约的多 Agent 项目，第一个任务应为 BlackboardAgent 存储合约**。
5. 主脑自主决策何时读写 RAG——可以在任务前检索已有知识，也可以在任务后存储新发现。
6. 用户说"先...然后..."/"再..."时，then 后的任务 depends_on 于前面的任务。
7. 无真实依赖的任务可以并行；有数据或逻辑依赖时建立 depends_on。
8. write_scope 使用 Agent 声明的工作子目录，没有工作目录的 Agent 不限制写入范围。
9. 每个 Agent 自己完成测试和自检，不创建独立测试 Agent。
10. 不要把跨领域工作全部塞给一个 Agent；与目标无关的 Agent 不要调用。
11. 上游上下文是已有任务的延续，结合上游理解指代；不要重复已完成的工作。
12. 不要创建 workspace-discovery- 前缀的任务（发现阶段已完成）。
13. 跨项目接口写入 coordination_contract。
14. 输出 JSON 时不要用 markdown 代码块包裹，直接输出纯 JSON 对象。
15. 任务数 ≥ 3 时，考虑先输出一个 BlackboardAgent 共享契约任务，再并行执行。

## Agent 选择规则（增强）

16. 选择 Agent 时综合考虑：capabilities（能力）、limitations（限制）、preferred_tasks（偏好）、skills（专项规范）。
17. 如果 Agent 的 forbidden_tasks 中包含任务关键词，绝不能分配该任务给此 Agent。
18. 优先选择 capabilities 和 preferred_tasks 与任务最匹配的 Agent。
19. 避免将所有任务集中分配给同一个 Agent，尽量利用团队的多样性。
20. 每个任务都必须有一条明确的验收标准（在 objective 中说明如何判断完成）。

## 任务拆分规则

21. 每个任务目标必须单一、清晰、可独立验收。
22. 任务名称应当描述具体动作和对象，如"定义用户登录 API 请求与响应结构"而非"处理后端"。
23. 可以并行的任务不要无意义串行。
24. 公共接口（API 契约、数据模型）应在前后端并行实现前先确定。
25. 高风险修改需要审查步骤。
26. 不要过度拆分——简单任务一个 Agent 即可完成。
27. 先判断 RAG/知识库是“操作工具”还是“被修改的软件模块”。只有用户明确要求检索、
    查询、召回、录入或导入知识时才使用 RAG Agent；如果用户要求更新、修复、实现或重构
    RAG 模块、接口或代码，必须交给编码 Agent，绝不能把它改写成知识检索任务。
""".strip()

PROJECT_MODE_GUIDANCE = {
    "manual": (
        "当前项目工作模式为 Manual。只规划用户明确要求的操作，不主动扩大修改范围，"
        "不添加可选优化；任务边界和验收条件必须具体。"
    ),
    "editAutomatically": (
        "当前项目工作模式为 Edit Automatically。可以为完成目标自动规划必要的文件修改，"
        "但不得加入与目标无关的重构或高风险操作。"
    ),
    "plan": (
        "当前项目工作模式为 Plan。只生成可执行的任务计划和 DAG，不假设任务已经执行，"
        "重点写明依赖、影响范围、验收标准和风险。"
    ),
    "auto": (
        "当前项目工作模式为 Auto。可以自主完成规划、执行、验证和必要返工，"
        "同时仍需遵守 Agent 能力、写入范围和安全边界。"
    ),
}


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


def _infer_acceptance_criteria(task: DagTask) -> list[str]:
    """从任务目标推断验收标准。"""
    obj = task.objective.lower()
    criteria: list[str] = []
    if any(w in obj for w in ("创建", "新建", "生成", "create", "generate")):
        criteria.append("确认生成的文件存在且内容符合规范")
    if any(w in obj for w in ("修改", "更新", "修复", "modify", "update", "fix")):
        criteria.append("确认修改已保存且功能符合预期")
    if any(w in obj for w in ("删除", "移除", "delete", "remove")):
        criteria.append("确认指定内容已删除且无残留")
    if any(w in obj for w in ("测试", "验证", "test", "verify")):
        criteria.append("确认测试通过")
    if any(w in obj for w in ("api", "接口", "endpoint")):
        criteria.append("确认 API 契约不变或变更已记录")
    if any(w in obj for w in ("文档", "document")):
        criteria.append("确认文档内容准确")
    if not criteria:
        criteria.append("任务目标已达成，产物已生成")
    return criteria


class DeepSeekPlanner:
    def __init__(
        self,
        settings: Settings,
        brain: BrainSettings | None = None,
        knowledge_store=None,
    ) -> None:
        self.settings = settings
        self.brain = brain or BrainSettings()
        self.knowledge_store = knowledge_store

    @staticmethod
    def _rag_is_code_subject(objective: str) -> bool:
        """RAG 是待修改的软件对象，而不是本轮要调用的检索工具。"""
        lowered = objective.lower().replace(" ", "")
        mentions_rag = any(word in lowered for word in ("rag", "知识库"))
        code_actions = (
            "更新", "修改", "修复", "实现", "开发", "重构", "适配", "新增",
            "接口", "模块", "代码", "api", "endpoint", "refactor", "implement",
            "update", "modify", "fix",
        )
        explicit_knowledge_actions = (
            "查询知识库", "检索知识库", "搜索知识库", "查找知识库",
            "知识库召回", "录入知识", "导入知识", "写入知识库",
            "更新知识库中的", "修改知识库中的", "更新知识条目",
            "修改知识条目", "删除知识条目", "从知识库",
            "queryknowledge", "searchknowledge", "retrieveknowledge",
        )
        return (
            mentions_rag
            and any(action in lowered for action in code_actions)
            and not any(action in lowered for action in explicit_knowledge_actions)
        )

    @staticmethod
    def _has_rag_agent(project_agents: list | None) -> bool:
        return any(
            getattr(agent, "agent_type", "") == "rag"
            for agent in (project_agents or [])
        )

    def create_discovery_dag(self, objective: str,
                              project_agents: list | None = None) -> TaskDag:
        """创建只读项目发现图；相关专业 Agent 会在所选工作空间内并行过滤候选项目。
        调用方需保证 project_agents 非空，否则应先跳过发现阶段直接规划。"""

        selected = [
            a for a in (project_agents or [])
            if getattr(a, 'agent_type', '') not in ('brain',)
        ]
        lowered = objective.lower().replace(" ", "")
        domain_keywords = {
            "frontend": ("前端", "页面", "ui", "vue", "react", "frontend"),
            "backend": ("后端", "服务端", "接口", "api", "数据库", "backend"),
            "netty": ("netty", "tcp", "udp"),
            "rag": ("知识库", "检索", "rag"),
            "file": ("文件", "目录", "复制", "移动", "file"),
            "document": ("文档", "readme", "document"),
        }
        requested_domains = {
            domain for domain, words in domain_keywords.items()
            if any(word in lowered for word in words)
        }
        if self._rag_is_code_subject(objective):
            requested_domains.discard("rag")
            requested_domains.add("backend")
        if "前后端" in lowered:
            requested_domains.update({"frontend", "backend"})
        if any(word in lowered for word in ("不用netty", "不要netty", "不需要netty")):
            requested_domains.discard("netty")

        def domains(agent: object) -> set[str]:
            haystack = " ".join([
                str(getattr(agent, "name", "")),
                str(getattr(agent, "display_name", "")),
                *map(str, getattr(agent, "capabilities", ())),
                *map(str, getattr(agent, "preferred_tasks", ())),
            ]).lower()
            return {
                domain for domain, words in domain_keywords.items()
                if any(word in haystack for word in words)
            }

        if requested_domains:
            chosen: list[object] = []
            for domain in requested_domains:
                candidates = [agent for agent in selected if domain in domains(agent)]
                if candidates:
                    chosen.append(max(
                        candidates,
                        key=lambda agent: (
                            getattr(agent, "priority", 0),
                            len(getattr(agent, "capabilities", ())),
                        ),
                    ))
            selected = list({getattr(agent, "name", str(agent)): agent for agent in chosen}.values())
        else:
            coding = [
                agent for agent in selected
                if getattr(agent, "agent_type", "") in ("claude", "chat")
                and not domains(agent).intersection({"document", "rag", "file"})
            ]
            selected = sorted(
                coding or selected,
                key=lambda agent: (
                    getattr(agent, "priority", 0),
                    len(getattr(agent, "capabilities", ())),
                ),
                reverse=True,
            )[:2]
        tasks = []
        for agent_obj in selected:
            agent_name = agent_obj.name if hasattr(agent_obj, 'name') else str(agent_obj)
            label = getattr(agent_obj, 'display_name', agent_name)
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
                    write_scope=[],
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
        project_id: str = "",
        project_mode: str = "auto",
    ) -> TaskDag:
        """基于项目发现结果生成实施 DAG；未设置密钥时返回代表性演示图。"""

        started_at = time.perf_counter()
        logger.info(
            "planner.started run_id=%s project_id=%s mode=%s objective_chars=%s "
            "agents=%s discovery_results=%s demo=%s",
            run_id or "-",
            project_id or "-",
            project_mode,
            len(objective),
            len(project_agents or []),
            len(discovery_results or []),
            not bool(self.settings.deepseek_api_key),
        )
        if not self.settings.deepseek_api_key:
            dag = self._enrich_dag(self._demo_dag(objective, project_agents), project_agents)
            dag = self._enforce_requested_agents(dag, objective, project_agents)
            dag = self._repair_rag_code_routing(dag, objective, project_agents)
            logger.info(
                "planner.finished run_id=%s source=demo tasks=%s duration_ms=%.1f",
                run_id or "-",
                len(dag.tasks),
                (time.perf_counter() - started_at) * 1000,
            )
            return PlannerResult(
                dag=dag,
                model='demo',
                duration_ms=(time.perf_counter() - started_at) * 1000,
            )

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
                agent_list.append(
                    f"- {name}（{dtype}）\n"
                    f"  role: {getattr(a, 'role', 'implementation_agent')}\n"
                    f"  type: {atype}; workdir: {sd}\n"
                    f"  capabilities: {list(getattr(a, 'capabilities', ()))}\n"
                    f"  limitations: {list(getattr(a, 'limitations', ()))}\n"
                    f"  preferred_tasks: {list(getattr(a, 'preferred_tasks', ()))}\n"
                    f"  forbidden_tasks: {list(getattr(a, 'forbidden_tasks', ()))}\n"
                    f"  skills: {list(getattr(a, 'skills', ()))}\n"
                    f"  priority: {getattr(a, 'priority', 0)}; "
                    f"max_iterations: {getattr(a, 'max_iterations', 3)}"
                )
            agent_guard = (
                "可用的执行 Agent：\n" + "\n".join(agent_list) + "\n\n"
                "只允许把执行任务交给以上列出的 Agent，必须使用上面列出的精确名称。\n"
                "每个 Agent 的 write_scope 必须使用其指定的工作子目录。\n"
                "不要使用 frontend-agent、backend-agent 等占位名称。"
            )
        guard = STRUCTURE_GUARD_BASE + "\n\n" + agent_guard
        mode_guidance = PROJECT_MODE_GUIDANCE.get(
            project_mode,
            PROJECT_MODE_GUIDANCE["auto"],
        )

        # 从知识库中检索与目标相关的内容，注入主脑规划上下文
        knowledge_context = ""
        if (
            self.knowledge_store
            and self._has_rag_agent(project_agents)
            and not self._rag_is_code_subject(objective)
        ):
            try:
                kb_results = self.knowledge_store.search(
                    objective, top_k=3, project_id=project_id
                )
                if kb_results:
                    knowledge_context = "相关知识库条目：\n" + "\n".join(
                        f"- [{r.get('category', '')}] {r.get('title', '')}: {r.get('content', '')[:500]}"
                        for r in kb_results
                    ) + "\n\n"
            except Exception:
                pass

        system_prompt = (
            f"{brain.orchestration_prompt}\n\n"
            f"{mode_guidance}\n\n"
            "【最重要规则】你是主脑编排器，不是执行 Agent。\n"
            "用户问你问题、让你分析结果、闲聊、解释概念 → 直接纯文本回答，绝不输出 JSON。\n"
            "用户让你读写文件、运行命令、搜索代码、操作知识库 → 输出 JSON 任务图。\n"
            "RAG/知识库若是被更新、修复、实现或重构的软件模块，属于代码任务，"
            "必须交给编码 Agent；不要调用 RAG Agent 查询。\n"
            "拿不准时选择纯文本。\n\n"
            f"{guard}\n\n"
            "【输出格式】\n"
            "- 纯文本回答：直接写中文/英文，一个自然段即可\n"
            "- JSON 任务图：直接写 { ... } 对象，不要用 ``` 包裹\n"
        )
        user_prompt = (
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
        )

        response = client.chat.completions.create(
            model=self.settings.deepseek_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,
        )
        content = response.choices[0].message.content
        logger.info(
            "planner.response_received run_id=%s response_chars=%s",
            run_id or "-",
            len(content or ""),
        )
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
                logger.warning(
                    "planner.invalid_dag_json run_id=%s json_chars=%s; using fallback",
                    run_id or "-",
                    len(json_part),
                    exc_info=True,
                )
                dag = _fallback_dag(objective, project_agents)
        else:
            # 纯文本：主脑选择直接回答，不创建任务
            dag = TaskDag(
                summary=content_stripped[:1000],
                tasks=[],
            )
        dag = self._enrich_dag(dag, project_agents)
        dag = self._enforce_requested_agents(dag, objective, project_agents)
        dag = self._repair_rag_code_routing(dag, objective, project_agents)
        duration_ms = (time.perf_counter() - started_at) * 1000
        logger.info(
            "planner.finished run_id=%s source=deepseek tasks=%s direct_answer=%s "
            "duration_ms=%.1f",
            run_id or "-",
            len(dag.tasks),
            not dag.tasks,
            duration_ms,
        )
        return PlannerResult(
            dag=dag,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=self.settings.deepseek_model,
            duration_ms=duration_ms,
        )

    @classmethod
    def _repair_rag_code_routing(
        cls,
        dag: TaskDag,
        objective: str,
        project_agents: list | None,
    ) -> TaskDag:
        """确定性阻止“修改 RAG 代码”被误路由为知识检索。"""
        if not dag.tasks or not cls._rag_is_code_subject(objective):
            return dag

        rag_names = {
            getattr(agent, "name", "")
            for agent in (project_agents or [])
            if getattr(agent, "agent_type", "") == "rag"
        }
        rag_names.update({"rag", "rag-agent", "knowledge-agent"})
        target = cls._resolve_agent_name("backend-agent", project_agents)
        if not target:
            return dag

        repaired: list[DagTask] = []
        for task in dag.tasks:
            if task.agent not in rag_names:
                repaired.append(task)
                continue
            repaired.append(task.model_copy(update={
                "title": "更新 RAG 相关代码",
                "objective": (
                    f"把 RAG 视为当前要修改的软件模块，而不是检索工具。"
                    f"完成用户原始目标：{objective}。检查并修改相关代码与接口，"
                    "验证变更；不要执行知识库检索来替代代码更新。"
                )[:4000],
                "agent": target,
            }))
        return dag.model_copy(update={"tasks": repaired})

    @staticmethod
    def _enrich_dag(dag: TaskDag, project_agents: list | None) -> TaskDag:
        """用可验证默认值和 Agent 配置补全模型可能省略的任务协议。"""
        profiles = {
            getattr(profile, "name", ""): profile
            for profile in (project_agents or [])
        }
        tasks: list[DagTask] = []
        for task in dag.tasks:
            profile = profiles.get(task.agent)
            criteria = task.acceptance_criteria or _infer_acceptance_criteria(task)
            outputs = task.expected_outputs or [
                f"{task.title}的实际产物或可复用结论",
                "验证结果与未验证项说明",
            ]
            updates: dict[str, object] = {
                "acceptance_criteria": criteria,
                "expected_outputs": outputs,
                "status": "ready" if not task.depends_on else "backlog",
            }
            if profile is not None:
                updates.update({
                    "max_iterations": min(
                        task.max_iterations,
                        getattr(profile, "max_iterations", task.max_iterations),
                    ),
                    "context": {
                        **task.context,
                        "agent_role": getattr(
                            profile, "role", "implementation_agent"
                        ),
                        "agent_capabilities": list(
                            getattr(profile, "capabilities", ())
                        ),
                    },
                })
            tasks.append(task.model_copy(update=updates))
        return dag.model_copy(update={"tasks": tasks})


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
        role_keywords = {
            "frontend-agent": ("frontend", "vue", "react", "前端"),
            "backend-agent": ("backend", "flask", "spring", "后端"),
            "netty-agent": ("netty",),
        }.get(role, ())
        for a in project_agents:
            haystack = " ".join([
                getattr(a, "name", ""),
                getattr(a, "display_name", ""),
                *map(str, getattr(a, "capabilities", ())),
            ]).lower()
            if any(keyword in haystack for keyword in role_keywords):
                return getattr(a, "name", None)
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
        project_mode: str = "auto",
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
                {
                    "role": "system",
                    "content": (
                        f"{self.brain.current().orchestration_prompt}\n\n"
                        f"{PROJECT_MODE_GUIDANCE.get(project_mode, PROJECT_MODE_GUIDANCE['auto'])}"
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "objective": objective,
                            "upstream_context": guidance,
                            "project_mode": project_mode,
                            "dag": dag.model_dump(),
                            "results": [result.model_dump() for result in results],
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            temperature=0.1,
        )
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
        ignored = {
            ".env", ".git", ".workspace", ".venv", "node_modules",
            "__pycache__", ".pytest_cache", "dist", "build",
        }
        try:
            entries = [
                entry for entry in sorted(
                    root.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower())
                )
                if entry.name not in ignored and not entry.name.endswith((".key", ".pem"))
            ]
            shown = 0
            for entry in entries:
                if shown >= 40:
                    break
                marker = "/" if entry.is_dir() else ""
                lines.append(f"  {entry.name}{marker}")
                shown += 1
                if entry.is_dir():
                    try:
                        children = [
                            child for child in sorted(entry.iterdir(), key=lambda e: e.name.lower())
                            if child.name not in ignored
                            and not child.name.startswith(".")
                            and not child.name.endswith((".key", ".pem"))
                        ][:8]
                        lines.extend(
                            f"    {child.name}{'/' if child.is_dir() else ''}"
                            for child in children
                        )
                    except (OSError, PermissionError):
                        pass
            remaining = len(entries) - shown
            if remaining > 0:
                lines.append(f"  ... 还有 {remaining} 项")
        except PermissionError:
            lines.append("  (无权限读取目录)")
        return "\n".join(lines)

    @staticmethod
    def _demo_dag(objective: str, project_agents: list | None = None) -> TaskDag:
        """演示模式用执行 Agent 验证并行分发和结果汇合。"""

        short_objective = objective[:800]
        frontend_agent = DeepSeekPlanner._resolve_agent_name(
            "frontend-agent", project_agents
        )
        backend_agent = DeepSeekPlanner._resolve_agent_name(
            "backend-agent", project_agents
        )
        fallback_agent = next(
            (
                getattr(agent, "name", "")
                for agent in (project_agents or [])
                if getattr(agent, "agent_type", "") != "brain"
            ),
            "brain",
        )
        analysis_agent = backend_agent or frontend_agent or fallback_agent
        implementation_agent = frontend_agent or backend_agent or fallback_agent
        demo_tasks = [
            DagTask(
                id="demo-analyze",
                title="分析项目结构（演示）",
                objective=f"分析当前工作空间结构并撰写简要发现报告。用户目标：{short_objective}",
                agent=analysis_agent,
                write_scope=[],
            ),
            DagTask(
                id="demo-code",
                title="代码实施（演示）",
                objective=f"基于分析结果选择最佳实现方案并说明理由。用户目标：{short_objective}",
                agent=implementation_agent,
                depends_on=["demo-analyze"],
                write_scope=["frontend"],
            ),
            DagTask(
                id="demo-verify",
                title="验证总结（演示）",
                objective=f"验证前两步结果并汇总报告。用户目标：{short_objective}",
                agent=implementation_agent,
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

    # ==================== Intent Classification ====================

    def create_execution_plan(
        self,
        objective: str,
        workspace_root: str | None = None,
        run_id: str | None = None,
        guidance: str = "",
        project_agents: list | None = None,
        project_mode: str = "auto",
    ) -> "ExecutionPlan":
        """创建结构化执行计划 — 包装 create_dag() 并升级为 AgentTask。

        与 create_dag() 兼容，同时输出更丰富的任务定义。
        """
        from app.planning.execution_plan import AgentTask, ExecutionPlan

        dag = self.create_dag(
            objective, workspace_root, run_id, guidance,
            project_agents=project_agents,
            project_mode=project_mode,
        )

        # 推断请求类型
        obj_lower = objective.lower()
        if not dag.tasks:
            request_type = "direct_answer"
        elif any(w in obj_lower for w in ("搜索", "检索", "查找", "知识库", "search", "find", "query")):
            request_type = "retrieval"
        elif any(w in obj_lower for w in ("复制", "移动", "删除", "文件", "copy", "move", "delete", "file")):
            request_type = "file_operation"
        elif any(w in obj_lower for w in ("文档", "说明", "document", "readme", "总结", "整理")):
            request_type = "document_processing"
        elif any(w in obj_lower for w in ("代码", "实现", "修改", "修复", "code", "implement", "fix", "开发")):
            request_type = "coding"
        elif len(dag.tasks) > 3:
            request_type = "mixed"
        else:
            request_type = "planning"

        # 推断策略
        if not dag.tasks:
            strategy = "direct"
        elif len(dag.tasks) == 1:
            strategy = "single_agent"
        else:
            has_deps = any(t.depends_on for t in dag.tasks)
            has_parallel = len(dag.tasks) > len({t.id for t in dag.tasks if t.depends_on})
            if has_deps and has_parallel:
                strategy = "hybrid"
            elif has_deps:
                strategy = "sequential"
            else:
                strategy = "parallel"

        # 升级 DagTask → AgentTask
        agent_tasks = []
        for task in dag.tasks:
            at = AgentTask.from_dag_task(
                task,
                acceptance_criteria=_infer_acceptance_criteria(task),
                status="ready" if not task.depends_on else "backlog",
            )
            agent_tasks.append(at)

        return ExecutionPlan(
            goal=objective,
            request_type=request_type,  # type: ignore[arg-type]
            tasks=agent_tasks,
            execution_strategy=strategy,  # type: ignore[arg-type]
            summary=dag.summary,
            coordination_contract=dag.coordination_contract,
        )

    def classify_intent(self, objective: str, available_flows: list[dict]) -> str | None:
        """Lightweight LLM call to match user intent to a known flow.

        Returns the flow name if confidence >= 0.7, otherwise None.
        Falls back to keyword matching if LLM is unavailable.
        """
        # If no flows registered, skip
        if not available_flows:
            return None

        # Try keyword-based match first (zero-cost)
        lowered = objective.lower()
        for f in available_flows:
            for kw in f.get("keywords", []):
                if kw.lower() in lowered:
                    return f["name"]
            if f["name"].lower() in lowered:
                return f["name"]

        # If LLM available, do a lightweight classification
        if not self.settings.deepseek_api_key:
            return None

        try:
            client = OpenAI(
                api_key=self.settings.deepseek_api_key,
                base_url=self.settings.deepseek_base_url,
            )
            flow_list = "\n".join(
                f"- {f['name']}: {f['description']} (关键词: {', '.join(f.get('keywords', []))})"
                for f in available_flows[:10]
            )
            response = client.chat.completions.create(
                model=self.settings.deepseek_model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "你是一个意图分类器。根据用户输入，判断是否匹配以下预定义流程。\n"
                            "如果匹配，只输出流程名称。如果不匹配任何流程，输出 NONE。\n"
                            "不要输出任何其他内容。\n\n"
                            f"可用流程：\n{flow_list}"
                        ),
                    },
                    {"role": "user", "content": objective},
                ],
                temperature=0.0,
                max_tokens=50,
            )
            content = (response.choices[0].message.content or "").strip().upper()
            if content == "NONE" or not content:
                return None
            # Verify the returned name is a valid flow
            for f in available_flows:
                if f["name"].upper() == content:
                    return f["name"]
            return None
        except Exception:
            return None
