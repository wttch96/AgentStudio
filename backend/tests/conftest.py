from pathlib import Path
import shutil

import pytest
import yaml

from app import create_app
from app.config import Settings

from fixtures.logger_fixture import logger  # noqa: F401


@pytest.fixture()
def app(tmp_path: Path):
    repository = Path(__file__).resolve().parents[2]
    workspace = tmp_path / "workspace"
    project_id = "test-project"
    project_dir = workspace / ".workspace" / project_id
    shutil.copytree(repository / "templates" / "agents", project_dir / "agents")
    (project_dir / "skills").mkdir(parents=True)
    (project_dir / "flows").mkdir(parents=True)
    (project_dir / "project.yaml").write_text(
        yaml.safe_dump({
            "id": project_id,
            "name": "Test Project",
            "root_dir": str(workspace),
            "description": "",
        }),
        encoding="utf-8",
    )
    (workspace / ".workspace" / "current-project.yaml").write_text(
        yaml.safe_dump({"project_id": project_id}), encoding="utf-8"
    )
    shutil.copytree(repository / "templates", workspace / "templates")
    settings = Settings(
        instance_dir=tmp_path / "instance",
        workspace_root=workspace,
    )
    application = create_app(settings)
    application.config.update(TESTING=True)
    return application


@pytest.fixture()
def client(app):
    return app.test_client()
