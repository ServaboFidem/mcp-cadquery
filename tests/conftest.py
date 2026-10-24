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
def server_context(workspace_root: Path, loaded_upstream, stub_store):
    from cadquery_dxl_mcp.server import ServerContext

    return ServerContext(
        workspace_root=workspace_root,
        upstream=loaded_upstream,
        artifact_store=stub_store,
    )


class _StubS3:
    """Recording stand-in for a boto3 S3 client (no network, no credentials)."""

    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], dict] = {}

    def put_object(self, Bucket, Key, Body, ContentType=None):
        data = Body.read() if hasattr(Body, "read") else bytes(Body)
        self.objects[(Bucket, Key)] = {"data": data, "content_type": ContentType}
        return {}

    def generate_presigned_url(self, operation, Params, ExpiresIn):
        return (
            f"https://fake-r2/{Params['Bucket']}/{Params['Key']}"
            f"?expires={ExpiresIn}"
        )


@pytest.fixture
def stub_s3():
    return _StubS3()


@pytest.fixture
def stub_store(stub_s3):
    from cadquery_dxl_mcp.artifact_upload import ArtifactStore

    return ArtifactStore(
        endpoint="https://fake-r2.example",
        bucket="fake-bucket",
        region="auto",
        prefix="cadquery/",
        access_key="fake-access",
        secret_key="fake-secret",
        client_factory=lambda: stub_s3,
    )


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
