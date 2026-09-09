"""Generated definition — do not hand-edit, regenerate from the OpenAPI spec.

Source API: httpbin.org
"""

from __future__ import annotations

from app.connectors import (
    ConnectorDefinitionV1,
    ConnectorLifecycle,
    ConnectorOperationV1,
    CredentialTypeV1,
)


CONNECTOR_KEY = "httpbin"
CONNECTOR_VERSION = "1.0.0"
OPERATION_VERSION = "1.0.0"


def _operation(key, display_name, description, input_schema, *, retryable=True, idempotency='idempotent'):
    return ConnectorOperationV1(
        connector_key=CONNECTOR_KEY,
        connector_version=CONNECTOR_VERSION,
        operation_key=key,
        operation_version=OPERATION_VERSION,
        display_name=display_name,
        description=description,
        input_schema=input_schema,
        output_schema={"type": "object", "properties": {}},
        credential_require=None,
        retryable=retryable,
        idempotency=idempotency,
        node_types=[CONNECTOR_KEY],
    )


def _operations():
    return {
        "get_absolute_redirect_n": _operation("get_absolute_redirect_n", "Absolutely 302 Redirects n times.", "GET /absolute-redirect/{n}", {"type": "object", "properties": {"n": {"type": "string", "title": "n"}}, "required": ["n"]}),
        "delete_anything": _operation("delete_anything", "Returns anything passed in request data.", "DELETE /anything", {"type": "object", "properties": {}, "required": []}),
        "get_anything": _operation("get_anything", "Returns anything passed in request data.", "GET /anything", {"type": "object", "properties": {}, "required": []}),
        "patch_anything": _operation("patch_anything", "Returns anything passed in request data.", "PATCH /anything", {"type": "object", "properties": {}, "required": []}),
        "post_anything": _operation("post_anything", "Returns anything passed in request data.", "POST /anything", {"type": "object", "properties": {}, "required": []}),
        "put_anything": _operation("put_anything", "Returns anything passed in request data.", "PUT /anything", {"type": "object", "properties": {}, "required": []}),
        "delete_anything_anything": _operation("delete_anything_anything", "Returns anything passed in request data.", "DELETE /anything/{anything}", {"type": "object", "properties": {"anything": {"type": "string", "title": "anything"}}, "required": ["anything"]}),
        "get_anything_anything": _operation("get_anything_anything", "Returns anything passed in request data.", "GET /anything/{anything}", {"type": "object", "properties": {"anything": {"type": "string", "title": "anything"}}, "required": ["anything"]}),
        "patch_anything_anything": _operation("patch_anything_anything", "Returns anything passed in request data.", "PATCH /anything/{anything}", {"type": "object", "properties": {"anything": {"type": "string", "title": "anything"}}, "required": ["anything"]}),
        "post_anything_anything": _operation("post_anything_anything", "Returns anything passed in request data.", "POST /anything/{anything}", {"type": "object", "properties": {"anything": {"type": "string", "title": "anything"}}, "required": ["anything"]}),
        "put_anything_anything": _operation("put_anything_anything", "Returns anything passed in request data.", "PUT /anything/{anything}", {"type": "object", "properties": {"anything": {"type": "string", "title": "anything"}}, "required": ["anything"]}),
        "get_base64_value": _operation("get_base64_value", "Decodes base64url-encoded string.", "GET /base64/{value}", {"type": "object", "properties": {"value": {"type": "string", "title": "value"}}, "required": ["value"]}),
        "get_basic_auth_user_passwd": _operation("get_basic_auth_user_passwd", "Prompts the user for authorization using HTTP Basic Auth.", "GET /basic-auth/{user}/{passwd}", {"type": "object", "properties": {"user": {"type": "string", "title": "user"}, "passwd": {"type": "string", "title": "passwd"}}, "required": ["user", "passwd"]}),
        "get_bearer": _operation("get_bearer", "Prompts the user for authorization using bearer authentication.", "GET /bearer", {"type": "object", "properties": {}, "required": []}),
        "get_brotli": _operation("get_brotli", "Returns Brotli-encoded data.", "GET /brotli", {"type": "object", "properties": {}, "required": []}),
        "get_bytes_n": _operation("get_bytes_n", "Returns n random bytes generated with given seed", "GET /bytes/{n}", {"type": "object", "properties": {"n": {"type": "string", "title": "n"}}, "required": ["n"]}),
        "get_cache": _operation("get_cache", "Returns a 304 if an If-Modified-Since header or If-None-Match is present. Return", "GET /cache", {"type": "object", "properties": {}, "required": []}),
        "get_cache_value": _operation("get_cache_value", "Sets a Cache-Control header for n seconds.", "GET /cache/{value}", {"type": "object", "properties": {"value": {"type": "string", "title": "value"}}, "required": ["value"]}),
        "get_cookies": _operation("get_cookies", "Returns cookie data.", "GET /cookies", {"type": "object", "properties": {}, "required": []}),
        "get_cookies_delete": _operation("get_cookies_delete", "Deletes cookie(s) as provided by the query string and redirects to cookie list.", "GET /cookies/delete", {"type": "object", "properties": {"freeform": {"type": "string", "title": "freeform"}}, "required": []}),
        "get_cookies_set": _operation("get_cookies_set", "Sets cookie(s) as provided by the query string and redirects to cookie list.", "GET /cookies/set", {"type": "object", "properties": {"freeform": {"type": "string", "title": "freeform"}}, "required": []}),
        "get_cookies_set_name_value": _operation("get_cookies_set_name_value", "Sets a cookie and redirects to cookie list.", "GET /cookies/set/{name}/{value}", {"type": "object", "properties": {"name": {"type": "string", "title": "name"}, "value": {"type": "string", "title": "value"}}, "required": ["name", "value"]}),
        "get_deflate": _operation("get_deflate", "Returns Deflate-encoded data.", "GET /deflate", {"type": "object", "properties": {}, "required": []}),
        "delete_delay_delay": _operation("delete_delay_delay", "Returns a delayed response (max of 10 seconds).", "DELETE /delay/{delay}", {"type": "object", "properties": {"delay": {"type": "string", "title": "delay"}}, "required": ["delay"]}),
        "get_delay_delay": _operation("get_delay_delay", "Returns a delayed response (max of 10 seconds).", "GET /delay/{delay}", {"type": "object", "properties": {"delay": {"type": "string", "title": "delay"}}, "required": ["delay"]}),
        "patch_delay_delay": _operation("patch_delay_delay", "Returns a delayed response (max of 10 seconds).", "PATCH /delay/{delay}", {"type": "object", "properties": {"delay": {"type": "string", "title": "delay"}}, "required": ["delay"]}),
        "post_delay_delay": _operation("post_delay_delay", "Returns a delayed response (max of 10 seconds).", "POST /delay/{delay}", {"type": "object", "properties": {"delay": {"type": "string", "title": "delay"}}, "required": ["delay"]}),
        "put_delay_delay": _operation("put_delay_delay", "Returns a delayed response (max of 10 seconds).", "PUT /delay/{delay}", {"type": "object", "properties": {"delay": {"type": "string", "title": "delay"}}, "required": ["delay"]}),
        "delete_delete": _operation("delete_delete", "The request's DELETE parameters.", "DELETE /delete", {"type": "object", "properties": {}, "required": []}),
        "get_deny": _operation("get_deny", "Returns page denied by robots.txt rules.", "GET /deny", {"type": "object", "properties": {}, "required": []}),
        "get_digest_auth_qop_user_passwd": _operation("get_digest_auth_qop_user_passwd", "Prompts the user for authorization using Digest Auth.", "GET /digest-auth/{qop}/{user}/{passwd}", {"type": "object", "properties": {"qop": {"type": "string", "title": "qop"}, "user": {"type": "string", "title": "user"}, "passwd": {"type": "string", "title": "passwd"}}, "required": ["qop", "user", "passwd"]}),
        "get_digest_auth_qop_user_passwd_algorithm": _operation("get_digest_auth_qop_user_passwd_algorithm", "Prompts the user for authorization using Digest Auth + Algorithm.", "GET /digest-auth/{qop}/{user}/{passwd}/{algorithm}", {"type": "object", "properties": {"qop": {"type": "string", "title": "qop"}, "user": {"type": "string", "title": "user"}, "passwd": {"type": "string", "title": "passwd"}, "algorithm": {"type": "string", "title": "algorithm"}}, "required": ["qop", "user", "passwd", "algorithm"]}),
        "get_digest_auth_qop_user_passwd_algorithm_stale_after": _operation("get_digest_auth_qop_user_passwd_algorithm_stale_after", "Prompts the user for authorization using Digest Auth + Algorithm.", "GET /digest-auth/{qop}/{user}/{passwd}/{algorithm}/{stale_after}", {"type": "object", "properties": {"qop": {"type": "string", "title": "qop"}, "user": {"type": "string", "title": "user"}, "passwd": {"type": "string", "title": "passwd"}, "algorithm": {"type": "string", "title": "algorithm"}, "stale_after": {"type": "string", "title": "stale_after"}}, "required": ["qop", "user", "passwd", "algorithm", "stale_after"]}),
        "get_drip": _operation("get_drip", "Drips data over a duration after an optional initial delay.", "GET /drip", {"type": "object", "properties": {"duration": {"type": "string", "title": "duration"}, "numbytes": {"type": "string", "title": "numbytes"}, "code": {"type": "string", "title": "code"}, "delay": {"type": "string", "title": "delay"}}, "required": []}),
        "get_encoding_utf8": _operation("get_encoding_utf8", "Returns a UTF-8 encoded body.", "GET /encoding/utf8", {"type": "object", "properties": {}, "required": []}),
        "get_etag_etag": _operation("get_etag_etag", "Assumes the resource has the given etag and responds to If-None-Match and If-Mat", "GET /etag/{etag}", {"type": "object", "properties": {"etag": {"type": "string", "title": "etag"}}, "required": ["etag"]}),
        "get_get": _operation("get_get", "The request's query parameters.", "GET /get", {"type": "object", "properties": {}, "required": []}),
        "get_gzip": _operation("get_gzip", "Returns GZip-encoded data.", "GET /gzip", {"type": "object", "properties": {}, "required": []}),
        "get_headers": _operation("get_headers", "Return the incoming request's HTTP headers.", "GET /headers", {"type": "object", "properties": {}, "required": []}),
        "get_hidden_basic_auth_user_passwd": _operation("get_hidden_basic_auth_user_passwd", "Prompts the user for authorization using HTTP Basic Auth.", "GET /hidden-basic-auth/{user}/{passwd}", {"type": "object", "properties": {"user": {"type": "string", "title": "user"}, "passwd": {"type": "string", "title": "passwd"}}, "required": ["user", "passwd"]}),
        "get_html": _operation("get_html", "Returns a simple HTML document.", "GET /html", {"type": "object", "properties": {}, "required": []}),
        "get_image": _operation("get_image", "Returns a simple image of the type suggest by the Accept header.", "GET /image", {"type": "object", "properties": {}, "required": []}),
        "get_image_jpeg": _operation("get_image_jpeg", "Returns a simple JPEG image.", "GET /image/jpeg", {"type": "object", "properties": {}, "required": []}),
        "get_image_png": _operation("get_image_png", "Returns a simple PNG image.", "GET /image/png", {"type": "object", "properties": {}, "required": []}),
        "get_image_svg": _operation("get_image_svg", "Returns a simple SVG image.", "GET /image/svg", {"type": "object", "properties": {}, "required": []}),
        "get_image_webp": _operation("get_image_webp", "Returns a simple WEBP image.", "GET /image/webp", {"type": "object", "properties": {}, "required": []}),
        "get_ip": _operation("get_ip", "Returns the requester's IP Address.", "GET /ip", {"type": "object", "properties": {}, "required": []}),
        "get_json": _operation("get_json", "Returns a simple JSON document.", "GET /json", {"type": "object", "properties": {}, "required": []}),
        "get_links_n_offset": _operation("get_links_n_offset", "Generate a page containing n links to other pages which do the same.", "GET /links/{n}/{offset}", {"type": "object", "properties": {"n": {"type": "string", "title": "n"}, "offset": {"type": "string", "title": "offset"}}, "required": ["n", "offset"]}),
        "patch_patch": _operation("patch_patch", "The request's PATCH parameters.", "PATCH /patch", {"type": "object", "properties": {}, "required": []}),
    }


def build_httpbin_definition() -> ConnectorDefinitionV1:
    return ConnectorDefinitionV1(
        connector_key=CONNECTOR_KEY,
        display_name="httpbin",
        description="Generated from httpbin.org.",
        category="developer",
        connector_version=CONNECTOR_VERSION,
        lifecycle_status=ConnectorLifecycle.BETA.value,
        operations=_operations(),
        triggers={},
        credential_types={},
        metadata={"source": "openapi-import", "api_title": "httpbin.org"},
        icon="🧲",
    )
