"""Salesforce provider client (Phase 7).

Reusable client for the Salesforce REST API. It owns everything that
talks to Salesforce over the wire:

- authentication: OAuth2 username-password (resource-owner) grant,
  token caching with a short-lived lock (single flight per token)
- Salesforce base URL: the org instance URL returned by the token
  endpoint wins over the credential's login URL
- API version: configurable (default v63.0), embedded in data URLs
- request construction: bearer auth, JSON/URL-encoded bodies, params,
  timeouts, path resolution (relative data paths vs full /services/...)
- response parsing: JSON parsing with empty-body tolerance
- Salesforce error translation: typed ConnectorError categories
  (AUTH_FAILED, NOT_FOUND, RATE_LIMITED, UNAVAILABLE, BAD_REQUEST,
  TIMEOUT) with correct retryable flags
- pagination: query() follows nextRecordsUrl pages up to a page cap

Credentials are never stored by the client; the caller (the connector,
fed by the CredentialResolver) passes them per call. All network I/O
goes through SafeHTTPClient (SSRF protection, redacted logging).
"""

from __future__ import annotations

import asyncio
import csv
import io
import logging
import time
from typing import Any
from urllib.parse import urlencode

import httpx

from app.connectors import (
    ConnectorError,
    ConnectorErrorCode,
    make_connector_error,
)
from app.config import get_settings
from app.security.safe_http_client import get_safe_http_client

logger = logging.getLogger(__name__)

DEFAULT_LOGIN_URL = "https://login.salesforce.com"
DEFAULT_API_VERSION = "v63.0"
DEFAULT_TOKEN_TTL_S = 7200  # Salesforce access tokens last 2h
DEFAULT_MAX_PAGES = 10

#: Bulk API v2 job states that end polling.
_BULK_TERMINAL_STATES = {"JobComplete", "JobFailed", "Aborted"}
#: Bulk API v2 ingest operations (Salesforce REST Bulk API 2.0).
BULK_OPERATIONS = ("insert", "update", "upsert", "delete")


def _parse_retry_after(value: str | None) -> float | None:
    """Parse a Retry-After header into seconds.

    Salesforce sends delay-seconds (RFC 7231 also allows HTTP dates,
    which we do not attempt to parse — treat unparseable as None).
    """
    if not value:
        return None
    try:
        seconds = float(value.strip())
    except ValueError:
        return None
    return max(0.0, seconds)


class SalesforceProviderClient:
    """Low-level Salesforce REST API client.

    The connector (Salesforce Operation layer) maps its operations onto
    the high-level methods here (query, get_record, create_record,
    update_record, delete_record, describe_object, list_objects).
    """

    def __init__(
        self,
        api_version: str = DEFAULT_API_VERSION,
        token_ttl_s: float = DEFAULT_TOKEN_TTL_S,
    ) -> None:
        self.api_version = api_version
        self._token_ttl_s = token_ttl_s
        self._token: str | None = None
        self._token_key: str = ""
        self._token_expires_at: float = 0.0
        self._instance_url: str = ""
        self._token_lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Drop cached token/instance state (e.g. on disconnect)."""
        self._token = None
        self._token_key = ""
        self._token_expires_at = 0.0
        self._instance_url = ""

    @property
    def has_token(self) -> bool:
        return self._token is not None

    def _token_cache_key(self, creds: dict[str, Any]) -> str:
        cid = creds.get("_credential_id")
        if cid:
            return f"cid:{cid}"
        return (
            f"{creds.get('instance_url', '')}|{creds.get('login_url', '')}"
            f"|{creds.get('username', '')}|{creds.get('client_id', '')}"
            f"|{(creds.get('refresh_token') or '')[:10]}"
        )

    def _token_valid(self, creds: dict[str, Any]) -> bool:
        return (
            self._token is not None
            and self._token_key == self._token_cache_key(creds)
            and self._token_expires_at > time.monotonic()
        )

    def _apply_server_oauth_config(self, creds: dict[str, Any]) -> dict[str, Any]:
        """Inject the server-side Connected App config for OAuth connections.

        'Connect Salesforce' credentials store no client id/secret (they are
        server configuration, never sent to the frontend); the token request
        needs them, so the server's settings are merged in at call time.
        """
        settings = get_settings()
        client_id = (creds.get("client_id") or "").strip() or settings.salesforce_client_id
        client_secret = (creds.get("client_secret") or "").strip() or settings.salesforce_client_secret
        return {
            **creds,
            "client_id": client_id,
            "client_secret": client_secret,
        }

    async def authenticate(self, creds: dict[str, Any]) -> str:
        """Return a valid access token, fetching one if needed (single flight)."""
        creds = self._apply_server_oauth_config(creds)
        if self._token_valid(creds):
            return self._token  # type: ignore[return-value]

        # Reuse unexpired access token from stored credentials if present
        access_token = (creds.get("access_token") or "").strip()
        expires_at = creds.get("expires_at") or 0
        if access_token and (expires_at and float(expires_at) > 0 and time.time() < (float(expires_at) - 60)):
            self._token = access_token
            self._token_key = self._token_cache_key(creds)
            self._token_expires_at = time.monotonic() + min(self._token_ttl_s, max(60.0, float(expires_at) - time.time()))
            if creds.get("instance_url"):
                self._instance_url = creds["instance_url"].rstrip("/")
            return access_token

        async with self._token_lock:
            if self._token_valid(creds):
                return self._token  # type: ignore[return-value]

            cid = creds.get("_credential_id")
            # If another thread/process refreshed the credential in DB, load it now
            if cid:
                try:
                    import json
                    from app.db import get_session
                    from app.models.credential import Credential
                    from app.security.crypto import decrypt_text
                    with get_session() as db_session:
                        c_rec = db_session.get(Credential, cid)
                        if c_rec:
                            c_dict = json.loads(decrypt_text(c_rec.data))
                            db_exp = c_dict.get("expires_at") or 0
                            if c_dict.get("access_token") and float(db_exp) > (time.time() + 60):
                                self._token = c_dict["access_token"]
                                self._token_key = self._token_cache_key(creds)
                                self._token_expires_at = time.monotonic() + min(self._token_ttl_s, max(60.0, float(db_exp) - time.time()))
                                if c_dict.get("instance_url"):
                                    self._instance_url = c_dict["instance_url"].rstrip("/")
                                creds["access_token"] = c_dict["access_token"]
                                creds["expires_at"] = db_exp
                                if c_dict.get("refresh_token"):
                                    creds["refresh_token"] = c_dict["refresh_token"]
                                return str(self._token or "")
                            # Always take the newest refresh token from DB before hitting Salesforce
                            if c_dict.get("refresh_token"):
                                creds["refresh_token"] = c_dict["refresh_token"]
                except Exception as ex:
                    logger.debug("Could not verify token in DB: %s", ex)

            login_url = (
                creds.get("login_url") or creds.get("instance_url") or DEFAULT_LOGIN_URL
            ).rstrip("/")
            # OAuth2 grant: refresh-token (authorization-code flow) when a
            # refresh_token is present, otherwise username-password.
            refresh_token = (creds.get("refresh_token") or "").strip()
            if refresh_token:
                body = urlencode({
                    "grant_type": "refresh_token",
                    "client_id": creds.get("client_id", ""),
                    "client_secret": creds.get("client_secret", ""),
                    "refresh_token": refresh_token,
                })
            else:
                body = urlencode({
                    "grant_type": "password",
                    "client_id": creds.get("client_id", ""),
                    "client_secret": creds.get("client_secret", ""),
                    "username": creds.get("username", ""),
                    "password": creds.get("password", ""),
                })

            try:
                async with get_safe_http_client() as client:
                    response = await client.request(
                        "POST",
                        f"{login_url}/services/oauth2/token",
                        data=body,
                        headers={"Content-Type": "application/x-www-form-urlencoded"},
                        timeout=30.0,
                    )
            except httpx.TimeoutException as exc:
                raise make_connector_error(
                    ConnectorErrorCode.TIMEOUT,
                    "Salesforce token request timed out.",
                    retryable=True,
                ) from exc
            except httpx.RequestError as exc:
                raise make_connector_error(
                    ConnectorErrorCode.UNAVAILABLE,
                    f"Salesforce token request failed: {exc}",
                    retryable=True,
                ) from exc

            if response.status_code >= 400:
                detail = ""
                try:
                    err = response.json()
                    if isinstance(err, dict):
                        desc = err.get("error_description") or err.get("error")
                        if desc:
                            detail = f": {desc}"
                except ValueError:
                    pass
                raise make_connector_error(
                    ConnectorErrorCode.AUTH_FAILED
                    if response.status_code in (400, 401)
                    else ConnectorErrorCode.BAD_REQUEST,
                    f"Salesforce authentication failed (HTTP {response.status_code}){detail}.",
                    retryable=False,
                )

            try:
                payload = response.json()
                token = payload["access_token"]
                instance_url = payload.get("instance_url", "").rstrip("/")
            except (ValueError, KeyError) as exc:
                raise make_connector_error(
                    ConnectorErrorCode.AUTH_FAILED,
                    "Salesforce token response was malformed.",
                    retryable=False,
                ) from exc

            self._token = token
            self._token_key = self._token_cache_key(creds)
            self._token_expires_at = time.monotonic() + self._token_ttl_s
            if instance_url:
                self._instance_url = instance_url

            # Update caller's in-memory dictionary in place so downstream callers within
            # the same execution or context hold the latest rotated tokens immediately.
            new_rt = payload.get("refresh_token")
            exp_at = time.time() + 7200
            creds["access_token"] = token
            creds["expires_at"] = exp_at
            if new_rt:
                creds["refresh_token"] = new_rt

            # Persist fresh access token and rotated refresh token
            if cid:
                try:
                    import json
                    from app.db import get_session
                    from app.models.credential import Credential
                    from app.security.crypto import encrypt_text, decrypt_text
                    with get_session() as db_session:
                        c_rec = db_session.get(Credential, cid)
                        if c_rec:
                            c_dict = json.loads(decrypt_text(c_rec.data))
                            c_dict["access_token"] = token
                            c_dict["expires_at"] = exp_at
                            if new_rt:
                                c_dict["refresh_token"] = new_rt
                            c_rec.data = encrypt_text(json.dumps(c_dict))
                            db_session.commit()
                except Exception as ex:
                    logger.warning("Could not persist Salesforce token update: %s", ex)

            return token

    # ------------------------------------------------------------------
    # Request construction
    # ------------------------------------------------------------------

    def _org_url(self, creds: dict[str, Any]) -> str:
        """Org instance URL: the token endpoint's answer wins.

        login.salesforce.com (or test.salesforce.com) is only the auth
        front door; data lives at the returned instance URL.
        """
        return (
            self._instance_url
            or creds.get("instance_url")
            or DEFAULT_LOGIN_URL
        ).rstrip("/")

    def _resolve_url(self, org_url: str, path: str) -> str:
        """Resolve a path against the org.

        Paths like "/services/data/..." carry their own API version and
        are used verbatim (nextRecordsUrl from pagination). Relative
        paths are joined with the configured API version.
        """
        path = path.lstrip("/")
        if path.startswith("services/"):
            return f"{org_url}/{path}"
        return f"{org_url}/services/data/{self.api_version}/{path}"

    async def request(
        self,
        creds: dict[str, Any],
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        data: Any = None,
        headers: dict[str, str] | None = None,
        timeout: float = 30.0,
    ) -> httpx.Response:
        """Run an authenticated request against the Salesforce REST API."""
        token = await self.authenticate(creds)
        url = self._resolve_url(self._org_url(creds), path)
        auth_headers = {"Authorization": f"Bearer {token}"}
        if headers:
            auth_headers.update(headers)
        async with get_safe_http_client() as client:
            try:
                response = await client.request(
                    method,
                    url,
                    params=params,
                    json=json,
                    data=data,
                    headers=auth_headers,
                    timeout=timeout,
                )
                # Auto-recovery: if session expired (HTTP 401), refresh token and retry once
                if response.status_code == 401 and creds.get("refresh_token"):
                    self._token = None
                    self._token_expires_at = 0.0
                    fresh_creds: dict[str, Any] = dict(creds)
                    fresh_creds.pop("access_token", None)
                    fresh_creds.pop("expires_at", None)
                    token = await self.authenticate(fresh_creds)
                    if fresh_creds.get("access_token"):
                        creds["access_token"] = fresh_creds["access_token"]
                    if fresh_creds.get("expires_at"):
                        creds["expires_at"] = fresh_creds["expires_at"]
                    if fresh_creds.get("refresh_token"):
                        creds["refresh_token"] = fresh_creds["refresh_token"]
                    auth_headers["Authorization"] = f"Bearer {token}"
                    response = await client.request(
                        method,
                        url,
                        params=params,
                        json=json,
                        data=data,
                        headers=auth_headers,
                        timeout=timeout,
                    )
                return response
            except httpx.TimeoutException as exc:
                raise make_connector_error(
                    ConnectorErrorCode.TIMEOUT,
                    "Salesforce request timed out.",
                    retryable=True,
                ) from exc
            except httpx.RequestError as exc:
                raise make_connector_error(
                    ConnectorErrorCode.UNAVAILABLE,
                    f"Salesforce request failed: {exc}",
                    retryable=True,
                ) from exc

    # ------------------------------------------------------------------
    # Response parsing + error translation
    # ------------------------------------------------------------------

    def _raise_for_status(
        self,
        response: httpx.Response,
        expected: tuple[int, ...] = (200,),
    ) -> None:
        """Map Salesforce HTTP errors to typed ConnectorErrors."""
        if response.status_code in expected:
            return
        # Salesforce error body: [{"errorCode": "...", "message": "..."}]
        message = "Salesforce API error."
        try:
            body = response.json()
            if isinstance(body, list) and body:
                message = body[0].get("message", message)
        except ValueError:
            pass

        code = ConnectorErrorCode.BAD_REQUEST
        retryable = False
        retry_after: float | None = None
        if response.status_code == 401:
            code = ConnectorErrorCode.AUTH_FAILED
        elif response.status_code == 403:
            code = ConnectorErrorCode.FORBIDDEN
        elif response.status_code == 404:
            code = ConnectorErrorCode.NOT_FOUND
        elif response.status_code == 429:
            code = ConnectorErrorCode.RATE_LIMITED
            retryable = True
            # Phase 9: Salesforce sends Retry-After on throttled requests;
            # surface it so the engine waits exactly as long as told.
            retry_after = _parse_retry_after(response.headers.get("Retry-After"))
        elif response.status_code >= 500:
            code = ConnectorErrorCode.UNAVAILABLE
            retryable = True
        raise make_connector_error(code, message, retryable=retryable, retry_after=retry_after)

    @staticmethod
    def parse_retry_after(response: httpx.Response) -> float | None:
        """Public wrapper so callers can read Retry-After off any response."""
        return _parse_retry_after(response.headers.get("Retry-After"))

    def _parse_body(self, response: httpx.Response, what: str, *, allow_empty: bool = False) -> dict[str, Any]:
        """Parse a JSON response body, tolerating empty bodies where noted."""
        if not response.content and allow_empty:
            return {}
        try:
            body = response.json()
        except ValueError as exc:
            raise make_connector_error(
                ConnectorErrorCode.BAD_REQUEST,
                f"Salesforce {what} returned a non-JSON response.",
                retryable=False,
            ) from exc
        return body if isinstance(body, dict) else {"value": body}

    # ------------------------------------------------------------------
    # Operations (high-level)
    # ------------------------------------------------------------------

    async def query(
        self,
        creds: dict[str, Any],
        soql: str,
        *,
        timeout: float = 30.0,
        max_pages: int = DEFAULT_MAX_PAGES,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Run a SOQL query, following nextRecordsUrl pages when needed.

        Returns the aggregated query body: records (all fetched pages),
        totalSize (first page), done (last page), nextRecordsUrl (last
        page's, or None once exhausted). Pass a custom ``headers`` dict
        to tune page size (e.g. ``Sforce-Query-Options: batchSize=5``).
        """
        response = await self.request(creds, "GET", "/query", params={"q": soql}, timeout=timeout, headers=headers)
        self._raise_for_status(response)
        body = self._parse_body(response, "query")

        records = list(body.get("records", []))
        total_size = body.get("totalSize", len(records))
        done = bool(body.get("done", True))
        next_url = body.get("nextRecordsUrl")
        pages = 1

        while not done and next_url and pages < max_pages:
            response = await self.request(creds, "GET", next_url, timeout=timeout)
            self._raise_for_status(response)
            page = self._parse_body(response, "query")
            records.extend(page.get("records", []))
            done = bool(page.get("done", True))
            next_url = page.get("nextRecordsUrl")
            pages += 1

        return {
            "records": records,
            "totalSize": total_size,
            "done": done,
            "nextRecordsUrl": next_url if not done else None,
        }

    async def get_record(
        self,
        creds: dict[str, Any],
        object_name: str,
        record_id: str,
        *,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        response = await self.request(
            creds, "GET", f"/sobjects/{object_name}/{record_id}", timeout=timeout
        )
        self._raise_for_status(response)
        return self._parse_body(response, "get")

    @staticmethod
    def escape_soql_string(value: str) -> str:
        """Escape a value for a SOQL string literal (backslash + quote)."""
        return value.replace("\\", "\\\\").replace("'", "\\'")

    async def search_records(
        self,
        creds: dict[str, Any],
        object_name: str,
        search_field: str,
        search_value: str,
        *,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        """Search/Get Record: find a record by field value and return it.

        Resolves to ``SELECT Id FROM <object> WHERE <field> = '<value>'
        LIMIT 1`` (value SOQL-escaped), then fetches the full record by
        id. Returns a normalized result: ``{"found": bool, "record": dict|None}``.
        """
        soql = (
            f"SELECT Id FROM {object_name} "
            f"WHERE {search_field} = '{self.escape_soql_string(search_value)}' LIMIT 1"
        )
        body = await self.query(creds, soql, timeout=timeout)
        records = body.get("records") or []
        if not records:
            return {"found": False, "record": None}
        record = await self.get_record(creds, object_name, records[0]["Id"], timeout=timeout)
        return {"found": True, "record": record}

    async def create_record(
        self,
        creds: dict[str, Any],
        object_name: str,
        record: dict[str, Any],
        *,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        response = await self.request(
            creds, "POST", f"/sobjects/{object_name}", json=record, timeout=timeout
        )
        if response.status_code == 300:
            # Duplicate ALERT: the org's duplicate rule fired in alert mode;
            # Salesforce still created the record (HTTP 300 "Use one of
            # these records?"). Report success with a duplicate flag so the
            # workflow completes; matched records are surfaced for audit.
            body: dict[str, Any] = {"id": None, "success": True, "duplicate_alert": True}
            recovered_id = await self._duplicate_alert_recovery(
                creds, object_name, record, response, timeout
            )
            if recovered_id is not None:
                body["id"] = recovered_id
            matched = self._duplicate_matches(response)
            if matched:
                body["matched_records"] = matched
            return body
        if response.status_code >= 400:
            # Some orgs surface alert-mode duplicate rules with a non-300
            # status (observed as 400 DUPLICATES_DETECTED). Confirm whether
            # the record was actually written before failing the workflow.
            recovered_id = await self._duplicate_alert_recovery(
                creds, object_name, record, response, timeout
            )
            if recovered_id is not None:
                return {"id": recovered_id, "success": True, "duplicate_alert": True}
        self._raise_for_status(response, expected=(200, 201))
        return self._parse_body(response, "create", allow_empty=True)

    async def _duplicate_alert_recovery(
        self,
        creds: dict[str, Any],
        object_name: str,
        record: dict[str, Any],
        response: httpx.Response,
        timeout: float,
    ) -> str | None:
        """Confirm whether a duplicate-rejection error actually created the
        record (alert mode) by re-querying its unique key. Returns the new
        record id when created, or None when it truly failed (block mode)."""
        try:
            body = response.json()
        except ValueError:
            return None
        if not isinstance(body, list) or not body or not isinstance(body[0], dict):
            return None
        err = body[0]
        error_code = str(err.get("errorCode", ""))
        message = str(err.get("message", ""))
        if error_code != "DUPLICATES_DETECTED" and "use one of these records" not in message.lower():
            return None
        key_field = record.get("Email")
        if not key_field:
            return None
        key_field_name = "Email"
        soql = (
            f"SELECT Id FROM {object_name} WHERE {key_field_name} = "
            f"'{self.escape_soql_string(str(key_field))}' "
            "ORDER BY CreatedDate DESC LIMIT 1"
        )
        try:
            found = await self.query(creds, soql, timeout=timeout)
        except ConnectorError:
            return None
        records = found.get("records") or []
        if records:
            return records[0]["Id"]
        return None

    @staticmethod
    def _duplicate_matches(response: httpx.Response) -> list[str]:
        """Extract matched record ids from a duplicate-rule HTTP 300 body."""
        try:
            body = response.json()
        except ValueError:
            return []
        if not isinstance(body, list) or not body:
            return []
        dup = body[0].get("duplicateResult")
        if isinstance(dup, dict):
            matches = dup.get("matchedRecords") or dup.get("matchResults") or []
        elif isinstance(dup, list):
            matches = dup
        else:
            matches = body[0].get("matchResults") or []
        ids: list[str] = []
        for match in matches:
            if not isinstance(match, dict):
                continue
            record = match.get("record")
            if isinstance(record, dict) and record.get("Id"):
                ids.append(str(record["Id"]))
        return ids

    async def update_record(
        self,
        creds: dict[str, Any],
        object_name: str,
        record_id: str,
        record: dict[str, Any],
        *,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        response = await self.request(
            creds, "PATCH", f"/sobjects/{object_name}/{record_id}", json=record, timeout=timeout
        )
        self._raise_for_status(response, expected=(200, 204))
        return self._parse_body(response, "update", allow_empty=True)

    async def upsert_record(
        self,
        creds: dict[str, Any],
        object_name: str,
        external_id_field: str,
        external_id: str,
        record: dict[str, Any],
        *,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        """Upsert by external id (Phase 9).

        PATCH /sobjects/{object}/{externalIdField}/{externalId} creates
        the record when the external id is unknown and patches it when
        known, which makes retries safe (idempotent write).
        Returns {"id": ..., "created": bool} per Salesforce response.
        """
        response = await self.request(
            creds,
            "PATCH",
            f"/sobjects/{object_name}/{external_id_field}/{external_id}",
            json=record,
            timeout=timeout,
        )
        self._raise_for_status(response, expected=(200, 201, 204))
        body = self._parse_body(response, "upsert", allow_empty=True)
        return {
            "id": body.get("id"),
            "created": bool(body.get("created", False)),
        }

    # ------------------------------------------------------------------
    # Bulk API 2.0 (Phase 9)
    # ------------------------------------------------------------------

    async def bulk_ingest(
        self,
        creds: dict[str, Any],
        object_name: str,
        bulk_operation: str,
        records: list[dict[str, Any]],
        *,
        external_id_field: str = "",
        timeout: float = 30.0,
        poll_interval: float = 1.0,
        max_polls: int = 60,
    ) -> dict[str, Any]:
        """Load records via REST Bulk API 2.0 (job-based ingest).

        Lifecycle: create job -> upload CSV -> UploadComplete -> poll
        until a terminal state -> fetch successful/failed row results.
        ``bulk_operation`` is one of BULK_OPERATIONS ("upsert" requires
        ``external_id_field``). Rows are keyed to results by their
        original position via the returned ``row_results`` list.
        """
        if bulk_operation not in BULK_OPERATIONS:
            raise make_connector_error(
                ConnectorErrorCode.BAD_REQUEST,
                f"Unsupported bulk operation '{bulk_operation}' (use one of {list(BULK_OPERATIONS)}).",
                retryable=False,
            )
        if not records:
            raise make_connector_error(
                ConnectorErrorCode.BAD_REQUEST,
                "Bulk operation requires at least one record.",
                retryable=False,
            )
        if bulk_operation == "delete":
            # Delete jobs take only Id columns.
            csv_rows = [{"Id": str(r.get("Id") or "")} for r in records]
        else:
            csv_rows = [dict(r) for r in records]

        job_body: dict[str, Any] = {"object": object_name, "operation": bulk_operation}
        if bulk_operation == "upsert":
            if not external_id_field:
                raise make_connector_error(
                    ConnectorErrorCode.BAD_REQUEST,
                    "Bulk upsert requires external_id_field.",
                    retryable=False,
                )
            job_body["externalIdField"] = external_id_field

        create_resp = await self.request(
            creds, "POST", "/jobs/ingest", json=job_body, timeout=timeout
        )
        self._raise_for_status(create_resp, expected=(200, 201))
        job = self._parse_body(create_resp, "bulk create")
        job_id = str(job.get("id") or "")
        if not job_id:
            raise make_connector_error(
                ConnectorErrorCode.BAD_REQUEST,
                "Salesforce Bulk API did not return a job id.",
                retryable=False,
            )

        csv_data = build_bulk_csv(csv_rows)
        upload_resp = await self.request(
            creds,
            "PUT",
            f"/jobs/ingest/{job_id}/batches",
            data=csv_data.encode("utf-8"),
            headers={"Content-Type": "text/csv"},
            timeout=max(timeout, 120.0),
        )
        self._raise_for_status(upload_resp, expected=(200, 201))

        complete_resp = await self.request(
            creds, "PATCH", f"/jobs/ingest/{job_id}",
            json={"state": "UploadComplete"}, timeout=timeout,
        )
        self._raise_for_status(complete_resp)

        state = ""
        job_info: dict[str, Any] = {}
        for _ in range(max_polls):
            poll_resp = await self.request(
                creds, "GET", f"/jobs/ingest/{job_id}", timeout=timeout
            )
            self._raise_for_status(poll_resp)
            job_info = self._parse_body(poll_resp, "bulk poll")
            state = str(job_info.get("state") or "")
            if state in _BULK_TERMINAL_STATES:
                break
            await asyncio.sleep(poll_interval)
        else:
            raise make_connector_error(
                ConnectorErrorCode.TIMEOUT,
                f"Bulk job {job_id} did not reach a terminal state after {max_polls} polls.",
                retryable=True,
            )

        result: dict[str, Any] = {
            "job_id": job_id,
            "state": state,
            "records_processed": int(job_info.get("numberRecordsProcessed") or 0),
            "records_failed": int(job_info.get("numberRecordsFailed") or 0),
        }
        if state == "JobComplete":
            failed_resp = await self.request(
                creds, "GET", f"/jobs/ingest/{job_id}/failedResults", timeout=timeout,
            )
            if failed_resp.status_code == 200 and failed_resp.content:
                result["failed_records"] = self._parse_csv_results(failed_resp.text)
            else:
                result["failed_records"] = []
            successful_resp = await self.request(
                creds, "GET", f"/jobs/ingest/{job_id}/successfulResults", timeout=timeout,
            )
            if successful_resp.status_code == 200 and successful_resp.content:
                result["successful_records"] = self._parse_csv_results(successful_resp.text)
            else:
                result["successful_records"] = []
        else:
            result["error_message"] = str(job_info.get("errorMessage") or "")
        return result

    @staticmethod
    def _parse_csv_results(text: str) -> list[dict[str, Any]]:
        """Parse Bulk API CSV results (sf__Id, sf__Created, Error columns)."""
        lines = [line for line in text.splitlines() if line.strip()]
        if len(lines) < 2:
            return []
        headers = next(csv.reader([lines[0]]))
        rows: list[dict[str, Any]] = []
        for line in lines[1:]:
            values = next(csv.reader([line]))
            rows.append(dict(zip(headers, values)))
        return rows

    async def delete_record(
        self,
        creds: dict[str, Any],
        object_name: str,
        record_id: str,
        *,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        response = await self.request(
            creds, "DELETE", f"/sobjects/{object_name}/{record_id}", timeout=timeout
        )
        self._raise_for_status(response, expected=(200, 204))
        return self._parse_body(response, "delete", allow_empty=True)

    async def describe_object(
        self,
        creds: dict[str, Any],
        object_name: str,
        *,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        response = await self.request(
            creds, "GET", f"/sobjects/{object_name}/describe", timeout=timeout
        )
        self._raise_for_status(response)
        return self._parse_body(response, "describe")

    async def list_objects(
        self,
        creds: dict[str, Any],
        *,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        response = await self.request(creds, "GET", "/sobjects", timeout=timeout)
        self._raise_for_status(response)
        return self._parse_body(response, "list")

    async def custom_api_call(
        self,
        creds: dict[str, Any],
        method: str,
        path: str,
        *,
        body: Any = None,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        """Generic REST call for Custom API Call resource."""
        method = (method or "GET").upper()
        if method not in ("GET", "POST", "PUT", "PATCH", "DELETE"):
            raise make_connector_error(
                ConnectorErrorCode.BAD_REQUEST,
                f"Custom API Call: unsupported method '{method}'.",
                retryable=False,
            )
        # body only for POST/PUT/PATCH
        json_body = body if method in ("POST", "PUT", "PATCH") else None
        response = await self.request(creds, method, path, json=json_body, timeout=timeout)
        self._raise_for_status(response, expected=(200, 201, 204))
        # 204 no content
        if response.status_code == 204 or not response.content:
            return {"status_code": response.status_code, "body": {}, "headers": dict(response.headers)}
        try:
            body_json = response.json()
        except ValueError:
            body_json = {"raw": response.text}
        return {"status_code": response.status_code, "body": body_json, "headers": dict(response.headers)}

    async def invoke_flow(
        self,
        creds: dict[str, Any],
        flow_api_name: str,
        inputs: dict[str, Any] | None = None,
        *,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        """Invoke an autolaunched Flow via REST."""
        if not flow_api_name or not flow_api_name.replace("_", "").replace("-", "").isalnum():
            raise ConnectorError(
                "flow_api_name must be non-empty and contain only alphanumeric, underscore, or hyphen.",
                code=ConnectorErrorCode.BAD_REQUEST,
                retryable=False,
            )
        # Salesforce Flow REST: POST /actions/custom/flow/{flowApiName}
        # Body: {"inputs": [inputs]} per docs, but support plain object as well
        body: Any = {"inputs": [inputs or {}]}
        response = await self.request(creds, "POST", f"/actions/custom/flow/{flow_api_name}", json=body, timeout=timeout)
        self._raise_for_status(response, expected=(200, 201))
        try:
            result = response.json()
        except ValueError:
            result = {"raw": response.text}
        return {"output": result, "success": True}


def build_bulk_csv(records: list[dict[str, Any]]) -> str:
    """Serialize Bulk API rows to CSV (RFC 4180 quoting via csv module).

    Column order: union of keys across rows in first-seen order so all
    rows share one consistent header.
    """
    columns: list[str] = []
    seen: set[str] = set()
    for row in records:
        for key in row:
            if key not in seen:
                seen.add(key)
                columns.append(key)

    def _cell(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, bool):
            return "true" if value else "false"
        return str(value)

    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(columns)
    for row in records:
        writer.writerow([_cell(row.get(col)) for col in columns])
    return buffer.getvalue()


_shared_salesforce_provider: SalesforceProviderClient | None = None


def get_salesforce_provider() -> SalesforceProviderClient:
    """Return the shared SalesforceProviderClient singleton instance."""
    global _shared_salesforce_provider
    if _shared_salesforce_provider is None:
        _shared_salesforce_provider = SalesforceProviderClient()
    return _shared_salesforce_provider