"""AWS S3 and S3-compatible Object Storage connector implementing ConnectorSDK.

Every operation performs a genuine, SigV4-signed HTTPS round-trip to the target
object store. There is no simulated or fallback success branch anywhere in this
module: a request that was not issued, or that the service rejected, raises a
typed ConnectorError instead of returning a fabricated result.

Supported targets: AWS S3, and S3-compatible services (MinIO, Cloudflare R2,
Wasabi) via a custom ``endpoint_url``. Uses virtual-hosted addressing for AWS
and path-style addressing for custom endpoints.

Implemented with the already-present ``httpx`` (through the SSRF-guarded
SafeHTTPClient) and ``hashlib``/``hmac`` — no additional dependency is introduced.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import time
import xml.etree.ElementTree as ET
from typing import Any, Dict, List
from urllib.parse import quote, urlencode, urlparse

import httpx

from app.connectors import (
    ConnectorSDK,
    ConnectorCategory,
    ConnectorHealthCheck,
    ConnectorErrorCode,
    make_connector_error,
)
from app.connectors.operations import ConnectorOperations
from app.security.safe_http_client import get_safe_http_client

logger = logging.getLogger(__name__)

_ALGORITHM = "AWS4-HMAC-SHA256"
_S3_SERVICE = "s3"
_S3_NS = {"s3": "http://s3.amazonaws.com/doc/2006-03-01/"}


class S3Connector(ConnectorSDK, ConnectorOperations):
    """AWS S3 & S3-compatible Object Storage connector for buckets, uploads, and downloads."""

    connector_id = "s3"
    display_name = "AWS S3 / Object Storage"
    description = "Upload, download, inspect, list, and delete files in AWS S3, Cloudflare R2, MinIO, or Wasabi."
    category = ConnectorCategory.API
    version = "2.0.0"

    def __init__(self) -> None:
        super().__init__(self.connector_id, self.display_name, self.description)
        self.credentials: Dict[str, Any] = {}

    @property
    def node_types(self) -> List[str]:
        return ["s3", "aws_s3"]

    # ------------------------------------------------------------------ #
    # lifecycle
    # ------------------------------------------------------------------ #

    async def connect(self, config: Dict[str, Any]) -> bool:
        self.credentials = config or {}
        creds = self._creds_from(config or {})
        if self._missing_fields(creds):
            return False
        return True

    async def disconnect(self) -> None:
        self.credentials = {}

    async def op_health_check(self) -> ConnectorHealthCheck:
        """Prove connectivity with a real ListBuckets call — never a static verdict."""
        creds = self._creds_from(self.credentials or {})
        missing = self._missing_fields(creds)
        if missing:
            return ConnectorHealthCheck(
                healthy=False,
                message=f"Missing S3 credential fields: {', '.join(missing)}",
            )
        try:
            region = creds.get("region") or "us-east-1"
            url = self._service_endpoint(region, creds) + "/"
            headers = self._signed_headers("GET", url, b"", creds, region)
            async with get_safe_http_client() as client:
                response = await client.request("GET", url, headers=headers, timeout=httpx.Timeout(20.0))
        except Exception as exc:  # pragma: no cover - network dependent
            return ConnectorHealthCheck(healthy=False, message=f"S3 reachable check failed: {exc}")
        if response.status_code >= 400:
            return ConnectorHealthCheck(
                healthy=False,
                message=f"S3 ListBuckets returned HTTP {response.status_code}.",
            )
        try:
            root = ET.fromstring(response.text)
            buckets = [
                (b.findtext("s3:Name", default="", namespaces=_S3_NS) or (b.findtext("Name") or ""))
                for b in root.findall("s3:Bucket", _S3_NS)
            ]
        except ET.ParseError:
            buckets = []
        return ConnectorHealthCheck(
            healthy=True,
            message=f"S3 ListBuckets succeeded ({len(buckets)} bucket(s) visible).",
        )

    # ------------------------------------------------------------------ #
    # operations
    # ------------------------------------------------------------------ #

    async def op_execute(
        self,
        operation: str,
        payload: Dict[str, Any],
        context: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        params = payload or {}
        creds = self._creds_from(
            ((context or {}).get("credentials") or {}).get("aws_s3")
            or ((context or {}).get("credentials") or {}).get("s3")
            or self.credentials
            or {}
        )

        op = (params.get("operation") or operation or "").lower().strip()
        if op in ("health_check", "ping"):
            check = await self.op_health_check()
            return {"output": [check.model_dump()]}

        missing = self._missing_fields(creds)
        if missing:
            raise make_connector_error(
                ConnectorErrorCode.NOT_CONFIGURED,
                "S3 credential is incomplete: missing "
                + ", ".join(missing)
                + ". Configure the credential before running this operation.",
                retryable=False,
            )

        bucket = str(params.get("bucket") or creds.get("bucket_name") or creds.get("bucket") or "").strip()
        if not bucket:
            raise make_connector_error(
                ConnectorErrorCode.NOT_CONFIGURED,
                "Bucket name is required (set it on the node or as the credential's default bucket).",
                retryable=False,
            )

        timeout = httpx.Timeout(float(params.get("timeout_seconds") or 30.0))

        if op in ("upload_file", "put_object"):
            return await self._upload(creds, bucket, params, timeout)
        if op in ("download_file", "get_object"):
            return await self._download(creds, bucket, params, timeout)
        if op in ("head_object", "get_object_metadata"):
            return await self._head(creds, bucket, params, timeout)
        if op in ("list_objects", "list_files"):
            return await self._list(creds, bucket, params, timeout)
        if op in ("delete_object", "delete_file"):
            return await self._delete(creds, bucket, params, timeout)

        raise make_connector_error(
            ConnectorErrorCode.INVALID_OPERATION,
            f"Unsupported S3 operation: {op or operation}",
            retryable=False,
        )

    async def _upload(self, creds: dict, bucket: str, params: dict, timeout: httpx.Timeout) -> Dict[str, Any]:
        key = self._require_key(params, "upload_file")
        if "content" not in params:
            raise make_connector_error(
                ConnectorErrorCode.BAD_REQUEST,
                "S3 'upload_file' requires 'content'.",
                retryable=False,
            )
        content = params.get("content")
        if isinstance(content, str):
            body = content.encode("utf-8")
        elif isinstance(content, bytes):
            body = content
        else:
            body = str(content).encode("utf-8")

        content_type = str(params.get("content_type") or "application/octet-stream")
        url = self._object_url(creds, bucket, key)
        headers = self._signed_headers("PUT", url, body, creds, creds.get("region") or "us-east-1")
        headers["Content-Type"] = content_type

        response = await self._send("PUT", url, headers, body, timeout)
        self._raise_for_status(response, "upload_file", bucket=bucket, key=key)

        return {
            "output": [
                {
                    "status": "uploaded",
                    "bucket": bucket,
                    "key": key,
                    "size_bytes": len(body),
                    "etag": response.headers.get("ETag", ""),
                    "content_type": content_type,
                }
            ]
        }

    async def _download(self, creds: dict, bucket: str, params: dict, timeout: httpx.Timeout) -> Dict[str, Any]:
        key = self._require_key(params, "download_file")
        url = self._object_url(creds, bucket, key)
        headers = self._signed_headers("GET", url, b"", creds, creds.get("region") or "us-east-1")

        response = await self._send("GET", url, headers, None, timeout)
        self._raise_for_status(response, "download_file", bucket=bucket, key=key)

        body = response.content
        content_type = response.headers.get("Content-Type", "application/octet-stream")
        try:
            text = body.decode("utf-8")
            encoding = "utf-8"
        except UnicodeDecodeError:
            text = base64.b64encode(body).decode("ascii")
            encoding = "base64"

        return {
            "output": [
                {
                    "status": "downloaded",
                    "bucket": bucket,
                    "key": key,
                    "size_bytes": len(body),
                    "etag": response.headers.get("ETag", ""),
                    "content_type": content_type,
                    "encoding": encoding,
                    "content": text,
                }
            ]
        }

    async def _head(self, creds: dict, bucket: str, params: dict, timeout: httpx.Timeout) -> Dict[str, Any]:
        """Fetch object metadata with a real signed HEAD request."""
        key = self._require_key(params, "head_object")
        url = self._object_url(creds, bucket, key)
        headers = self._signed_headers("HEAD", url, b"", creds, creds.get("region") or "us-east-1")

        response = await self._send("HEAD", url, headers, None, timeout)
        if response.status_code == 404:
            return {
                "output": [
                    {
                        "status": "not_found",
                        "bucket": bucket,
                        "key": key,
                        "exists": False,
                    }
                ]
            }
        self._raise_for_status(response, "head_object", bucket=bucket, key=key)

        size_header = response.headers.get("Content-Length")
        metadata = {
            name.lower().removeprefix("x-amz-meta-"): value
            for name, value in response.headers.items()
            if name.lower().startswith("x-amz-meta-")
        }
        return {
            "output": [
                {
                    "status": "found",
                    "bucket": bucket,
                    "key": key,
                    "exists": True,
                    "size_bytes": int(size_header) if size_header and size_header.isdigit() else None,
                    "etag": response.headers.get("ETag", ""),
                    "last_modified": response.headers.get("Last-Modified"),
                    "content_type": response.headers.get("Content-Type"),
                    "metadata": metadata,
                }
            ]
        }

    async def _list(self, creds: dict, bucket: str, params: dict, timeout: httpx.Timeout) -> Dict[str, Any]:
        """ListObjectsV2 with real continuation-token pagination."""
        region = creds.get("region") or "us-east-1"
        prefix = str(params.get("prefix") or "")
        max_keys = int(params.get("max_keys") or params.get("page_size") or 1000)
        return_all = bool(params.get("return_all", False))
        token = str(params.get("continuation_token") or "") or None

        objects: List[Dict[str, Any]] = []
        pages = 0
        max_pages = int(params.get("max_pages") or 10)
        next_token: str | None = token
        truncated = False

        while True:
            query: Dict[str, Any] = {"list-type": "2", "max-keys": str(max(1, min(max_keys, 1000)))}
            if prefix:
                query["prefix"] = prefix
            if next_token:
                query["continuation-token"] = next_token
            url = self._bucket_url(creds, bucket) + "?" + urlencode(query, doseq=True)

            headers = self._signed_headers("GET", url, b"", creds, region)
            response = await self._send("GET", url, headers, None, timeout)
            self._raise_for_status(response, "list_objects", bucket=bucket)

            page, next_token, truncated = self._parse_list_response(response.text)
            objects.extend(page)
            pages += 1
            if not next_token or not truncated or (not return_all and pages >= max_pages):
                break
            if return_all and pages >= max_pages:
                break

        return {
            "output": [
                {
                    "status": "listed",
                    "bucket": bucket,
                    "prefix": prefix,
                    "objects": objects,
                    "count": len(objects),
                    "pages_fetched": pages,
                    "is_truncated": bool(truncated and next_token),
                    "continuation_token": next_token or None,
                }
            ]
        }

    async def _delete(self, creds: dict, bucket: str, params: dict, timeout: httpx.Timeout) -> Dict[str, Any]:
        key = self._require_key(params, "delete_object")
        url = self._object_url(creds, bucket, key)
        headers = self._signed_headers("DELETE", url, b"", creds, creds.get("region") or "us-east-1")

        response = await self._send("DELETE", url, headers, None, timeout)
        # S3 returns 204 on success, 404 when the object was already gone.
        if response.status_code == 404:
            return {"output": [{"status": "not_found", "bucket": bucket, "key": key, "deleted": False}]}
        self._raise_for_status(response, "delete_object", bucket=bucket, key=key)
        return {"output": [{"status": "deleted", "bucket": bucket, "key": key, "deleted": True}]}

    # ------------------------------------------------------------------ #
    # HTTP plumbing
    # ------------------------------------------------------------------ #

    async def _send(
        self,
        method: str,
        url: str,
        headers: Dict[str, str],
        body: bytes | None,
        timeout: httpx.Timeout,
    ) -> httpx.Response:
        try:
            async with get_safe_http_client() as client:
                return await client.request(
                    method,
                    url,
                    headers=headers,
                    data=body,
                    timeout=timeout,
                )
        except httpx.TimeoutException as exc:
            raise make_connector_error(
                ConnectorErrorCode.TIMEOUT,
                f"S3 {method} request timed out: {exc}",
                retryable=True,
            ) from exc
        except httpx.HTTPError as exc:
            raise make_connector_error(
                ConnectorErrorCode.PROVIDER_ERROR,
                f"S3 {method} request failed: {exc}",
                retryable=True,
            ) from exc

    def _raise_for_status(
        self,
        response: httpx.Response,
        operation: str,
        **context: str,
    ) -> None:
        if response.status_code < 400:
            return
        detail = self._s3_error_message(response.text)
        ctx = ", ".join(f"{k}={v}" for k, v in context.items())
        if ctx:
            ctx = f" ({ctx})"
        code = {
            401: ConnectorErrorCode.AUTH_FAILED,
            403: ConnectorErrorCode.FORBIDDEN,
            404: ConnectorErrorCode.NOT_FOUND,
            429: ConnectorErrorCode.RATE_LIMITED,
        }.get(response.status_code, ConnectorErrorCode.PROVIDER_ERROR)
        retryable = response.status_code in (429, 500, 502, 503, 504)
        raise make_connector_error(
            code,
            f"S3 {operation} failed with HTTP {response.status_code}{ctx}: {detail}",
            retryable=retryable,
        )

    @staticmethod
    def _s3_error_message(body: str) -> str:
        try:
            root = ET.fromstring(body)
        except (ET.ParseError, TypeError):
            return (body or "").strip()[:300] or "no error body"
        code = root.findtext("Code") or ""
        message = root.findtext("Message") or ""
        return f"{code}: {message}".strip(": ") or (body or "").strip()[:300]

    @staticmethod
    def _parse_list_response(xml_text: str) -> tuple[List[Dict[str, Any]], str | None, bool]:
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as exc:
            raise make_connector_error(
                ConnectorErrorCode.PROVIDER_ERROR,
                f"S3 list_objects returned unparseable XML: {exc}",
                retryable=True,
            ) from exc

        def _t(el: ET.Element, tag: str) -> str:
            return el.findtext(f"s3:{tag}", default="", namespaces=_S3_NS) or el.findtext(tag) or ""

        items: List[Dict[str, Any]] = []
        for contents in root.findall("s3:Contents", _S3_NS) or root.findall("Contents"):
            items.append(
                {
                    "key": _t(contents, "Key"),
                    "size": int(_t(contents, "Size") or 0),
                    "last_modified": _t(contents, "LastModified"),
                    "etag": _t(contents, "ETag"),
                    "storage_class": _t(contents, "StorageClass"),
                }
            )
        truncated = (_t(root, "IsTruncated") or "").lower() == "true"
        next_token = _t(root, "NextContinuationToken") or None
        return items, next_token, truncated

    # ------------------------------------------------------------------ #
    # addressing & signing
    # ------------------------------------------------------------------ #

    @staticmethod
    def _missing_fields(creds: dict) -> List[str]:
        required = ("access_key_id", "secret_access_key")
        return [f for f in required if not str(creds.get(f) or "").strip()]

    @staticmethod
    def _creds_from(raw: dict) -> Dict[str, Any]:
        """Normalise credential field aliases used across the credential store."""
        access = str(raw.get("access_key_id") or raw.get("access_key") or raw.get("aws_access_key_id") or "").strip()
        secret = str(
            raw.get("secret_access_key") or raw.get("secret_key") or raw.get("aws_secret_access_key") or ""
        ).strip()
        region = str(raw.get("region") or raw.get("aws_region") or "us-east-1").strip() or "us-east-1"
        endpoint = str(raw.get("endpoint_url") or "").strip().rstrip("/")
        return {
            "access_key_id": access,
            "secret_access_key": secret,
            "region": region,
            "endpoint_url": endpoint,
            "session_token": str(raw.get("session_token") or "").strip(),
            "bucket_name": str(raw.get("bucket_name") or raw.get("bucket") or "").strip(),
        }

    @staticmethod
    def _require_key(params: dict, operation: str) -> str:
        key = str(params.get("key") or "").strip().lstrip("/")
        if not key:
            raise make_connector_error(
                ConnectorErrorCode.BAD_REQUEST,
                f"S3 '{operation}' requires an object 'key'.",
                retryable=False,
            )
        return key

    @staticmethod
    def _service_endpoint(region: str, creds: dict) -> str:
        """Bucket-less endpoint (ListBuckets), custom endpoint aware."""
        if creds.get("endpoint_url"):
            return creds["endpoint_url"]
        if region == "us-east-1":
            return "https://s3.amazonaws.com"
        return f"https://s3.{region}.amazonaws.com"

    @classmethod
    def _bucket_url(cls, creds: dict, bucket: str) -> str:
        region = creds.get("region") or "us-east-1"
        if creds.get("endpoint_url"):
            # path-style: <endpoint>/<bucket> — required by MinIO/R2 style hosts
            return f"{creds['endpoint_url']}/{quote(bucket, safe='')}"
        host = f"{bucket}.s3.{region}.amazonaws.com" if region != "us-east-1" else f"{bucket}.s3.amazonaws.com"
        return f"https://{host}"

    @classmethod
    def _object_url(cls, creds: dict, bucket: str, key: str) -> str:
        encoded_key = quote(key, safe="/-_.~")
        return f"{cls._bucket_url(creds, bucket)}/{encoded_key}"

    @staticmethod
    def _canonical_uri(url: str) -> str:
        path = urlparse(url).path or "/"
        # already percent-encoded by quote(); keep as-is for the canonical form
        return path

    @classmethod
    def _signed_headers(
        cls,
        method: str,
        url: str,
        payload: bytes,
        creds: dict,
        region: str,
    ) -> Dict[str, str]:
        """Build SigV4 headers for an S3 request (service ``s3``)."""
        access = creds["access_key_id"]
        secret = creds["secret_access_key"]
        parsed = urlparse(url)
        host = parsed.netloc

        now = time.gmtime()
        amz_date = time.strftime("%Y%m%dT%H%M%SZ", now)
        date_stamp = time.strftime("%Y%m%d", now)
        payload_hash = hashlib.sha256(payload or b"").hexdigest()

        headers: Dict[str, str] = {
            "host": host,
            "x-amz-content-sha256": payload_hash,
            "x-amz-date": amz_date,
        }
        if creds.get("session_token"):
            headers["x-amz-security-token"] = creds["session_token"]

        signed_names = sorted(headers)
        canonical_headers = "".join(f"{k}:{headers[k].strip()}\n" for k in signed_names)
        signed_headers = ";".join(signed_names)

        canonical_query = parsed.query or ""
        canonical_request = "\n".join(
            [
                method.upper(),
                cls._canonical_uri(url),
                canonical_query,
                canonical_headers,
                signed_headers,
                payload_hash,
            ]
        )

        scope = f"{date_stamp}/{region}/{_S3_SERVICE}/aws4_request"
        string_to_sign = "\n".join(
            [
                _ALGORITHM,
                amz_date,
                scope,
                hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
            ]
        )

        def _hmac(key: bytes, msg: str) -> bytes:
            return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()

        k_signing = _hmac(
            _hmac(_hmac(_hmac(f"AWS4{secret}".encode(), date_stamp), region), _S3_SERVICE), "aws4_request"
        )
        signature = hmac.new(k_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

        headers["Authorization"] = (
            f"{_ALGORITHM} Credential={access}/{scope}, SignedHeaders={signed_headers}, Signature={signature}"
        )
        # `host` is supplied by the transport; keep it out of the returned headers.
        headers.pop("host", None)
        return headers
