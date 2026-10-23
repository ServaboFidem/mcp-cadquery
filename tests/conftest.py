"""Shared fixtures: src on sys.path, fake upstream, jailed workspace."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parent
FAKE_UPSTREAM = TESTS_DIR / "fixtures" / "fake_upstream"
SRC_DIR = TESTS_DIR.parent / "src"

sys.path.insert(0, str(SRC_DIR))

import cadquery_dxl_mcp.upstream as upstream_mod  # noqa: E402


@pytest.fixture
def workspace_root(tmp_path: Path) -> Path:
    root = tmp_path / "workspace"
    (root / "exports").mkdir(parents=True)
    return root


@pytest.fixture
def loaded_upstream(monkeypatch: pytest.MonkeyPatch):
    """Load the fake upstream through the real loader (env override path)."""
    monkeypatch.setenv(upstream_mod.UPSTREAM_SRC_ENV, str(FAKE_UPSTREAM))
    _drop_upstream_modules()
    up = upstream_mod.load_upstream()
    yield up
    _drop_upstream_modules()


def _drop_upstream_modules() -> None:
    for mod in [
        m
        for m in list(sys.modules)
        if m == "mcp_cadquery_server" or m.startswith("mcp_cadquery_server.")
    ]:
        del sys.modules[mod]
    for mod in [
        m for m in list(sys.modules) if m == "cadquery" or m.startswith("cadquery.")
    ]:
        del sys.modules[mod]


@pytest.fixture
def server_context(workspace_root: Path, loaded_upstream):
    from cadquery_dxl_mcp.server import ServerContext

    return ServerContext(workspace_root=workspace_root, upstream=loaded_upstream)


@pytest.fixture(autouse=True)
def _reset_fake_state():
    yield
    h = sys.modules.get("mcp_cadquery_server.handlers")
    if h is not None:
        for attr in ("PRINT_ON_CALL", "SLEEP_ON_CALL", "FAIL_ONCE", "CALLS"):
            try:
                getattr(h, attr).clear()
            except Exception:
                pass
