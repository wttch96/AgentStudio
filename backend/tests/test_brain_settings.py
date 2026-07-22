"""验证版本库中的默认主脑模板可直接作为运行默认值。"""

from pathlib import Path

from app.domain.configuration import BrainConfiguration
from app.services.brain_settings import BrainSettings


def test_versioned_brain_template_is_valid_and_used(tmp_path: Path):
    template = Path(__file__).resolve().parents[2] / "config" / "brain.default.json"
    expected = BrainConfiguration.model_validate_json(template.read_text(encoding="utf-8"))

    settings = BrainSettings(tmp_path / "brain.json", template)

    assert settings.current() == expected
    assert "项目发现结果" in expected.planning_prompt
    assert "共享契约" in expected.planning_prompt
