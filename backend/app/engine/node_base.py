"""The node SDK contract (spec 7, 26, 27).

A node is a class that declares metadata + a Pydantic parameters schema
and implements `run()`. The same schema drives validation now and will
drive the API config-panel forms later.
"""

from __future__ import annotations

import asyncio
import logging
import time
import zlib
from typing import Any, Callable, Generic, TypeVar, cast

import httpx
from pydantic import BaseModel

from app.engine.errors import NodeExecutionError

__all__ = [
    "BaseNode",
    "NodeContext",
    "NodeResult",
    "MemoryKVStore",
    "NodeExecutionError",
    "IDEMPOTENT",
    "CONDITIONALLY_IDEMPOTENT",
    "NON_IDEMPOTENT",
    "DEFAULT_MAX_RESPONSE_BYTES",
    "request_with_size_cap",
]

IDEMPOTENT = "idempotent"
CONDITIONALLY_IDEMPOTENT = "conditionally_idempotent"
NON_IDEMPOTENT = "non-idempotent"
#: Fallback response-size cap when a node does not set its own (H19).
DEFAULT_MAX_RESPONSE_BYTES = 10 * 1024 * 1024
#: Valid values for BaseNode.idempotency (spec 35).
IDEMPOTENCY_LEVELS = frozenset({IDEMPOTENT, CONDITIONALLY_IDEMPOTENT, NON_IDEMPOTENT})

ParamsT = TypeVar("ParamsT", bound=BaseModel)


class MemoryKVStore:
    """Async in-process TTL key/value store for node idempotency caching.

    Nodes read/write it with ``await ctx.storage.get/set``; entries
    expire after their TTL (seconds) or live forever when no TTL is set.
    """

    def __init__(self) -> None:
        self._data: dict[str, tuple[Any, float | None]] = {}
        self._lock = asyncio.Lock()

    async def get(self, key: str, default: Any = None) -> Any:
        async with self._lock:
            item = self._data.get(key)
            if item is None:
                return default
            value, expires = item
            if expires is not None and time.monotonic() > expires:
                self._data.pop(key, None)
                return default
            return value

    async def set(self, key: str, value: Any, ttl: float | None = None) -> None:
        async with self._lock:
            expires = time.monotonic() + ttl if ttl is not None else None
            self._data[key] = (value, expires)

    def seed(self, key: str, value: Any) -> None:
        """Synchronous pre-loop insert (resume seeding); no lock needed
        because it runs before any task exists."""
        self._data[key] = (value, None)


class NodeResult(BaseModel):
    """Structured output of a node run (spec 27).

    Either `output_items` (for the "main" handle) or `output_by_handle`
    (for multi-output nodes like IF: {"true": [...], "false": [...]}).
    """

    output_items: list[dict[str, Any]] | None = None
    output_by_handle: dict[str, list[dict[str, Any]]] | None = None
    metadata: dict[str, Any] = {}

    def items_for(self, handle: str) -> list[dict[str, Any]]:
        if self.output_by_handle is not None:
            return self.output_by_handle.get(handle, [])
        return self.output_items or []


def filter_client_kwargs(client: Any, kwargs: dict[str, Any]) -> dict[str, Any]:
    """Drop kwargs the injected HTTP client doesn't support, so nodes can
    pass the full extended set (follow_redirects, max_response_bytes, …)
    while plain httpx.AsyncClient test doubles keep working."""
    import inspect

    request_fn = getattr(client, "request", None)
    if request_fn is None:
        return {}
    try:
        sig = inspect.signature(request_fn)
    except (TypeError, ValueError):
        return kwargs
    if any(pr.kind is inspect.Parameter.VAR_KEYWORD for pr in sig.parameters.values()):
        return kwargs
    named = {
        name for name, pr in sig.parameters.items()
        if pr.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
    }
    return {k: v for k, v in kwargs.items() if k in named}


async def request_with_size_cap(
    client: Any,
    method: str,
    url: str,
    *,
    max_response_bytes: int | None,
    node_id: str,
    code: str = "RESPONSE_TOO_LARGE",
    **kwargs: Any,
) -> httpx.Response:
    """Issue a request that can never buffer more than the size cap (H19).

    Clients that understand ``max_response_bytes`` (SafeHTTPClient) get the
    kwarg through the normal filter and enforce it themselves. Plain httpx
    clients silently drop the unknown kwarg — which is what made the node
    cap a no-op — so we stream the body here and abort the moment the cap
    is exceeded, before a hostile endpoint can stream gigabytes into memory.

    Also mirrors SafeHTTPClient's handling of the Salesforce/F5 quirk: a
    response advertising ``Content-Encoding`` over a body it never
    compressed fails to decode ("Error -3 while decompressing data:
    incorrect header check"). ``_stream_capped`` recovers that leniently;
    a genuinely corrupt compressed body is replayed once with
    ``Accept-Encoding: identity`` — but only for methods that are safe to
    replay, because a POST may already have executed server-side.
    """
    cap = (
        max_response_bytes
        if max_response_bytes and max_response_bytes > 0
        else DEFAULT_MAX_RESPONSE_BYTES
    )
    try:
        return await _dispatch_capped(
            client, method, url, cap=cap, node_id=node_id, code=code, kwargs=kwargs
        )
    except httpx.DecodingError as exc:
        upper = method.upper()
        original_headers = kwargs.get("headers") or {}
        already_identity = any(
            k.lower() == "accept-encoding" and str(v).strip().lower() == "identity"
            for k, v in original_headers.items()
        )
        if upper not in ("GET", "HEAD", "OPTIONS") or already_identity:
            raise NodeExecutionError(
                f"HTTP {upper} request failed: response body could not be decoded.",
                code="HTTP_REQUEST_FAILED", node_id=node_id, retryable=False,
            ) from exc
        retry_headers = {
            k: v for k, v in original_headers.items() if k.lower() != "accept-encoding"
        }
        retry_headers["Accept-Encoding"] = "identity"
        retry_kwargs = {**kwargs, "headers": retry_headers}
        try:
            return await _dispatch_capped(
                client, method, url, cap=cap, node_id=node_id, code=code,
                kwargs=retry_kwargs,
            )
        except httpx.DecodingError as exc2:
            raise NodeExecutionError(
                "HTTP request failed: response body could not be decoded even "
                "with Accept-Encoding: identity.",
                code="HTTP_REQUEST_FAILED", node_id=node_id, retryable=True,
            ) from exc2


async def _dispatch_capped(
    client: Any,
    method: str,
    url: str,
    *,
    cap: int,
    node_id: str,
    code: str,
    kwargs: dict[str, Any],
) -> httpx.Response:
    """Single attempt of ``request_with_size_cap``, split out so the
    decode-failure handler can replay it with modified headers."""
    filtered = filter_client_kwargs(client, {**kwargs, "max_response_bytes": cap})
    if "max_response_bytes" in filtered:
        response = await client.request(method, url, **filtered)
        await _assert_redirects_public(response, node_id)
    elif isinstance(client, httpx.AsyncClient):
        response = await _stream_capped(
            client, method, url, filtered, cap, node_id=node_id, code=code
        )
    else:
        request_fn = getattr(client, "request", None)
        if request_fn is None:
            # Test double exposing only verb helpers (post/get/...).
            response = await getattr(client, method.lower())(url, **filtered)
        else:
            response = await request_fn(method, url, **filtered)
        await _assert_redirects_public(response, node_id)
    return response


async def _assert_redirects_public(response: httpx.Response, node_id: str) -> None:
    """Re-validate every redirect hop before its body is consumed.

    The shared execution client does this in a request hook, but a bare
    client does not — without it a public URL that 302s to an internal
    address would be fetched and surfaced.
    """
    # Test doubles (and any response built without httpx internals) may not
    # carry `.history`; treat it as "no redirects" rather than crashing.
    history = getattr(response, "history", None) or ()
    if not history:
        return
    from app.security.ssrf import assert_public_url

    for hop in (*history, response):
        await assert_public_url(str(hop.url), node_id=node_id)


async def _stream_capped(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    kwargs: dict[str, Any],
    cap: int,
    *,
    node_id: str,
    code: str,
) -> httpx.Response:
    """Stream the response body, failing fast once *cap* is exceeded and
    rebuilding the response so callers see a normal fully-read httpx.Response
    (content, headers, request and redirect history intact).

    ``gzip``/``deflate`` bodies are captured raw and decoded leniently
    (bounded by *cap*) instead of through httpx's built-in decoder, so a
    server that advertises compression it did not apply — or violates the
    deflate framing rules — yields the plain body instead of a
    decompression failure."""
    async with client.stream(method, url, **kwargs) as response:
        await _assert_redirects_public(response, node_id)
        ce = (response.headers.get("content-encoding") or "").strip().lower()
        if any(enc in ce for enc in ("gzip", "deflate", "compress")):
            raw = bytearray()
            async for chunk in response.aiter_raw():
                raw += chunk
                if len(raw) > cap + 65536:
                    raise NodeExecutionError(
                        f"Response exceeded the maximum allowed size ({cap} bytes).",
                        code=code, node_id=node_id, retryable=False,
                    )
            content = _decode_content_lenient(
                bytes(raw), ce, cap, node_id=node_id, code=code
            )
        else:
            chunks: list[bytes] = []
            total = 0
            async for chunk in response.aiter_bytes():
                total += len(chunk)
                if total > cap:
                    raise NodeExecutionError(
                        f"Response exceeded the maximum allowed size ({cap} bytes).",
                        code=code, node_id=node_id, retryable=False,
                    )
                chunks.append(chunk)
            content = b"".join(chunks)
        # The body is already decoded: drop Content-Encoding (httpx re-reads
        # a `content=` response during construction and would re-apply the
        # codec to the decoded bytes — the "Error -3 while decompressing
        # data" crash) plus the now-stale framing headers.
        rebuilt_headers = httpx.Headers(
            [(k, v) for k, v in response.headers.items() if k.lower() not in ("content-encoding", "content-length", "transfer-encoding")]
        )
        return httpx.Response(
            status_code=response.status_code,
            headers=rebuilt_headers,
            content=content,
            request=response.request,
            history=response.history,
        )


def _decode_content_lenient(
    raw: bytes, content_encoding: str, cap: int, *, node_id: str, code: str
) -> bytes:
    """Decode *raw* under *content_encoding*, tolerating servers that lie.

    * Valid compressed data decodes normally (output bounded by *cap*).
    * A body without the advertised framing (the Salesforce/F5
      ``Content-Encoding: gzip`` over a plain body bug) is returned
      as-is — the header was simply wrong.
    * Data that DOES carry the framing but is corrupt raises
      ``httpx.DecodingError`` so the caller can replay with
      ``Accept-Encoding: identity``.
    """
    ce = content_encoding.strip().lower()
    if "deflate" in ce and "gzip" not in ce:
        candidates: tuple[int, ...] = (15, -15, 47)
    else:
        candidates = (47, 31, 15, -15)
    last_err: zlib.error | None = None
    for wbits in candidates:
        try:
            return _decompress_bounded(raw, wbits, cap, node_id=node_id, code=code)
        except zlib.error as exc:
            last_err = exc
    if _looks_compressed(raw, ce):
        raise httpx.DecodingError(
            str(last_err) or "response body could not be decompressed"
        ) from last_err
    # Header advertised compression that never happened: the body IS the
    # payload (already bounded by the caller's raw-byte cap).
    return raw


def _decompress_bounded(
    raw: bytes, wbits: int, cap: int, *, node_id: str, code: str
) -> bytes:
    """zlib-decompress *raw*, aborting as soon as the output exceeds *cap*."""
    obj = zlib.decompressobj(wbits)
    out = bytearray()
    buf = raw
    while buf:
        piece = obj.decompress(buf, max_length=cap + 1 - len(out))
        out += piece
        if len(out) > cap:
            raise NodeExecutionError(
                f"Response exceeded the maximum allowed size ({cap} bytes).",
                code=code, node_id=node_id, retryable=False,
            )
        buf = obj.unconsumed_tail
        if not piece and buf:
            # No progress without hitting the cap: corrupt input.
            raise zlib.error("decompression made no progress")
    out += obj.flush()
    if len(out) > cap:
        raise NodeExecutionError(
            f"Response exceeded the maximum allowed size ({cap} bytes).",
            code=code, node_id=node_id, retryable=False,
        )
    return bytes(out)


def _looks_compressed(raw: bytes, ce: str) -> bool:
    """Does *raw* actually carry the framing *ce* advertises?"""
    if "gzip" in ce:
        return raw.startswith(b"\x1f\x8b")
    # zlib wrapper: CMF/FLG header check (RFC 1950 §2.2).
    if len(raw) >= 2 and (raw[0] & 0x0F) == 8:
        return ((raw[0] << 8) | raw[1]) % 31 == 0
    return False


class _CancelState:
    """Shared mutable cancel flag: survives copy.copy(NodeContext) so a
    per-node context copy still observes execution-wide cancellation."""

    __slots__ = ("cancelled",)

    def __init__(self) -> None:
        self.cancelled = False


class NodeContext:
    """Carries execution-scoped services into a node (spec 8.1, 36)."""

    def __init__(
        self,
        *,
        execution_id: str,
        workflow_id: str,
        node_id: str = "",
        logger: logging.Logger,
        http_client: httpx.AsyncClient,
        storage: MemoryKVStore | None = None,
        emit_event: Callable[..., Any] | None = None,
        credentials: dict[str, Any] | None = None,
        env_vars: dict[str, str] | None = None,
        execution_depth: int = 0,
        cancel_event: asyncio.Event | None = None,
        workspace_id: str | None = None,
        user_id: int | None = None,
    ):
        self.execution_id = execution_id
        self.workflow_id = workflow_id
        self.node_id = node_id
        self.logger = logger
        self.http_client = http_client
        self.storage = storage if storage is not None else MemoryKVStore()
        self._emit_event = emit_event or (lambda *a, **k: None)
        self._cancel_state = _CancelState()
        self.credentials: dict[str, Any] = credentials or {}
        # Workspace environment variables (Phase 31): resolved decrypted
        # values, exposed to expressions as {{ $env.KEY }}.
        self.env_vars: dict[str, str] = env_vars or {}
        # Phase 8: nesting depth for sub-workflow recursion guarding and
        # the shared cancel event so nodes that spawn child executions
        # (sub_workflow) propagate cancellation downward.
        self.execution_depth = execution_depth
        self.cancel_event = cancel_event
        # Phase 18: tenant identity for resource-scoped nodes (RAG
        # collections resolve against the run's workspace/owner).
        self.workspace_id: str | None = workspace_id
        self.user_id: int | None = user_id
        # Phase 8: the executor stores the credential resolver on the
        # context so sub-workflow nodes can propagate it to child runs.
        self._credential_resolver: Callable[[dict[str, str]], dict[str, Any]] | None = None
        # The engine-built expression context for this node (set by the
        # executor just before the node runs). Nodes with
        # resolves_own_expressions extend it per evaluation
        # (e.g. loop_while adds $iterations / fresh $json).
        self.expression_context: dict[str, Any] | None = None

    @property
    def _cancelled(self) -> bool:
        return self._cancel_state.cancelled

    @_cancelled.setter
    def _cancelled(self, value: bool) -> None:
        self._cancel_state.cancelled = value

    def is_cancelled(self) -> bool:
        """Cooperative cancellation check (spec 36)."""
        return self._cancelled

    def emit_event(self, name: str, *, node_id: str | None = None,
                   status: str | None = None, **extra: Any) -> None:
        self._emit_event(
            {"event": name, "execution_id": self.execution_id,
             "workflow_id": self.workflow_id, "node_id": node_id,
             "status": status, **extra}
        )


class EmptyParams(BaseModel):
    """Default parameters schema for nodes without parameters."""

    pass


class BaseNode(Generic[ParamsT]):
    """Every node implements this interface (spec 26).

    Subclasses parameterize the params type:

        class HTTPRequestNode(BaseNode[HTTPRequestParams]): ...
    """

    node_type: str = ""
    display_name: str = ""
    version: int = 1
    description: str = ""
    category: str = "Actions"
    icon: str = "node"
    parameters_schema: type[BaseModel] = EmptyParams
    credential_types: list[str] = []
    input_handles: list[str] = ["main"]
    output_handles: list[str] = ["main"]
    # Spec 35: whether re-running this node can duplicate external side
    # effects. One of IDEMPOTENCY_LEVELS; surfaced in the node catalog
    # (GET /api/nodes) and shown in the UI. Deterministic local nodes
    # default to "idempotent"; nodes with external or paid side effects
    # (email, LLM calls, writes) must declare otherwise.
    idempotency: str = "idempotent"
    # Phase 8: when True the executor hands the node its RAW parameters
    # and skips the one-shot pre-resolution pass, because the node
    # re-evaluates expressions itself at run time (e.g. per loop
    # iteration, where {{ $iterations }} / evolving $json only exist
    # inside the node).
    resolves_own_expressions: bool = False

    def build_params(self, raw: dict[str, Any]) -> ParamsT:
        """Validate and normalize the raw parameters dict (spec 26.3)."""
        return cast(ParamsT, self.parameters_schema.model_validate(raw))

    async def run(
        self,
        ctx: NodeContext,
        params: ParamsT,
        input_items: list[dict[str, Any]],
    ) -> NodeResult:
        raise NotImplementedError(f"Node '{self.node_type}' does not implement run().")
