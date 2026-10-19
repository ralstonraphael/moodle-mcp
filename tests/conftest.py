import httpx
import pytest

from moodle_mcp import client as mc


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    """Keep every test away from the real ~/.config/moodle-mcp and any MOODLE_* variables."""
    path = tmp_path / "moodle-mcp" / "config.json"
    monkeypatch.setattr(mc, "CONFIG_PATH", path)
    monkeypatch.delenv("MOODLE_URL", raising=False)
    monkeypatch.delenv("MOODLE_TOKEN", raising=False)
    return path


@pytest.fixture
def fake_moodle():
    """Build a Moodle client whose HTTP calls go to `handler(request) -> httpx.Response`."""
    def make(handler):
        c = mc.Moodle(url="https://moodle.example.edu", token="t" * 32)
        c.http = httpx.Client(transport=httpx.MockTransport(handler))
        return c
    return make
