"""Object storage abstraction (Phase 19).

PostgreSQL is the source of truth for metadata (FileRecord); the bytes
live here. Two backends behind one interface (settings OBJECT_STORE_BACKEND):

- ``local`` — filesystem directory ``OBJECT_STORE_LOCAL_PATH``. Zero
  extra dependencies, default for development and single-host deploys.
- ``s3`` — any S3-compatible provider (AWS S3, MinIO, Cloudflare R2…).
  Requires ``boto3`` when selected; otherwise raises a clear error at
  first use so the Docker image stays lean by default.

Design: S3 is for durable large bytes only. Never put authoritative
state here; PostgreSQL stays source of truth (audit phase 21).
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class ObjectStore(ABC):
    """Minimal bytes store contract."""

    @abstractmethod
    def put(self, object_key: str, data: bytes, mime_type: str = "application/octet-stream") -> None:
        """Store bytes under ``object_key`` (overwrites if it exists)."""

    @abstractmethod
    def get(self, object_key: str) -> bytes:
        """Fetch bytes; raises FileNotFoundError when missing."""

    @abstractmethod
    def delete(self, object_key: str) -> bool:
        """Delete; True when the key existed."""

    @abstractmethod
    def exists(self, object_key: str) -> bool:
        pass

    def generate_download_url(self, object_key: str, expires_s: int = 3600) -> str | None:
        """Presigned URL when the backend supports it, else None."""
        return None
