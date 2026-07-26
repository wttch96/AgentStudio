"""Agent 选择器 —— 基于规则过滤 + 多维度评分。

选择流程:
    规则过滤 → 能力匹配 → 工具匹配 → 偏好匹配 →
    限制检查 → 负载评分 → 返回最佳候选
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.agents.registry import AgentProfile, AgentRegistry


@dataclass
class SelectionScore:
    """单个 Agent 的匹配评分。"""

    agent_name: str
    score: float = 0.0
    capability_match: float = 0.0
    tool_match: float = 0.0
    preference_match: float = 0.0
    priority_bonus: float = 0.0
    workload_penalty: float = 0.0
    limitation_penalty: float = 0.0
    matched_capabilities: list[str] = field(default_factory=list)
    missing_capabilities: list[str] = field(default_factory=list)
    selection_reason: str = ""
    excluded: bool = False
    exclusion_reason: str = ""


class AgentSelector:
    """基于规则和评分的 Agent 选择器。

    强制规则:
        1. forbidden_tasks 命中 → 直接排除
        2. 缺少必需工具 → 直接排除
        3. limitations 与任务核心需求冲突 → 直接排除

    评分维度:
        - 能力匹配 (35%)
        - 工具匹配 (25%)
        - 任务偏好 (15%)
        - 优先级 (15%)
        - 上下文亲和 (10%)
        - 负载惩罚 (扣分)
        - 限制惩罚 (扣分)
    """

    def __init__(self, registry: AgentRegistry) -> None:
        self._registry = registry

    def select(
        self,
        project_id: str,
        task_objective: str,
        required_tools: list[str] | None = None,
        required_capabilities: list[str] | None = None,
        candidate_names: list[str] | None = None,
        workload_counts: dict[str, int] | None = None,
    ) -> SelectionScore | None:
        """为任务选择最佳 Agent。

        Args:
            project_id: 项目 ID
            task_objective: 任务目标描述
            required_tools: 任务必需的工具列表
            required_capabilities: 任务需要的能力
            candidate_names: 候选 Agent 名称列表，None 表示所有
            workload_counts: Agent → 当前负载任务数

        Returns:
            最佳匹配的 SelectionScore，或 None 表示无合适 Agent。
        """
        try:
            profiles = self._registry.load_project_agents(project_id)
        except Exception:
            profiles = self._registry._load_from_files(project_id)

        if not profiles:
            return None

        workloads = workload_counts or {}
        obj_lower = task_objective.lower()
        required_tools_set = set(required_tools or [])
        required_capabilities_set = set(required_capabilities or [])

        scores: list[SelectionScore] = []

        for name, profile in profiles.items():
            # 跳过 brain 类型（主脑不执行具体任务）
            if profile.agent_type in ("brain",):
                continue
            if candidate_names and name not in candidate_names:
                continue

            score = self._score_agent(
                profile, obj_lower, required_tools_set,
                required_capabilities_set, workloads,
            )
            scores.append(score)

        if not scores:
            return None

        # 过滤被排除的
        valid = [s for s in scores if not s.excluded]
        if not valid:
            return None

        # 按评分降序
        valid.sort(key=lambda s: s.score, reverse=True)
        return valid[0]

    def select_top_k(
        self,
        project_id: str,
        task_objective: str,
        k: int = 3,
        **kwargs: Any,
    ) -> list[SelectionScore]:
        """返回评分最高的 K 个候选 Agent。"""
        try:
            profiles = self._registry.load_project_agents(project_id)
        except Exception:
            profiles = self._registry._load_from_files(project_id)

        if not profiles:
            return []

        obj_lower = task_objective.lower()
        workloads = kwargs.get("workload_counts", {})
        required_tools = set(kwargs.get("required_tools", []))
        required_capabilities = set(kwargs.get("required_capabilities", []))

        scores: list[SelectionScore] = []
        for name, profile in profiles.items():
            if profile.agent_type in ("brain",):
                continue
            score = self._score_agent(
                profile, obj_lower, required_tools,
                required_capabilities, workloads,
            )
            scores.append(score)

        valid = [s for s in scores if not s.excluded]
        valid.sort(key=lambda s: s.score, reverse=True)
        return valid[:k]

    def validate_assignment(
        self, profile: AgentProfile, task_objective: str,
    ) -> tuple[bool, str]:
        """验证 Agent 是否可以执行给定任务。

        Returns:
            (is_valid, reason)
        """
        obj_lower = task_objective.lower()

        # 检查 forbidden_tasks
        for forbidden in profile.forbidden_tasks:
            if forbidden.lower() in obj_lower:
                return False, f"任务命中禁止项: {forbidden}"

        # 检查 limitations
        for limitation in profile.limitations:
            if limitation.lower() in obj_lower:
                return False, f"任务涉及已知限制: {limitation}"

        return True, "验证通过"

    @staticmethod
    def resolve_role(
        role: str, project_agents: list[Any] | None = None,
    ) -> str | None:
        """将概念角色名映射到实际项目 Agent 名称。

        比 DeepSeekPlanner._resolve_agent_name 更通用，
        支持基于 capabilities 匹配。
        """
        if not project_agents:
            return None

        role_keywords: dict[str, list[str]] = {
            "frontend-agent": ["frontend", "vue", "react", "前端"],
            "backend-agent": ["backend", "flask", "springboot", "fastapi", "后端"],
            "netty-agent": ["netty"],
            "rag-agent": ["rag", "检索", "知识库"],
            "file-agent": ["file-ops", "文件"],
            "doc-agent": ["document", "文档", "doc-diff"],
        }

        keywords = role_keywords.get(role, [role.replace("-agent", "")])

        # 第一阶段: 精确名称匹配
        for a in project_agents:
            name = getattr(a, "name", "")
            if any(kw in name for kw in keywords):
                return name

        # 第二阶段: capabilities 匹配
        for a in project_agents:
            caps = getattr(a, "capabilities", ())
            if any(kw in str(c).lower() for kw in keywords for c in caps):
                return getattr(a, "name", None)

        # 第三阶段: agent_type 回退
        for a in project_agents:
            atype = getattr(a, "agent_type", "")
            if atype == "claude":
                return getattr(a, "name", None)

        return None

    # ── 内部评分 ──────────────────────────────────────────────────

    def _score_agent(
        self,
        profile: AgentProfile,
        obj_lower: str,
        required_tools: set[str],
        required_capabilities: set[str],
        workloads: dict[str, int],
    ) -> SelectionScore:
        score = SelectionScore(agent_name=profile.name)

        # ── 强制规则检查 ──
        for forbidden in profile.forbidden_tasks:
            if forbidden.lower() in obj_lower:
                score.excluded = True
                score.exclusion_reason = f"命中禁止任务: {forbidden}"
                return score

        for limitation in profile.limitations:
            if limitation.lower() in obj_lower:
                score.excluded = True
                score.exclusion_reason = f"任务涉及已知限制: {limitation}"
                return score

        # ── 能力匹配 (0-1) ──
        caps = [c.lower() for c in profile.capabilities]
        if required_capabilities:
            matched_caps = [c for c in required_capabilities if c.lower() in caps or any(c.lower() in cap for cap in caps)]
            missing_caps = [c for c in required_capabilities if c not in matched_caps]
            score.capability_match = len(matched_caps) / len(required_capabilities) if required_capabilities else 0.5
            score.matched_capabilities = matched_caps
            score.missing_capabilities = missing_caps
        else:
            score.capability_match = sum(1 for c in caps if c in obj_lower) / max(len(caps), 1) if caps else 0.3

        # ── 工具匹配 (0-1) ──
        agent_tools = {t.lower() for t in profile.tools}
        if required_tools:
            matched_tools = required_tools & agent_tools
            score.tool_match = len(matched_tools) / len(required_tools) if required_tools else 0.5
            if len(matched_tools) < len(required_tools):
                score.excluded = True
                score.exclusion_reason = f"缺少必要工具: {required_tools - agent_tools}"
                return score
        else:
            score.tool_match = 0.5  # 无要求时中性

        # ── 任务偏好匹配 (0-1) ──
        prefs = [p.lower() for p in profile.preferred_tasks]
        if prefs:
            score.preference_match = sum(1 for p in prefs if p in obj_lower) / len(prefs)
        else:
            score.preference_match = 0.0

        # ── 优先级加成 (0-0.15) ──
        score.priority_bonus = min(profile.priority / 10, 1.0) * 0.15

        # ── 负载惩罚 (0-0.1) ──
        current_load = workloads.get(profile.name, 0)
        score.workload_penalty = min(current_load * 0.05, 0.1)

        # ── 综合评分 ──
        score.score = (
            score.capability_match * 0.35 +
            score.tool_match * 0.25 +
            score.preference_match * 0.15 +
            score.priority_bonus +
            0.10  # 基础分
            - score.workload_penalty
        )
        score.score = max(0.0, min(1.0, score.score))

        # ── 生成选择原因 ──
        reasons = []
        if score.matched_capabilities:
            reasons.append(f"能力匹配: {', '.join(score.matched_capabilities)}")
        if score.preference_match > 0:
            reasons.append(f"任务偏好匹配")
        if score.priority_bonus > 0:
            reasons.append(f"优先级 {profile.priority}")
        score.selection_reason = "; ".join(reasons) if reasons else "默认选择"

        return score
