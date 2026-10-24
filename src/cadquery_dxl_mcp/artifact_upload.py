"""R2 artifact upload for export tools: bytes bypass MCP, callers get a link.

Remote callers cannot read server-side paths, and stuffing multi-megabyte
STL through a JSON tool result means buffering the whole payload in the
proxy. So exports go direct to R2 (the real-esrgan shape): the shim PUTs
the file and returns a presigned GET URL. The proxy's artifact spillover
never sees the bytes; the result stays a small JSON summary.

Credentials reach the child by reference only: ``--env-file`` names a
``KEY=VALUE`` file (SYSTEM + Administrators only, written by installer
step 2, never logged). Values are read into an ``ArtifactStore``; nothing
is copied into ``os.environ`` and nothing secret is ever logged.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import ArtifactUploadError

#: Keys the shim reads from the env file. Anything else in the file is
#: ignored: the store carries exactly these six.
_ENDPOINT_KEY = "DXL_CADQUERY_S3_ENDPOINT"
_BUCKET_KEY = "DXL_CADQUERY_S3_BUCKET"
_REGION_KEY = "DXL_CADQUERY_S3_REGION"
_PREFIX_KEY = "DXL_CADQUERY_S3_PREFIX"
_ACCESS_KEY = "DXL_CADQUERY_S3_ACCESS_KEY"
_SECRET_KEY = "DXL_CADQUERY_S3_SECRET_KEY"

#: How long the returned download links stay valid (seconds). Long enough
#: for a remote caller to fetch a massive STL; short enough that a leaked
#: tool result is not a permanent public link.
PRESIGNED_TTL_SECS = 3600


@dataclass(frozen=True)
class ArtifactStore:
    """R2 coordinates for export uploads, plus a client factory (stubbed in tests)."""

    endpoint: str
    bucket: str
    region: str
    prefix: str
    access_key: str
    secret_key: str
    client_factory: Callable[[], Any] | None = None


def load_store(env_file: str | os.PathLike[str] | None) -> ArtifactStore | None:
    """Parse the installer-written env file; ``None`` when not configured.

    A missing path, an unreadable file, or any blank required value means
    "not configured" (never an exception): exports then fail as ``isError``
    naming artifact storage, and `verify-install` reports the same state.
    Comment lines (``#...``) and blank lines are skipped; a ``KEY=VALUE``
    line with an empty value counts as blank. Secret values are never
    logged here or anywhere else.
    """
    if not env_file:
        return None
    try:
        text = Path(env_file).read_text(encoding="utf-8")
    except OSError:
        return None
    values: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip()
    endpoint = values.get(_ENDPOINT_KEY, "")
    bucket = values.get(_BUCKET_KEY, "")
    region = values.get(_REGION_KEY, "") or "auto"
    prefix = values.get(_PREFIX_KEY, "")
    access_key = values.get(_ACCESS_KEY, "")
    secret_key = values.get(_SECRET_KEY, "")
    if not endpoint or not bucket or not access_key or not secret_key:
        return None
    return ArtifactStore(
        endpoint=endpoint,
        bucket=bucket,
        region=region,
        prefix=prefix,
        access_key=access_key,
        secret_key=secret_key,
    )


def _client_for(store: ArtifactStore) -> Any:
    if store.client_factory is not None:
        return store.client_factory()
    try:
        import boto3
        from botocore.config import Config
    except Exception as exc:
        raise ArtifactUploadError(
            f"artifact upload needs boto3: {exc}"
        ) from None
    return boto3.client(
        "s3",
        endpoint_url=store.endpoint,
        aws_access_key_id=store.access_key,
        aws_secret_access_key=store.secret_key,
        region_name=store.region,
        config=Config(
            signature_version="s3v4", s3={"addressing_style": "path"}
        ),
    )


def object_key(store: ArtifactStore, name: str) -> str:
    """Object key for an export: ``<prefix><name>``, exactly one separator."""
    prefix = (store.prefix or "").lstrip("/")
    if prefix and not prefix.endswith("/"):
        prefix += "/"
    return f"{prefix}{name.lstrip('/')}"


def upload_file(
    store: ArtifactStore,
    path: Path,
    name: str,
    content_type: str,
) -> tuple[str, str]:
    """PUT one export to R2; return ``(key, presigned_url)``.

    The payload streams from disk (no whole-file buffering beyond what
    boto3's multipart handling does internally). Failures are
    ``ArtifactUploadError`` (tool-level ``isError``, never a broken
    backend); the key/value that failed is named, secret values never are.
    """
    key = object_key(store, name)
    client = _client_for(store)
    try:
        with open(path, "rb") as fh:
            client.put_object(
                Bucket=store.bucket,
                Key=key,
                Body=fh,
                ContentType=content_type,
            )
    except Exception as exc:
        raise ArtifactUploadError(
            f"upload of {name} failed: {type(exc).__name__}: {exc}"
        ) from None
    try:
        url = client.generate_presigned_url(
            "get_object",
            Params={"Bucket": store.bucket, "Key": key},
            ExpiresIn=PRESIGNED_TTL_SECS,
        )
    except Exception as exc:
        raise ArtifactUploadError(
            f"presign of {name} failed: {type(exc).__name__}: {exc}"
        ) from None
    return key, url
