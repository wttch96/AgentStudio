"""Agent 配置模型测试 —— 旧配置兼容 + 新字段生效。"""

import pytest
from pydantic import ValidationError

from app.domain.models import Project, ProjectAgent, ReviewDecision


class TestAgentConfigBackwardCompat:
    """旧配置（仅有基础字段）必须正常加载。"""

    def test_minimal_config_loads(self):
        """仅有必填字段的旧配置应加载成功，新字段使用默认值。"""
        p = ProjectAgent(
            project_id="test",
            name="simple-agent",
            display_name="Simple",
            system_prompt="You are a simple agent with enough characters for validation",
        )
        assert p.name == "simple-agent"
        assert p.capabilities == []
        assert p.limitations == []
        assert p.preferred_tasks == []
        assert p.forbidden_tasks == []
        assert p.priority == 0
        assert p.max_iterations == 3
        assert p.input_contract == {}
        assert p.output_contract == {}

    def test_mixed_config_loads(self):
        """部分新字段的配置应加载成功。"""
        p = ProjectAgent(
            project_id="test",
            name="partial-agent",
            display_name="Partial",
            system_prompt="You are a partial agent with enough characters here",
            capabilities=["coding"],
            priority=5,
        )
        assert p.capabilities == ["coding"]
        assert p.priority == 5
        assert p.limitations == []  # 未设置的字段使用默认值
        assert p.forbidden_tasks == []


class TestAgentConfigEnhanced:
    """新配置字段应正确加载和校验。"""

    def test_full_config_loads(self):
        """所有新字段均被正确解析。"""
        p = ProjectAgent(
            project_id="test",
            name="full-agent",
            display_name="Full Featured",
            system_prompt="You are a fully featured agent with enough characters for validation tests",
            capabilities=["frontend", "vue", "api-integration"],
            limitations=["no-database", "no-auth"],
            preferred_tasks=["ui", "component"],
            forbidden_tasks=["database-migration"],
            input_contract={"files": "list of file paths"},
            output_contract={"report": "summary of changes"},
            dependencies_info=["node >= 20"],
            priority=7,
            max_iterations=5,
        )
        assert len(p.capabilities) == 3
        assert p.limitations == ["no-database", "no-auth"]
        assert p.forbidden_tasks == ["database-migration"]
        assert p.priority == 7
        assert p.max_iterations == 5

    def test_priority_bounds(self):
        """priority 必须在 0-10 范围内。"""
        with pytest.raises(Exception):
            ProjectAgent(
                project_id="test",
                name="bad-priority",
                display_name="Bad",
                system_prompt="Agent with bad priority value that should fail validation",
                priority=11,
            )
        with pytest.raises(Exception):
            ProjectAgent(
                project_id="test",
                name="bad-priority-neg",
                display_name="Bad",
                system_prompt="Agent with negative priority that should fail validation",
                priority=-1,
            )

    def test_max_iterations_bounds(self):
        """max_iterations 必须在 1-20 范围内。"""
        with pytest.raises(Exception):
            ProjectAgent(
                project_id="test",
                name="bad-iter",
                display_name="Bad",
                system_prompt="Agent with bad max_iterations value for validation test",
                max_iterations=0,
            )
        with pytest.raises(Exception):
            ProjectAgent(
                project_id="test",
                name="bad-iter-2",
                display_name="Bad",
                system_prompt="Agent with max_iterations exceeding limit for validation test",
                max_iterations=21,
            )


@pytest.mark.parametrize(
    "mode",
    ["manual", "editAutomatically", "plan", "auto"],
)
def test_project_modes_are_valid(mode):
    project = Project(
        id="mode-project",
        name="Mode Project",
        root_dir="/tmp/mode-project",
        mode=mode,
    )
    assert project.mode == mode


def test_unknown_project_mode_is_rejected():
    with pytest.raises(ValidationError):
        Project(
            id="bad-mode-project",
            name="Bad Mode",
            root_dir="/tmp/bad-mode",
            mode="dangerously-skip-everything",
        )


class TestReviewDecision:
    """审查决策枚举测试。"""

    def test_all_values(self):
        """所有 ReviewDecision 值应可访问。"""
        values = {d.value for d in ReviewDecision}
        assert "accepted" in values
        assert "accepted_with_risks" in values
        assert "revision_required" in values
        assert "rejected" in values
        assert "blocked" in values

    def test_from_string(self):
        """字符串应能转换为 ReviewDecision。"""
        assert ReviewDecision("accepted") == ReviewDecision.ACCEPTED
        assert ReviewDecision("revision_required") == ReviewDecision.REVISION_REQUIRED
