"""OpenAPI emitter, Phase 1 (original implementation).

Turns a parsed `ApiSpec` (see `openapi_import`) into three Flowsmith
modules — provider, definition, connector — as source strings. The
caller writes them wherever it wants; `discover_generated()` loads
such pairs back from file paths. No network, no writes here.
"""

from __future__ import annotations

import json
import re
from typing import Any

from app.connectors.openapi_import import ApiOperation, ApiSpec

_KEY_RE = re.compile(r"[^a-z0-9_]+")
_OP_CAP = 50


def connector_key_for(name: str) -> str:
    """Slugify an arbitrary name into a safe connector key."""
    key = _KEY_RE.sub("_", name.lower()).strip("_")
    if not key or key[0].isdigit():
        key = f"gen_{key}" if key else "gen_api"
    return key[:48]


def _py_str(value: str) -> str:
    return json.dumps(value)


def _credential_block(auth_kind: str, key: str) -> tuple[str, str, str | None]:
    """Return (credential-fields-schema-props, required-list, require-or-None).

    As (python-dict-literal, python-list-literal, python-expr) strings.
    """
    if auth_kind == "api_key_header":
        props = '{"api_key": {"type": "string", "title": "API key"}}'
        req, require = '["api_key"]', f'"{key}"'
    elif auth_kind == "api_key_query":
        props = '{"api_key": {"type": "string", "title": "API key"}}'
        req, require = '["api_key"]', f'"{key}"'
    elif auth_kind == "bearer":
        props = '{"access_token": {"type": "string", "title": "Access token"}}'
        req, require = '["access_token"]', f'"{key}"'
    elif auth_kind == "basic":
        props = ('{"username": {"type": "string", "title": "Username"}, '
                 '"password": {"type": "string", "title": "Password"}}')
        req, require = '["username", "password"]', f'"{key}"'
    elif auth_kind == "oauth2":
        props = '{"access_token": {"type": "string", "title": "Access token (paste from OAuth flow)"}}'
        req, require = '["access_token"]', f'"{key}"'
    else:
        return "{}", "[]", "None"
    return props, req, require


def _secret_fields(auth_kind: str) -> str:
    mapping = {
        "api_key_header": ["api_key"],
        "api_key_query": ["api_key"],
        "bearer": ["access_token"],
        "basic": ["password"],
        "oauth2": ["access_token"],
    }
    return json.dumps(mapping.get(auth_kind, []))


def emit_provider(key: str, api: ApiSpec) -> str:
    auth = api.auth
    lines = [
        '"""Generated provider — do not hand-edit, regenerate from the OpenAPI spec.',
        "",
        f"Source API: {_py_str(api.title)}",
        f"Base URL: {_py_str(api.base_url or '(none declared)')}",
        '"""',
        "",
        "from __future__ import annotations",
        "",
        "from typing import Any",
        "",
        "from app.connectors import ConnectorErrorCode, make_connector_error",
        "from app.security.safe_http_client import get_safe_http_client",
        "",
        "",
        f"API_BASE = {_py_str(api.base_url)}",
        f"AUTH_KIND = {_py_str(auth.kind)}",
        f"AUTH_NAME = {_py_str(auth.name)}",
        "",
        "",
        "def _auth_parts(creds: dict) -> tuple[dict[str, str], dict[str, str]]:",
        '    """Return (headers, query) auth material.',
        "",
        "    Empty credentials pass through unauthenticated — public endpoints",
        '    work, protected ones answer 401 (mapped to AUTH_FAILED)."""',
    ]
    if auth.kind == "api_key_header":
        lines += [
            "    token = str((creds or {}).get('api_key') or '').strip()",
            "    if not token:",
            "        return {}, {}",
            f"    return {{{_py_str(auth.name)}: token}}, {{}}",
        ]
    elif auth.kind == "api_key_query":
        lines += [
            "    token = str((creds or {}).get('api_key') or '').strip()",
            "    if not token:",
            "        return {}, {}",
            f"    return {{}}, {{{_py_str(auth.name)}: token}}",
        ]
    elif auth.kind == "bearer":
        lines += [
            "    token = str((creds or {}).get('access_token') or '').strip()",
            "    if not token:",
            "        return {}, {}",
            '    return {"Authorization": f"Bearer {token}"}, {}',
        ]
    elif auth.kind == "basic":
        lines += [
            "    username = str((creds or {}).get('username') or '')",
            "    password = str((creds or {}).get('password') or '')",
            "    if not username:",
            "        return {}, {}",
            "    raw = f'{username}:{password}'.encode()",
            "    import base64 as _b64",
            "    return {'Authorization': 'Basic ' + _b64.b64encode(raw).decode()}, {}",
        ]
    elif auth.kind == "oauth2":
        lines += [
            "    token = str((creds or {}).get('access_token') or '').strip()",
            "    if not token:",
            "        return {}, {}",
            '    return {"Authorization": f"Bearer {token}"}, {}',
        ]
    else:
        lines += ['    return {}, {}']
    lines += [
        "",
        "",
        "def _raise_for_status(status: int, body: str, what: str) -> None:",
        "    if status < 400:",
        "        return",
        "    if status == 401:",
        "        raise make_connector_error(ConnectorErrorCode.AUTH_FAILED, f'Auth failed during {what}.', retryable=False)",
        "    if status == 403:",
        "        raise make_connector_error(ConnectorErrorCode.FORBIDDEN, f'Forbidden during {what}.', retryable=False)",
        "    if status == 404:",
        "        raise make_connector_error(ConnectorErrorCode.NOT_FOUND, f'Resource missing during {what}.', retryable=False)",
        "    if status == 429:",
        "        raise make_connector_error(ConnectorErrorCode.RATE_LIMITED, f'Rate limited during {what}.', retryable=True)",
        "    if status >= 500:",
        "        raise make_connector_error(ConnectorErrorCode.UNAVAILABLE, f'Service unavailable during {what}.', retryable=True)",
        "    raise make_connector_error(ConnectorErrorCode.BAD_REQUEST, f'Request rejected during {what}: {body[:200]}', retryable=False)",
        "",
        "",
        "class GeneratedProvider:",
        '    """Thin REST client for one generated connector."""',
        "",
        "    async def call(",
        "        self, creds: dict, method: str, path_template: str,",
        "        path_values: dict[str, Any] | None = None,",
        "        query: dict[str, Any] | None = None,",
        "        body: Any = None, timeout: float = 30.0, what: str = 'request',",
        "    ) -> Any:",
        "        if not API_BASE:",
        '            raise make_connector_error(ConnectorErrorCode.NOT_CONFIGURED, "No server URL in the imported spec.", retryable=False)',
        "        headers, auth_query = _auth_parts(creds)",
        "        path = path_template",
        "        for name, value in (path_values or {}).items():",
        "            from urllib.parse import quote as _quote",
        "            path = path.replace('{' + str(name) + '}', _quote(str(value), safe=''))",
        "        params = {**auth_query, **(query or {})}",
        "        try:",
        "            async with get_safe_http_client() as client:",
        "                kwargs: dict[str, Any] = {'timeout': timeout}",
        "                if body is not None:",
        "                    kwargs['json'] = body",
        "                response = await client.request(method, API_BASE + path, headers=headers or None, params=params or None, **kwargs)",
        "        except Exception as exc:",
        "            raise make_connector_error(",
        "                ConnectorErrorCode.UNAVAILABLE, f'Unreachable during {what}: {exc}', retryable=True) from exc",
        "        _raise_for_status(response.status_code, response.text, what)",
        "        try:",
        "            return response.json()",
        "        except Exception:",
        "            return {'raw': response.text}",
        "",
    ]
    return "\n".join(lines)


def _op_input_schema(op: ApiOperation) -> str:
    props: dict[str, Any] = {}
    required: list[str] = []
    for name in op.path_params:
        props[name] = {"type": "string", "title": name}
        required.append(name)
    for param in op.query_params:
        props[param.name] = {"type": "string", "title": param.name}
        if param.required and param.name not in required:
            required.append(param.name)
    if op.has_body:
        props["body"] = {"type": "object", "title": "Request body"}
    return json.dumps({"type": "object", "properties": props, "required": required})


def emit_definition(key: str, display_name: str, api: ApiSpec, category: str = "api") -> str:
    props, req, require = _credential_block(api.auth.kind, key)
    lines = [
        '"""Generated definition — do not hand-edit, regenerate from the OpenAPI spec.',
        "",
        f"Source API: {_py_str(api.title)}",
        '"""',
        "",
        "from __future__ import annotations",
        "",
        "from app.connectors import (",
        "    ConnectorDefinitionV1,",
        "    ConnectorLifecycle,",
        "    ConnectorOperationV1,",
        "    CredentialTypeV1,",
        ")",
        "",
        "",
        f"CONNECTOR_KEY = {_py_str(key)}",
        'CONNECTOR_VERSION = "1.0.0"',
        'OPERATION_VERSION = "1.0.0"',
        "",
        "",
        "def _operation(key, display_name, description, input_schema, *, retryable=True, idempotency='idempotent'):",
        "    return ConnectorOperationV1(",
        "        connector_key=CONNECTOR_KEY,",
        "        connector_version=CONNECTOR_VERSION,",
        "        operation_key=key,",
        "        operation_version=OPERATION_VERSION,",
        "        display_name=display_name,",
        "        description=description,",
        "        input_schema=input_schema,",
        '        output_schema={"type": "object", "properties": {}},',
        f"        credential_require={require},",
        "        retryable=retryable,",
        "        idempotency=idempotency,",
        "        node_types=[CONNECTOR_KEY],",
        "    )",
        "",
        "",
        "def _operations():",
        "    return {",
    ]
    for op in api.operations[:_OP_CAP]:
        title = re.sub(r"\s+", " ", (op.summary or op.operation_key))[:80]
        lines.append(
            f"        {_py_str(op.operation_key)}: _operation("
            f"{_py_str(op.operation_key)}, {_py_str(title)}, "
            f"{_py_str(f'{op.method} {op.path}')}, {_op_input_schema(op)}),"
        )
    lines += [
        "    }",
        "",
        "",
        f"def build_{key}_definition() -> ConnectorDefinitionV1:",
        "    return ConnectorDefinitionV1(",
        "        connector_key=CONNECTOR_KEY,",
        f"        display_name={_py_str(display_name)},",
        f"        description={_py_str(f'Generated from {api.title}.')},",
        f"        category={_py_str(category)},",
        '        connector_version=CONNECTOR_VERSION,',
        "        lifecycle_status=ConnectorLifecycle.BETA.value,",
        "        operations=_operations(),",
        "        triggers={},",
    ]
    if require == "None":
        lines += ["        credential_types={},"]
    else:
        lines += [
            "        credential_types={",
            f"            {_py_str(key)}: CredentialTypeV1(",
            f"                type_key={_py_str(key)},",
            f"                display_name={_py_str(display_name)},",
            f"                description={_py_str(f'Credentials for {api.title} (imported).')},",
            f"                secret_fields={_secret_fields(api.auth.kind)},",
            "                validation_schema={",
            '                    "type": "object",',
            f"                    {_py_str('properties')}: {props},",
            f"                    {_py_str('required')}: {req},",
            "                },",
            "                encryption_required=True,",
            "            ),",
            "        },",
        ]
    lines += [
        "        metadata={" + f'"source": "openapi-import", "api_title": {_py_str(api.title)}' + "},",
        '        icon="openapi",',
        "    )",
        "",
    ]
    return "\n".join(lines)


def emit_connector(key: str, display_name: str, api: ApiSpec) -> str:
    ops_table = repr(
        {o.operation_key: {"method": o.method, "path": o.path,
                           "path_params": o.path_params,
                           "query_params": [p.name for p in o.query_params],
                           "has_body": o.has_body}
         for o in api.operations[:_OP_CAP]})
    return "\n".join([
        '"""Generated connector — do not hand-edit, regenerate from the OpenAPI spec.',
        "",
        f"Source API: {_py_str(api.title)}",
        '"""',
        "",
        "from __future__ import annotations",
        "",
        "from typing import Any",
        "",
        "from pydantic import BaseModel, Field",
        "",
        "from app.connectors import (",
        "    ConnectorCategory,",
        "    ConnectorErrorCode,",
        "    ConnectorSDK,",
        "    ConnectorStatus,",
        "    make_connector_error,",
        ")",
        "",
        f"from gen_{key}_provider import GeneratedProvider",
        "",
        "",
        "class GeneratedConnectorParams(BaseModel):",
        '    operation: str = Field(default="")',
        "    timeout_seconds: float = Field(default=30.0, ge=1, le=300)",
        "",
        "    model_config = {'extra': 'allow'}",
        "",
        "",
        f"OPERATIONS = {ops_table}",
        "",
        "",
        f"class Generated{''.join(p.title() for p in key.split('_'))}Connector(ConnectorSDK):",
        f'    connector_id = {_py_str(key)}',
        f'    display_name = {_py_str(display_name)}',
        f'    description = {_py_str(f"Generated from {api.title}.")}',
        "    category = ConnectorCategory.API",
        '    version = "1.0.0"',
        "",
        "    def __init__(self) -> None:",
        "        super().__init__(self.connector_id, self.display_name, self.description)",
        "        self._provider = GeneratedProvider()",
        "",
        "    @property",
        "    def node_types(self) -> list[str]:",
        f"        return [{_py_str(key)}]",
        "",
        "    async def connect(self, config: dict[str, Any]) -> bool:",
        "        return True",
        "",
        "    async def disconnect(self) -> None:",
        "        self.status = ConnectorStatus.DISCONNECTED",
        "        self._metadata.clear()",
        "",
        "    async def op_execute(",
        "        self, operation: str, payload: dict[str, Any], context: dict[str, Any] | None = None,",
        "    ) -> dict[str, Any]:",
        "        try:",
        "            params = GeneratedConnectorParams.model_validate(payload or {})",
        "        except Exception as exc:",
        "            raise make_connector_error(",
        "                ConnectorErrorCode.BAD_REQUEST, f'Invalid payload: {exc}', retryable=False) from exc",
        "        creds: dict[str, Any] = {}",
        "        if context and context.get('credentials'):",
        f"            creds = context['credentials'].get({_py_str(key)}) or {{}}",
        "        raw = payload or {}",
        "        op = (operation or '').lower()",
        "        if op in ('', 'execute'):",
        "            op = str(params.operation or '').lower()",
        "        meta = OPERATIONS.get(op)",
        "        if meta is None:",
        "            raise make_connector_error(",
        "                ConnectorErrorCode.BAD_REQUEST, f'Unsupported operation {operation!r}.', retryable=False)",
        "        path_values = {k: raw.get(k, '') for k in meta['path_params']}",
        "        query = {k: raw[k] for k in meta['query_params'] if raw.get(k) not in (None, '')}",
        "        body = raw.get('body') if meta['has_body'] else None",
        "        result = await self._provider.call(",
        "            creds, meta['method'], meta['path'], path_values, query, body,",
        "            timeout=params.timeout_seconds, what=op,",
        "        )",
        "        if isinstance(result, dict):",
        "            return result",
        "        if isinstance(result, list):",
        "            return {'items': result}",
        "        return {'result': result}",
        "",
        "    async def op_list(self, payload=None, context=None):",
        "        return {'output': {'connector_id': self.connector_id, 'operations': sorted(OPERATIONS)}}",
        "",
    ])


def emit_connector_files(
    name: str, display_name: str, api: ApiSpec, category: str = "api",
) -> dict[str, str]:
    """Emit {filename: source} for provider + definition + connector."""
    key = connector_key_for(name)
    return {
        f"gen_{key}_provider.py": emit_provider(key, api),
        f"gen_{key}_definition.py": emit_definition(key, display_name, api, category),
        f"gen_{key}_connector.py": emit_connector(key, display_name, api),
    }


def discover_generated(directory: str) -> list[tuple[Any, Any]]:
    """Load generated connector pairs from a directory.

    Returns [(connector_instance, definition)] for every complete,
    valid triple (provider + definition + connector). Anything broken
    is skipped with a warning — discovery never crashes the caller.
    Imported modules stay in sys.modules; restart to pick up edits.
    """
    import importlib
    import logging
    import sys
    from pathlib import Path

    from app.connectors import ConnectorSDK
    from app.connectors.registry import validate_definition

    log = logging.getLogger("openapi-import")
    found: list[tuple[Any, Any]] = []
    directory_path = str(directory)
    sys.path.insert(0, directory_path)
    try:
        for connector_file in sorted(Path(directory_path).glob("gen_*_connector.py")):
            stem = connector_file.stem  # gen_<key>_connector
            key = stem[len("gen_"): -len("_connector")]
            try:
                try:
                    provider_mod = importlib.import_module(f"app.connectors.generated.gen_{key}_provider")
                    definition_mod = importlib.import_module(f"app.connectors.generated.gen_{key}_definition")
                    connector_mod = importlib.import_module(f"app.connectors.generated.gen_{key}_connector")
                except (ImportError, ModuleNotFoundError):
                    provider_mod = importlib.import_module(f"gen_{key}_provider")
                    definition_mod = importlib.import_module(f"gen_{key}_definition")
                    connector_mod = importlib.import_module(f"gen_{key}_connector")
            except Exception as exc:
                log.warning("generated connector %s skipped (import): %s", key, exc)
                continue
            builders = [
                getattr(definition_mod, name) for name in dir(definition_mod)
                if name.startswith("build_") and name.endswith("_definition")
                and callable(getattr(definition_mod, name))
            ]
            classes = [
                obj for _, obj in vars(connector_mod).items()
                if isinstance(obj, type) and issubclass(obj, ConnectorSDK) and obj is not ConnectorSDK
            ]
            if len(builders) != 1 or len(classes) != 1:
                log.warning("generated connector %s skipped (ambiguous module contents)", key)
                continue
            try:
                definition = builders[0]()
                validate_definition(definition)
                found.append((classes[0](), definition))
            except Exception as exc:
                log.warning("generated connector %s skipped (invalid): %s", key, exc)
    finally:
        try:
            sys.path.remove(directory_path)
        except ValueError:
            pass
    return found


def register_generated(registry: Any, directory: str) -> int:
    """Register all discoverable generated connectors; return the count."""
    import logging

    log = logging.getLogger("openapi-import")
    count = 0
    for instance, definition in discover_generated(directory):
        try:
            registry.register(instance, definition)
            count += 1
        except Exception as exc:
            log.warning("generated connector %s not registered: %s", instance.connector_id, exc)
    return count
