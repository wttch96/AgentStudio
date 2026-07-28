from pathlib import Path
import shutil

from app.agents.skill_registry import SkillRegistry
from app.config import Settings
from app.services.config_reader import ConfigReader
from app.services.project_manager import ProjectManager


def test_new_project_uses_named_workspace_directory(tmp_path: Path):
    workspace = tmp_path / "studio"
    source = tmp_path / "source"
    workspace.mkdir()
    source.mkdir()
    repository = Path(__file__).resolve().parents[2]
    shutil.copytree(repository / "templates", workspace / "templates")
    reader = ConfigReader(workspace)
    manager = ProjectManager(config_reader=reader)

    project = manager.create_project(
        "Commerce Platform",
        str(source),
        project_name="commerce-platform",
    )

    project_dir = workspace / ".workspace" / "commerce-platform"
    assert project["id"] == "commerce-platform"
    assert (project_dir / "project.yaml").is_file()
    assert (project_dir / "workspace.yaml").is_file()
    assert (project_dir / "scheduler.yaml").is_file()
    assert (project_dir / "memory.yaml").is_file()
    assert (project_dir / "agents").is_dir()
    assert (project_dir / "skills").is_dir()
    assert (project_dir / "flows").is_dir()
    assert (project_dir / "db").is_dir()
    assert (project_dir / "brain.yaml").is_file()
    assert (project_dir / "agents" / "code-reviewer.yaml").is_file()
    assert (project_dir / "skills" / "board-operations.yaml").is_file()
    assert (project_dir / "flows" / "feature-implement.yaml").is_file()


def test_current_project_selects_project_rag_database(tmp_path: Path):
    workspace = tmp_path / "studio"
    current = workspace / ".workspace" / "current-project.yaml"
    current.parent.mkdir(parents=True)
    current.write_text("project_id: alpha-project\n", encoding="utf-8")

    settings = Settings(workspace_root=workspace)

    assert settings.database_path == (
        workspace / ".workspace" / "alpha-project" / "db" / "rag.db"
    )


def test_project_skills_are_isolated(tmp_path: Path):
    workspace = tmp_path / "studio"
    public_skills = workspace / ".claude" / "skills"
    reader = ConfigReader(workspace)
    registry = SkillRegistry(public_skills, config_reader=reader)

    registry.create_project(
        "alpha-project", "shared-skill", "Alpha", "alpha content"
    )
    registry.create_project(
        "beta-project", "shared-skill", "Beta", "beta content"
    )

    assert registry.get_project("alpha-project", "shared-skill")["content"] == "alpha content"
    assert registry.get_project("beta-project", "shared-skill")["content"] == "beta content"
