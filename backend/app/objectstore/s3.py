"""S3-compatible object store backend (Phase 19).

Uses ``boto3`` when ``OBJECT_STORE_BACKEND=s3``. Import is lazy so the
default ``local`` backend never requires boto3.
"""

from __future__ import annotations

from app.config import get_settings
from app.objectstore import ObjectStore


class S3ObjectStore(ObjectStore):
    def __init__(self) -> None:
        try:
            import boto3  # type: ignore[import-not-found]
            from botocore.client import Config  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "S3 object store selected but boto3 is not installed: "
                "pip install boto3"
            ) from exc
        settings = get_settings()
        if not settings.object_store_bucket:
            raise ValueError("OBJECT_STORE_BUCKET is required when OBJECT_STORE_BACKEND=s3")
        cfg = Config(signature_version="s3v4", s3={"addressing_style": "path" if settings.object_store_force_path_style else "virtual"})
        self._bucket = settings.object_store_bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=settings.object_store_endpoint or None,
            region_name=settings.object_store_region,
            aws_access_key_id=settings.object_store_access_key or None,
            aws_secret_access_key=settings.object_store_secret_key or None,
            config=cfg,
        )

    def put(self, object_key: str, data: bytes, mime_type: str = "application/octet-stream") -> None:
        self._client.put_object(Bucket=self._bucket, Key=object_key, Body=data, ContentType=mime_type)

    def get(self, object_key: str) -> bytes:
        try:
            resp = self._client.get_object(Bucket=self._bucket, Key=object_key)
            return resp["Body"].read()
        except self._client.exceptions.NoSuchKey as exc:  # type: ignore[attr-defined]
            raise FileNotFoundError(object_key) from exc
        except Exception as exc:  # botocore wraps NoSuchKey differently per provider
            if "NoSuchKey" in str(exc) or "Not Found" in str(exc):
                raise FileNotFoundError(object_key) from exc
            raise

    def delete(self, object_key: str) -> bool:
        # Head first to distinguish missing vs deleted (S3 Delete is idempotent).
        if not self.exists(object_key):
            return False
        self._client.delete_object(Bucket=self._bucket, Key=object_key)
        return True

    def exists(self, object_key: str) -> bool:
        try:
            self._client.head_object(Bucket=self._bucket, Key=object_key)
            return True
        except Exception:
            return False

    def generate_download_url(self, object_key: str, expires_s: int = 3600) -> str | None:
        try:
            return self._client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self._bucket, "Key": object_key},
                ExpiresIn=expires_s,
            )
        except Exception:
            return None
