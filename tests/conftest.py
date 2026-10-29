import pytest


@pytest.fixture(scope="session", autouse=True)
def private_history(tmp_path_factory):
    """Tests must not write into the user's own analysis history."""
    from cellsurveillance import history
    home = tmp_path_factory.mktemp("history")
    saved = history.HOME, history.REGISTRY
    history.HOME, history.REGISTRY = str(home), str(home / "history.json")
    yield
    history.HOME, history.REGISTRY = saved
