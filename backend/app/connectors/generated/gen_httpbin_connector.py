"""Generated connector — do not hand-edit, regenerate from the OpenAPI spec.

Source API: httpbin.org
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.connectors import (
    ConnectorCategory,
    ConnectorErrorCode,
    ConnectorSDK,
    ConnectorStatus,
    make_connector_error,
)

from .gen_httpbin_provider import GeneratedProvider


class GeneratedConnectorParams(BaseModel):
    operation: str = Field(default="")
    timeout_seconds: float = Field(default=30.0, ge=1, le=300)

    model_config = {'extra': 'allow'}


OPERATIONS = {'get_absolute_redirect_n': {'method': 'GET', 'path': '/absolute-redirect/{n}', 'path_params': ['n'], 'query_params': [], 'has_body': False}, 'delete_anything': {'method': 'DELETE', 'path': '/anything', 'path_params': [], 'query_params': [], 'has_body': False}, 'get_anything': {'method': 'GET', 'path': '/anything', 'path_params': [], 'query_params': [], 'has_body': False}, 'patch_anything': {'method': 'PATCH', 'path': '/anything', 'path_params': [], 'query_params': [], 'has_body': False}, 'post_anything': {'method': 'POST', 'path': '/anything', 'path_params': [], 'query_params': [], 'has_body': False}, 'put_anything': {'method': 'PUT', 'path': '/anything', 'path_params': [], 'query_params': [], 'has_body': False}, 'delete_anything_anything': {'method': 'DELETE', 'path': '/anything/{anything}', 'path_params': ['anything'], 'query_params': [], 'has_body': False}, 'get_anything_anything': {'method': 'GET', 'path': '/anything/{anything}', 'path_params': ['anything'], 'query_params': [], 'has_body': False}, 'patch_anything_anything': {'method': 'PATCH', 'path': '/anything/{anything}', 'path_params': ['anything'], 'query_params': [], 'has_body': False}, 'post_anything_anything': {'method': 'POST', 'path': '/anything/{anything}', 'path_params': ['anything'], 'query_params': [], 'has_body': False}, 'put_anything_anything': {'method': 'PUT', 'path': '/anything/{anything}', 'path_params': ['anything'], 'query_params': [], 'has_body': False}, 'get_base64_value': {'method': 'GET', 'path': '/base64/{value}', 'path_params': ['value'], 'query_params': [], 'has_body': False}, 'get_basic_auth_user_passwd': {'method': 'GET', 'path': '/basic-auth/{user}/{passwd}', 'path_params': ['user', 'passwd'], 'query_params': [], 'has_body': False}, 'get_bearer': {'method': 'GET', 'path': '/bearer', 'path_params': [], 'query_params': [], 'has_body': False}, 'get_brotli': {'method': 'GET', 'path': '/brotli', 'path_params': [], 'query_params': [], 'has_body': False}, 'get_bytes_n': {'method': 'GET', 'path': '/bytes/{n}', 'path_params': ['n'], 'query_params': [], 'has_body': False}, 'get_cache': {'method': 'GET', 'path': '/cache', 'path_params': [], 'query_params': [], 'has_body': False}, 'get_cache_value': {'method': 'GET', 'path': '/cache/{value}', 'path_params': ['value'], 'query_params': [], 'has_body': False}, 'get_cookies': {'method': 'GET', 'path': '/cookies', 'path_params': [], 'query_params': [], 'has_body': False}, 'get_cookies_delete': {'method': 'GET', 'path': '/cookies/delete', 'path_params': [], 'query_params': ['freeform'], 'has_body': False}, 'get_cookies_set': {'method': 'GET', 'path': '/cookies/set', 'path_params': [], 'query_params': ['freeform'], 'has_body': False}, 'get_cookies_set_name_value': {'method': 'GET', 'path': '/cookies/set/{name}/{value}', 'path_params': ['name', 'value'], 'query_params': [], 'has_body': False}, 'get_deflate': {'method': 'GET', 'path': '/deflate', 'path_params': [], 'query_params': [], 'has_body': False}, 'delete_delay_delay': {'method': 'DELETE', 'path': '/delay/{delay}', 'path_params': ['delay'], 'query_params': [], 'has_body': False}, 'get_delay_delay': {'method': 'GET', 'path': '/delay/{delay}', 'path_params': ['delay'], 'query_params': [], 'has_body': False}, 'patch_delay_delay': {'method': 'PATCH', 'path': '/delay/{delay}', 'path_params': ['delay'], 'query_params': [], 'has_body': False}, 'post_delay_delay': {'method': 'POST', 'path': '/delay/{delay}', 'path_params': ['delay'], 'query_params': [], 'has_body': False}, 'put_delay_delay': {'method': 'PUT', 'path': '/delay/{delay}', 'path_params': ['delay'], 'query_params': [], 'has_body': False}, 'delete_delete': {'method': 'DELETE', 'path': '/delete', 'path_params': [], 'query_params': [], 'has_body': False}, 'get_deny': {'method': 'GET', 'path': '/deny', 'path_params': [], 'query_params': [], 'has_body': False}, 'get_digest_auth_qop_user_passwd': {'method': 'GET', 'path': '/digest-auth/{qop}/{user}/{passwd}', 'path_params': ['qop', 'user', 'passwd'], 'query_params': [], 'has_body': False}, 'get_digest_auth_qop_user_passwd_algorithm': {'method': 'GET', 'path': '/digest-auth/{qop}/{user}/{passwd}/{algorithm}', 'path_params': ['qop', 'user', 'passwd', 'algorithm'], 'query_params': [], 'has_body': False}, 'get_digest_auth_qop_user_passwd_algorithm_stale_after': {'method': 'GET', 'path': '/digest-auth/{qop}/{user}/{passwd}/{algorithm}/{stale_after}', 'path_params': ['qop', 'user', 'passwd', 'algorithm', 'stale_after'], 'query_params': [], 'has_body': False}, 'get_drip': {'method': 'GET', 'path': '/drip', 'path_params': [], 'query_params': ['duration', 'numbytes', 'code', 'delay'], 'has_body': False}, 'get_encoding_utf8': {'method': 'GET', 'path': '/encoding/utf8', 'path_params': [], 'query_params': [], 'has_body': False}, 'get_etag_etag': {'method': 'GET', 'path': '/etag/{etag}', 'path_params': ['etag'], 'query_params': [], 'has_body': False}, 'get_get': {'method': 'GET', 'path': '/get', 'path_params': [], 'query_params': [], 'has_body': False}, 'get_gzip': {'method': 'GET', 'path': '/gzip', 'path_params': [], 'query_params': [], 'has_body': False}, 'get_headers': {'method': 'GET', 'path': '/headers', 'path_params': [], 'query_params': [], 'has_body': False}, 'get_hidden_basic_auth_user_passwd': {'method': 'GET', 'path': '/hidden-basic-auth/{user}/{passwd}', 'path_params': ['user', 'passwd'], 'query_params': [], 'has_body': False}, 'get_html': {'method': 'GET', 'path': '/html', 'path_params': [], 'query_params': [], 'has_body': False}, 'get_image': {'method': 'GET', 'path': '/image', 'path_params': [], 'query_params': [], 'has_body': False}, 'get_image_jpeg': {'method': 'GET', 'path': '/image/jpeg', 'path_params': [], 'query_params': [], 'has_body': False}, 'get_image_png': {'method': 'GET', 'path': '/image/png', 'path_params': [], 'query_params': [], 'has_body': False}, 'get_image_svg': {'method': 'GET', 'path': '/image/svg', 'path_params': [], 'query_params': [], 'has_body': False}, 'get_image_webp': {'method': 'GET', 'path': '/image/webp', 'path_params': [], 'query_params': [], 'has_body': False}, 'get_ip': {'method': 'GET', 'path': '/ip', 'path_params': [], 'query_params': [], 'has_body': False}, 'get_json': {'method': 'GET', 'path': '/json', 'path_params': [], 'query_params': [], 'has_body': False}, 'get_links_n_offset': {'method': 'GET', 'path': '/links/{n}/{offset}', 'path_params': ['n', 'offset'], 'query_params': [], 'has_body': False}, 'patch_patch': {'method': 'PATCH', 'path': '/patch', 'path_params': [], 'query_params': [], 'has_body': False}}


class GeneratedHttpbinConnector(ConnectorSDK):
    connector_id = "httpbin"
    display_name = "httpbin"
    description = "Generated from httpbin.org."
    category = ConnectorCategory.API
    version = "1.0.0"

    def __init__(self) -> None:
        super().__init__(self.connector_id, self.display_name, self.description)
        self._provider = GeneratedProvider()

    @property
    def node_types(self) -> list[str]:
        return ["httpbin"]

    async def connect(self, config: dict[str, Any]) -> bool:
        return True

    async def disconnect(self) -> None:
        self.status = ConnectorStatus.DISCONNECTED
        self._metadata.clear()

    async def op_execute(
        self, operation: str, payload: dict[str, Any], context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            params = GeneratedConnectorParams.model_validate(payload or {})
        except Exception as exc:
            raise make_connector_error(
                ConnectorErrorCode.BAD_REQUEST, f'Invalid payload: {exc}', retryable=False) from exc
        creds: dict[str, Any] = {}
        if context and context.get('credentials'):
            creds = context['credentials'].get("httpbin") or {}
        raw = payload or {}
        op = (operation or '').lower()
        if op in ('', 'execute'):
            op = str(params.operation or '').lower()
        meta = OPERATIONS.get(op)
        if meta is None:
            raise make_connector_error(
                ConnectorErrorCode.BAD_REQUEST, f'Unsupported operation {operation!r}.', retryable=False)
        path_values = {k: raw.get(k, '') for k in meta['path_params']}
        query = {k: raw[k] for k in meta['query_params'] if raw.get(k) not in (None, '')}
        body = raw.get('body') if meta['has_body'] else None
        result = await self._provider.call(
            creds, meta['method'], meta['path'], path_values, query, body,
            timeout=params.timeout_seconds, what=op,
        )
        if isinstance(result, dict):
            return result
        if isinstance(result, list):
            return {'items': result}
        return {'result': result}

    async def op_list(self, payload=None, context=None):
        return {'output': {'connector_id': self.connector_id, 'operations': sorted(OPERATIONS)}}
