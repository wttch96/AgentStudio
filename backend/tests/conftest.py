from pathlib import Path
import shutil

import pytest

from app import create_app
from app.config import Settings


@pytest.fixture()
def app(tmp_path: Path):
    source_agents = Path(__file__).resolve().parents[2] / "agents"
    workspace = tmp_path / "workspace"
    shutil.copytree(source_agents, workspace / "agents")
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
