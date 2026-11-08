from __future__ import annotations

import io
import logging
import os
import re
from datetime import timedelta
from pathlib import Path

logger = logging.getLogger(__name__)


def _load_env_file(path: Path) -> None:
    if not path.exists() or not path.is_file():
        return
    try:
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()
            if not key:
                continue
            if len(value) >= 2 and (
                (value.startswith('"') and value.endswith('"'))
                or (value.startswith("'") and value.endswith("'"))
            ):
                value = value[1:-1]
            os.environ[key] = value
    except Exception as exc:
        logger.warning("Failed to load env file %s: %s", path, exc)


def _load_local_env_files() -> None:
    current = Path(__file__).resolve()
    backend_root = current.parents[2]
    project_root = current.parents[3]
    for candidate in (backend_root / ".env", project_root / ".env"):
        _load_env_file(candidate)


_load_local_env_files()

MINIO_ENABLED = os.getenv("MINIO_ENABLED", "true").lower() == "true"
MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "127.0.0.1:9000").strip()
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minioadmin").strip()
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minioadmin").strip()
MINIO_SECURE = os.getenv("MINIO_SECURE", "false").lower() == "true"
MINIO_BUCKET = os.getenv("MINIO_BUCKET", "carbon-knowledge").strip()
MINIO_PUBLIC_BASE_URL = os.getenv("MINIO_PUBLIC_BASE_URL", "").strip()
MINIO_PRESIGN_EXPIRES_HOURS = int(os.getenv("MINIO_PRESIGN_EXPIRES_HOURS", "72"))


def _get_client():
    from minio import Minio

    return Minio(
        endpoint=MINIO_ENDPOINT,
        access_key=MINIO_ACCESS_KEY,
        secret_key=MINIO_SECRET_KEY,
        secure=MINIO_SECURE,
    )


def _ensure_bucket(client) -> None:
    found = client.bucket_exists(MINIO_BUCKET)
    if not found:
        client.make_bucket(MINIO_BUCKET)


def _safe_name(filename: str) -> str:
    raw = (filename or "unknown").strip()
    raw = raw.replace("\\", "_").replace("/", "_")
    safe = re.sub(r"\s+", "_", raw)
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", safe)
    return safe[:180] or "unknown"


def build_object_key(filename: str, prefix: str = "knowledge") -> str:
    from datetime import datetime

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{prefix}/{ts}_{_safe_name(filename)}"


def _build_public_url(object_key: str) -> str:
    if MINIO_PUBLIC_BASE_URL:
        return f"{MINIO_PUBLIC_BASE_URL.rstrip('/')}/{MINIO_BUCKET}/{object_key}"
    scheme = "https" if MINIO_SECURE else "http"
    return f"{scheme}://{MINIO_ENDPOINT}/{MINIO_BUCKET}/{object_key}"


def upload_bytes(
    content: bytes,
    *,
    filename: str,
    object_key: str | None = None,
    content_type: str | None = None,
) -> dict:
    if not MINIO_ENABLED:
        raise RuntimeError("MinIO is disabled")
    if not content:
        raise ValueError("Empty content is not allowed")

    key = object_key or build_object_key(filename)
    ctype = content_type or "application/octet-stream"
    client = _get_client()
    _ensure_bucket(client)
    stream = io.BytesIO(content)
    result = client.put_object(
        bucket_name=MINIO_BUCKET,
        object_name=key,
        data=stream,
        length=len(content),
        content_type=ctype,
    )
    return {
        "bucket": MINIO_BUCKET,
        "object_key": key,
        "etag": getattr(result, "etag", ""),
        "size": len(content),
        "file_url": _build_public_url(key),
    }


def delete_object(object_key: str) -> None:
    if not MINIO_ENABLED or not object_key:
        return
    client = _get_client()
    try:
        client.remove_object(MINIO_BUCKET, object_key)
    except Exception as exc:
        logger.warning("Failed to delete object from MinIO: %s", exc)


def presigned_url(object_key: str) -> str:
    if not MINIO_ENABLED or not object_key:
        return ""
    client = _get_client()
    try:
        return client.presigned_get_object(
            MINIO_BUCKET,
            object_key,
            expires=timedelta(hours=max(1, MINIO_PRESIGN_EXPIRES_HOURS)),
        )
    except Exception:
        return _build_public_url(object_key)


def check_minio_health() -> tuple[bool, str]:
    if not MINIO_ENABLED:
        return False, "MINIO disabled"
    try:
        client = _get_client()
        _ensure_bucket(client)
        return True, "ok"
    except Exception as exc:
        return False, str(exc)

