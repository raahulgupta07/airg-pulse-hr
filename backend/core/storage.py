"""Storage adapter — pluggable backend for CV / file artefacts.

Local filesystem (default, EFS-ready on ECS) or S3 (optional).

Wire-only at the moment: existing upload routes still write to /data/cvs
directly. Migration to `get_storage()` is a follow-on. This module exists
so an ECS task definition can flip STORAGE_BACKEND=s3 once the upload
routes are converted, without touching the image.
"""
from __future__ import annotations

import os
import logging
import secrets
from abc import ABC, abstractmethod
from pathlib import Path

logger = logging.getLogger(__name__)

CV_ROOT = Path(os.getenv("CV_STORAGE_PATH", "/data/cvs"))


class Storage(ABC):
    """Abstract storage adapter."""

    @abstractmethod
    def save(self, filename: str, data: bytes) -> str:
        """Persist `data` under `filename`. Returns canonical path/key."""

    @abstractmethod
    def read(self, path: str) -> bytes:
        """Return raw bytes for the given path/key."""

    @abstractmethod
    def delete(self, path: str) -> None:
        """Remove the object. Idempotent: missing path is not an error."""

    @abstractmethod
    def exists(self, path: str) -> bool:
        """Return True iff the object is retrievable."""

    @abstractmethod
    def signed_url(self, path: str, ttl_s: int = 300) -> str:
        """Return a time-limited URL the browser can GET directly."""


# ---------------------------------------------------------------------------
# Local filesystem (current behaviour; EFS-mounted in ECS)
# ---------------------------------------------------------------------------
class LocalStorage(Storage):
    def __init__(self, root: Path | None = None):
        self.root = Path(root) if root else CV_ROOT
        try:
            self.root.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            logger.warning(f"[storage.local] could not ensure root {self.root}: {e}")

    def _resolve(self, path: str) -> Path:
        p = Path(path)
        # Allow absolute paths under root, otherwise treat as relative
        if p.is_absolute():
            return p
        return self.root / p

    def save(self, filename: str, data: bytes) -> str:
        # Light dedup-by-suffix to avoid clobber. Caller may already have unique names.
        dest = self._resolve(filename)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            stem, suffix = dest.stem, dest.suffix
            dest = dest.with_name(f"{stem}_{secrets.token_hex(4)}{suffix}")
        dest.write_bytes(data)
        return str(dest)

    def read(self, path: str) -> bytes:
        return self._resolve(path).read_bytes()

    def delete(self, path: str) -> None:
        try:
            self._resolve(path).unlink()
        except FileNotFoundError:
            pass

    def exists(self, path: str) -> bool:
        return self._resolve(path).is_file()

    def signed_url(self, path: str, ttl_s: int = 300) -> str:
        # Preserve existing API surface — actual HMAC signing lives in the
        # candidates route (`/candidates/{id}/file/sign`). Here we just hand
        # back the relative path; callers with a candidate_id should use
        # the route to mint the HMAC URL.
        return f"/candidates/file?path={path}&ttl={ttl_s}"


# ---------------------------------------------------------------------------
# S3 (lazy boto3 import — only loaded when STORAGE_BACKEND=s3)
# ---------------------------------------------------------------------------
class S3Storage(Storage):
    def __init__(self, bucket: str | None = None, region: str | None = None):
        self.bucket = bucket or os.getenv("S3_BUCKET")
        self.region = region or os.getenv("S3_REGION", "us-east-1")
        if not self.bucket:
            raise RuntimeError("S3Storage requires S3_BUCKET env var")
        # Lazy import — keeps boto3 optional for local/dev installs
        try:
            import boto3  # noqa: WPS433
        except ImportError as e:
            raise RuntimeError(
                "boto3 not installed — `pip install boto3` to use STORAGE_BACKEND=s3"
            ) from e
        self._boto3 = boto3
        self._client = boto3.client("s3", region_name=self.region)

    def _key(self, path: str) -> str:
        # Strip any leading /data/cvs/ so existing paths work transparently
        return path.lstrip("/").replace("data/cvs/", "", 1)

    def save(self, filename: str, data: bytes) -> str:
        key = self._key(filename)
        self._client.put_object(Bucket=self.bucket, Key=key, Body=data)
        return key

    def read(self, path: str) -> bytes:
        obj = self._client.get_object(Bucket=self.bucket, Key=self._key(path))
        return obj["Body"].read()

    def delete(self, path: str) -> None:
        try:
            self._client.delete_object(Bucket=self.bucket, Key=self._key(path))
        except Exception as e:
            logger.debug(f"[storage.s3] delete swallowed: {e}")

    def exists(self, path: str) -> bool:
        try:
            self._client.head_object(Bucket=self.bucket, Key=self._key(path))
            return True
        except Exception:
            return False

    def signed_url(self, path: str, ttl_s: int = 300) -> str:
        return self._client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": self._key(path)},
            ExpiresIn=int(ttl_s),
        )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------
_storage_singleton: Storage | None = None


def get_storage() -> Storage:
    """Return the configured storage backend (singleton).

    Selection driven by env STORAGE_BACKEND in {"local","s3"}; default "local".
    """
    global _storage_singleton
    if _storage_singleton is not None:
        return _storage_singleton

    backend = (os.getenv("STORAGE_BACKEND") or "local").strip().lower()
    if backend == "s3":
        _storage_singleton = S3Storage()
        logger.info(f"[storage] backend=s3 bucket={_storage_singleton.bucket}")
    else:
        _storage_singleton = LocalStorage()
        logger.info(f"[storage] backend=local root={_storage_singleton.root}")
    return _storage_singleton
