import pytest

from app.logging_config import configure_logging

@pytest.fixture(scope="session", autouse=False)
def logger():
    """
    Configure the logger for tests.
    """
    configure_logging()
    yield
