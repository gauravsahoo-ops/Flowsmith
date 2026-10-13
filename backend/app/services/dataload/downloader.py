"""Secure streaming HTTP/HTTPS file downloader with strict SSRF protection for Flowsmith DataLoad."""

from __future__ import annotations

import asyncio
import logging
import os
import re
from typing import Any
from urllib.parse import urlparse, urljoin

import httpx

from app.engine.errors import NodeExecutionError
from app.services.dataload.ssrf_validator import validate_download_url, redact_sensitive_url

logger = logging.getLogger(__name__)


class SecureFileDownloader:
    """Enterprise file downloader enforcing SSRF guards, size caps, and authentication."""

    DEFAULT_TIMEOUT_SECONDS = 30.0
    DEFAULT_MAX_DOWNLOAD_BYTES = 52_428_800  # 50 MB
    MAX_REDIRECTS = 5

    @classmethod
    async def download_file(
        cls,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        auth_type: str = "none",  # none | bearer | basic | custom_header
        auth_token: str = "",
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_download_bytes: int = DEFAULT_MAX_DOWNLOAD_BYTES,
        allow_loopback_in_dev: bool = False,
        node_id: str = "data_load",
    ) -> tuple[bytes, str, dict[str, Any]]:
        """Securely download a file with step-by-step redirect inspection and streaming size limits.

        Returns:
            (file_bytes, filename_hint, metadata)
        """
        current_url = url.strip()
        redacted_initial_url = redact_sensitive_url(current_url)
        logger.info("Initiating secure file download from %s (size cap: %d bytes)", redacted_initial_url, max_download_bytes)

        # 1. Initial SSRF check
        await validate_download_url(
            current_url,
            node_id=node_id,
            allow_loopback_in_dev=allow_loopback_in_dev,
        )

        # Prepare request headers
        req_headers: dict[str, str] = {
            "User-Agent": "Flowsmith-DataLoad/2.0 (Universal Ingestion Engine)",
            "Accept": "*/*",
        }
        if headers:
            req_headers.update(headers)

        # Attach authentication credentials
        if auth_type == "bearer" and auth_token:
            clean_token = auth_token.strip()
            if not clean_token.lower().startswith("bearer "):
                clean_token = f"Bearer {clean_token}"
            req_headers["Authorization"] = clean_token
        elif auth_type == "basic" and auth_token:
            import base64
            clean_token = auth_token.strip()
            if ":" in clean_token:
                b64 = base64.b64encode(clean_token.encode("utf-8")).decode("utf-8")
                req_headers["Authorization"] = f"Basic {b64}"
            else:
                if not clean_token.lower().startswith("basic "):
                    clean_token = f"Basic {clean_token}"
                req_headers["Authorization"] = clean_token

        redirect_count = 0
        final_response_headers: dict[str, str] = {}
        chunks: list[bytes] = []
        total_downloaded = 0
        filename_hint = ""

        # Use httpx without automatic redirect following so each redirect hop is checked for SSRF
        client_timeout = httpx.Timeout(timeout_seconds, connect=10.0)

        # Retry logic for transient failures (max 2 retries on 502/503/504)
        max_attempts = 2
        for attempt in range(max_attempts):
            try:
                while True:
                    async with httpx.AsyncClient(
                        follow_redirects=False,
                        timeout=client_timeout,
                        verify=True,
                    ) as client:
                        async with client.stream("GET", current_url, headers=req_headers) as response:
                            # Check redirect status codes (301, 302, 303, 307, 308)
                            if response.status_code in (301, 302, 303, 307, 308):
                                redirect_count += 1
                                if redirect_count > cls.MAX_REDIRECTS:
                                    raise NodeExecutionError(
                                        f"Download failed: Exceeded maximum redirect limit ({cls.MAX_REDIRECTS}).",
                                        code="REDIRECT_LIMIT_EXCEEDED",
                                        node_id=node_id,
                                        retryable=False,
                                    )

                                redirect_location = response.headers.get("location")
                                if not redirect_location:
                                    raise NodeExecutionError(
                                        f"Download received redirect status {response.status_code} without Location header.",
                                        code="INVALID_REDIRECT",
                                        node_id=node_id,
                                        retryable=False,
                                    )

                                # Resolve relative redirect against current URL
                                new_url = urljoin(current_url, redirect_location)
                                logger.info(
                                    "Validating redirect hop %d to %s",
                                    redirect_count,
                                    redact_sensitive_url(new_url),
                                )

                                # CRITICAL: Validate the redirect destination against SSRF rules!
                                await validate_download_url(
                                    new_url,
                                    node_id=node_id,
                                    allow_loopback_in_dev=allow_loopback_in_dev,
                                )

                                current_url = new_url
                                continue

                            # Validate HTTP status
                            if response.status_code >= 400:
                                if response.status_code in (502, 503, 504) and attempt < max_attempts - 1:
                                    # Transient gateway error, wait and retry
                                    await asyncio.sleep(1.0)
                                    break
                                raise NodeExecutionError(
                                    f"Download failed with HTTP status {response.status_code} from {redact_sensitive_url(current_url)}.",
                                    code=f"HTTP_{response.status_code}",
                                    node_id=node_id,
                                    retryable=(response.status_code in (502, 503, 504)),
                                )

                            final_response_headers = dict(response.headers)

                            # Check Content-Length upfront if provided
                            content_length_str = response.headers.get("content-length")
                            if content_length_str and content_length_str.isdigit():
                                expected_len = int(content_length_str)
                                if expected_len > max_download_bytes:
                                    raise NodeExecutionError(
                                        f"Download rejected: Content-Length ({expected_len} bytes) exceeds maximum allowed size ({max_download_bytes} bytes).",
                                        code="FILE_TOO_LARGE",
                                        node_id=node_id,
                                        retryable=False,
                                    )

                            # Stream and enforce running byte limit
                            async for chunk in response.aiter_bytes(chunk_size=65536):
                                total_downloaded += len(chunk)
                                if total_downloaded > max_download_bytes:
                                    raise NodeExecutionError(
                                        f"Download aborted: Stream exceeded maximum allowed size of {max_download_bytes} bytes.",
                                        code="FILE_TOO_LARGE",
                                        node_id=node_id,
                                        retryable=False,
                                    )
                                chunks.append(chunk)

                            # Download completed successfully
                            break
                # If we successfully completed the streaming loop, break out of retry loop
                if chunks:
                    break
            except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.TimeoutException) as exc:
                if attempt < max_attempts - 1:
                    await asyncio.sleep(1.0)
                    continue
                raise NodeExecutionError(
                    f"Download timed out after {timeout_seconds}s connecting to {redact_sensitive_url(current_url)}.",
                    code="TIMEOUT",
                    node_id=node_id,
                    retryable=True,
                ) from exc
            except NodeExecutionError:
                raise
            except Exception as exc:
                if attempt < max_attempts - 1 and isinstance(exc, (httpx.ConnectError, httpx.NetworkError)):
                    await asyncio.sleep(1.0)
                    continue
                raise NodeExecutionError(
                    f"Download failed: {exc}",
                    code="DOWNLOAD_FAILED",
                    node_id=node_id,
                    retryable=False,
                ) from exc

        content = b"".join(chunks)

        # Extract filename hint from Content-Disposition or URL path
        cd = final_response_headers.get("content-disposition", "")
        if "filename=" in cd:
            match = re.search(r'filename\*?=(?:UTF-8\'\')?["\']?([^"\';\r\n]+)', cd, re.IGNORECASE)
            if match:
                filename_hint = match.group(1).strip()

        if not filename_hint:
            parsed_path = urlparse(current_url).path
            base_name = os.path.basename(parsed_path)
            if base_name and "." in base_name:
                filename_hint = base_name

        meta = {
            "final_url": redact_sensitive_url(current_url),
            "redirect_count": redirect_count,
            "total_bytes": len(content),
            "content_type": final_response_headers.get("content-type", "application/octet-stream"),
            "filename_hint": filename_hint or "downloaded_file",
        }

        return content, filename_hint or "downloaded_file", meta
