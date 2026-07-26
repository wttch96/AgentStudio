"""Agent 选择器测试 —— 评分、规则过滤、能力匹配。"""

import pytest

from app.agents.registry import AgentProfile, AgentRegistry
from app.agents.agent_selector import AgentSelector, SelectionScore


class FakeRegistry:
    """模拟 AgentRegistry，避免文件系统依赖。"""

    def __init__(self, profiles: dict[str, AgentProfile] | None = None):
        self._profiles = profiles or {}

    def load_project_agents(self, project_id: str) -> dict[str, AgentProfile]:
        return self._profiles

    def _load_from_files(self, project_id: str) -> dict[str, AgentProfile]:
        return self._profiles


def _make_profile(name: str, agent_type: str = "claude",
                  capabilities: list[str] | None = None,
                  limitations: list[str] | None = None,
                  preferred_tasks: list[str] | None = None,
                  forbidden_tasks: list[str] | None = None,
                  priority: int = 0) -> AgentProfile:
    return AgentProfile(
        name=name, agent_type=agent_type,
        capabilities=capabilities or [],
        limitations=limitations or [],
        preferred_tasks=preferred_tasks or [],
        forbidden_tasks=forbidden_tasks or [],
        priority=priority,
    )


class TestAgentSelectionScoring:
    """基本选择和评分测试。"""

    def test_select_frontend_task(self):
        """前端任务应选择前端 Agent。"""
        registry = FakeRegistry({
            "frontend": _make_profile("frontend", capabilities=["frontend", "vue"],
                                       preferred_tasks=["ui", "frontend"]),
            "backend": _make_profile("backend", capabilities=["backend", "api"],
                                      preferred_tasks=["api", "backend"]),
        })
        selector = AgentSelector(registry)
        result = selector.select("test", "实现一个新的页面组件")
        assert result is not None
        assert result.agent_name == "frontend"

    def test_select_backend_task(self):
        """后端任务应选择后端 Agent。"""
        registry = FakeRegistry({
            "frontend": _make_profile("frontend", capabilities=["frontend"]),
            "backend": _make_profile("backend", capabilities=["backend", "api"]),
        })
        selector = AgentSelector(registry)
        result = selector.select("test", "设计并实现REST API接口")
        assert result is not None
        assert result.agent_name == "backend"

    def test_forbidden_task_exclusion(self):
        """forbidden_tasks 命中时应排除 Agent。"""
        registry = FakeRegistry({
            "safe-agent": _make_profile("safe-agent", capabilities=["coding"]),
            "restricted": _make_profile("restricted", capabilities=["coding"],
                                         forbidden_tasks=["database"]),
        })
        selector = AgentSelector(registry)
        result = selector.select("test", "执行数据库迁移任务")
        assert result is not None
        assert result.agent_name == "safe-agent"

    def test_no_suitable_agent(self):
        """没有合适 Agent 时返回 None。"""
        registry = FakeRegistry({})
        selector = AgentSelector(registry)
        result = selector.select("test", "任意任务")
        assert result is None

    def test_priority_weighting(self):
        """高优先级 Agent 应有更高分数。"""
        registry = FakeRegistry({
            "low": _make_profile("low", capabilities=["coding"], priority=2),
            "high": _make_profile("high", capabilities=["coding"], priority=8),
        })
        selector = AgentSelector(registry)
        result = selector.select("test", "编写代码")
        assert result is not None
        assert result.agent_name == "high"

    def test_top_k_candidates(self):
        """select_top_k 应返回多个候选。"""
        registry = FakeRegistry({
            "a": _make_profile("a", capabilities=["frontend"], priority=8),
            "b": _make_profile("b", capabilities=["backend"], priority=5),
            "c": _make_profile("c", capabilities=["fullstack"], priority=3),
        })
        selector = AgentSelector(registry)
        candidates = selector.select_top_k("test", "实现功能", k=2)
        assert len(candidates) <= 2
        assert len(candidates) > 0


class TestAgentValidation:
    """Agent 分配验证测试。"""

    def test_validate_assignment_valid(self):
        """合规的分配应通过验证。"""
        profile = _make_profile("test", forbidden_tasks=["database-migration"])
        selector = AgentSelector(FakeRegistry())
        is_valid, reason = selector.validate_assignment(profile, "编写前端代码")
        assert is_valid is True
        assert "通过" in reason

    def test_validate_assignment_forbidden(self):
        """禁止任务命中时应拒绝。"""
        profile = _make_profile("test", forbidden_tasks=["database-migration"])
        selector = AgentSelector(FakeRegistry())
        is_valid, reason = selector.validate_assignment(profile, "执行数据库迁移")
        assert is_valid is False
        assert "禁止" in reason

    def test_validate_assignment_limitation(self):
        """限制命中时应拒绝。"""
        profile = _make_profile("test", limitations=["no-auth-module"])
        selector = AgentSelector(FakeRegistry())
        is_valid, reason = selector.validate_assignment(profile, "修改认证模块代码")
        assert is_valid is False


class TestRoleResolution:
    """角色解析测试。"""

    def test_resolve_frontend_role(self):
        """应能解析 frontend-agent 角色。"""
        agents = [
            _make_profile("vue-frontend", capabilities=["frontend", "vue"]),
            _make_profile("flask-backend", capabilities=["backend", "flask"]),
        ]
        result = AgentSelector.resolve_role("frontend-agent", agents)
        assert result is not None
        assert "frontend" in result

    def test_resolve_backend_role(self):
        """应能解析 backend-agent 角色。"""
        agents = [
            _make_profile("vue-frontend", capabilities=["frontend"]),
            _make_profile("flask-backend", capabilities=["backend"]),
        ]
        result = AgentSelector.resolve_role("backend-agent", agents)
        assert result is not None
        assert "backend" in result
