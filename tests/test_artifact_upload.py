"""R2 artifact upload: env parsing, key shape, presigned links, failure mode."""

from __future__ import annotations

import pytest
from cadquery_dxl_mcp import artifact_upload as au
from cadquery_dxl_mcp.errors import ArtifactUploadError


def _env_file(tmp_path, **overrides):
    values = {
        "DXL_CADQUERY_S3_ENDPOINT": "https://abc.r2.cloudflarestorage.com",
        "DXL_CADQUERY_S3_BUCKET": "dxl-mcp-proxy-artifacts",
        "DXL_CADQUERY_S3_REGION": "auto",
        "DXL_CADQUERY_S3_PREFIX": "cadquery/",
        "DXL_CADQUERY_S3_ACCESS_KEY": "ak",
        "DXL_CADQUERY_S3_SECRET_KEY": "sk",
    }
    values.update(overrides)
    path = tmp_path / "cadquery.env"
    path.write_text(
        "# written by the installer; read by the child\n"
        + "".join(f"{k}={v}\n" for k, v in values.items()),
        encoding="utf-8",
    )
    return path


def test_load_store_reads_installer_env_file(tmp_path):
    store = au.load_store(_env_file(tmp_path))
    assert store is not None
    assert store.endpoint == "https://abc.r2.cloudflarestorage.com"
    assert store.bucket == "dxl-mcp-proxy-artifacts"
    assert store.region == "auto"
    assert store.prefix == "cadquery/"


def test_load_store_none_when_unconfigured(tmp_path):
    assert au.load_store(None) is None
    assert au.load_store(tmp_path / "missing.env") is None
    assert au.load_store(_env_file(tmp_path, DXL_CADQUERY_S3_SECRET_KEY="")) is None
    assert au.load_store(_env_file(tmp_path, DXL_CADQUERY_S3_ENDPOINT="  ")) is None


def test_object_key_joins_prefix_exactly_once():
    store = au.ArtifactStore(
        endpoint="https://x",
        bucket="b",
        region="auto",
        prefix="cadquery",
        access_key="a",
        secret_key="s",
    )
    assert au.object_key(store, "r_0/part.stl") == "cadquery/r_0/part.stl"
    assert au.object_key(store, "/r_0/part.stl") == "cadquery/r_0/part.stl"


def test_upload_puts_bytes_and_returns_presigned_link(tmp_path, stub_s3):
    from cadquery_dxl_mcp.artifact_upload import ArtifactStore, upload_file

    payload = tmp_path / "part.stl"
    payload.write_bytes(b"\x00STL-BINARY\xff")
    store = ArtifactStore(
        endpoint="https://fake",
        bucket="b",
        region="auto",
        prefix="cadquery/",
        access_key="a",
        secret_key="s",
        client_factory=lambda: stub_s3,
    )
    key, url = upload_file(store, payload, "r_0/part.stl", "model/stl")
    assert key == "cadquery/r_0/part.stl"
    assert url.startswith("https://fake-r2/b/cadquery/r_0/part.stl")
    stored = stub_s3.objects[("b", "cadquery/r_0/part.stl")]
    assert stored["data"] == b"\x00STL-BINARY\xff"
    assert stored["content_type"] == "model/stl"


def test_upload_failure_is_typed_never_transport(tmp_path):
    from cadquery_dxl_mcp.artifact_upload import ArtifactStore, upload_file

    class _Boom:
        def put_object(self, **kwargs):
            raise RuntimeError("network down")

    payload = tmp_path / "part.step"
    payload.write_text("step", encoding="utf-8")
    store = ArtifactStore(
        endpoint="https://fake",
        bucket="b",
        region="auto",
        prefix="cadquery/",
        access_key="a",
        secret_key="s",
        client_factory=_Boom,
    )
    with pytest.raises(ArtifactUploadError) as exc_info:
        upload_file(store, payload, "r_0/part.step", "model/step")
    assert "part.step" in str(exc_info.value)
    assert "sk" not in str(exc_info.value).lower()


def test_export_without_store_is_error_naming_storage(workspace_root, loaded_upstream):
    import asyncio

    from cadquery_dxl_mcp.server import ServerContext, execute_tool

    ctx = ServerContext(workspace_root=workspace_root, upstream=loaded_upstream)
    result = asyncio.run(
        execute_tool(
            ctx,
            "export_shape",
            {"result_id": "r_0", "filename": "part.step"},
            request_id="t1",
        )
    )
    assert result.is_error is True
    assert "artifact storage" in result.content[0].text
