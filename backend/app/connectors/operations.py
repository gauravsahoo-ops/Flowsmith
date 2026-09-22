"""Connector Operations (spec 37+).

Standardized operations that any connector can implement. The framework
defines a common interface so the API layer can invoke connector operations
without knowing the underlying implementation details.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable, cast

from app.connectors import (
    ConnectorSDK,
    ConnectorError,
    ConnectorHealthCheck,
)


class ConnectorOperations:
    """Mixin that provides default implementations of standard connector
    operations. Subclasses override as needed.

    The API layer (e.g. POST /api/connectors/{id}/execute) should call
    through this mixin rather than invoking `connector.execute()` directly,
    so that pre/post processing (auth, logging, validation) can be applied
    in one place.
    """

    status: str
    _metadata: dict[str, Any]

    # ------------------------------------------------------------------
    # Default implementations - most subclasses will override these
    # ------------------------------------------------------------------

    async def op_search(self, payload: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
        """Default search: not implemented."""
        raise ConnectorError("Search not supported by this connector", code="OP_SEARCH_UNSUPPORTED")

    async def op_get(self, payload: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
        """Default get: not implemented."""
        raise ConnectorError("Get not supported by this connector", code="OP_GET_UNSUPPORTED")

    async def op_create(self, payload: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
        """Default create: not implemented."""
        raise ConnectorError("Create not supported by this connector", code="OP_CREATE_UNSUPPORTED")

    async def op_update(self, payload: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
        """Default update: not implemented."""
        raise ConnectorError("Update not supported by this connector", code="OP_UPDATE_UNSUPPORTED")

    async def op_delete(self, payload: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
        """Default delete: not implemented."""
        raise ConnectorError("Delete not supported by this connector", code="OP_DELETE_UNSUPPORTED")

    async def op_execute(self, operation: str, payload: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
        """Default execute: not supported."""
        raise ConnectorError(
            f"Execute is not supported by this connector (operation '{operation}').",
            code="OP_EXECUTE_UNSUPPORTED",
        )

    async def op_execute_raw(self, operation: str, payload: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
        """Raw execute: direct delegate to the connector's op_execute."""
        return await self.op_execute(operation, payload, context)

    async def op_health_check(self) -> ConnectorHealthCheck:
        """Default health check: returns unhealthy if not connected."""
        if self.status != "connected":
            return ConnectorHealthCheck(
                healthy=False,
                message="Connector not connected.",
            )
        # Subclasses should override with real connectivity logic
        return ConnectorHealthCheck(healthy=True, message="Connector is operational.")

    # ------------------------------------------------------------------
    # List / describe operations
    # ------------------------------------------------------------------

    async def op_list(self, payload: dict[str, Any] | None = None, context: dict[str, Any] | None = None) -> dict[str, Any]:
        """Default list: not implemented."""
        raise ConnectorError("List not supported by this connector", code="OP_LIST_UNSUPPORTED")

    async def op_describe(self, payload: dict[str, Any] | None = None, context: dict[str, Any] | None = None) -> dict[str, Any]:
        """Default describe: not implemented."""
        raise ConnectorError("Describe not supported by this connector", code="OP_DESCRIBE_UNSUPPORTED")

    # ------------------------------------------------------------------
    # Convenience: dispatch by operation name
    # ------------------------------------------------------------------

    async def dispatch(self, operation: str, payload: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
        """Dispatch *operation* to the appropriate handler method.

        Supported operation names (convention-over-configuration):
          - "search"   -> op_search
          - "get"      -> op_get
          - "create"   -> op_create
          - "update"   -> op_update
          - "delete"   -> op_delete
          - "execute"  -> op_execute (or op_execute_raw)
          - "list"     -> op_list
          - "describe" -> op_describe
          - anything   -> op_execute (catch-all)
        """
        handler_name = f"op_{operation}" if operation else "op_execute"

        # If the handler has a specific method, use it; otherwise fall back to execute
        if hasattr(self, handler_name) and handler_name != "op_execute":
            handler = getattr(self, handler_name)
            return await handler(payload, context)

        # Fall back to the generic execute method
        return await self.op_execute(operation, payload, context)


# ----------------------------------------------------------------------
# Helper: build a ConnectorOperations instance from a ConnectorSDK
# ----------------------------------------------------------------------


def build_operations(connector: ConnectorSDK) -> ConnectorOperations:
    """Return a ConnectorOperations instance wired to *connector*.

    The returned object delegates specific operation methods to the
    connector's own `_<opname>` private methods when available, otherwise
    falls back to the default no-op implementations above.

    Example::

        class MyConnector(ConnectorSDK, ConnectorOperations):
            connector_id = "my_http"

            async def _search(self, payload, context):
                ...

            async def _execute(self, operation, payload, context):
                ...

        ops = build_operations(my_connector_instance)
    """

    class _Ops(ConnectorOperations):
        def __init__(self) -> None:
            self._connector = connector
            self._status = self._connector.status if self._connector else "initialized"
            super().__init__()

        @property
        def status(self) -> str:
            return self._status

        @status.setter
        def status(self, s: str) -> None:  # type: ignore[reportIncompatibleVariableOverride]
            self._status = s
            if self._connector:
                self._connector.status = s

        # Wire up the dispatch to use our connector's methods
        async def _dispatch_wired(self, operation: str, payload: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
            # Check connector status, not self.status
            conn_status = self._connector.status if self._connector else "initialized"
            if conn_status != "connected":
                return {"healthy": False, "message": "Connector not connected."}
            # Try to find a method on the connector matching _<operation>
            handler_name = f"_{operation}"
            if hasattr(self._connector, handler_name):
                method = getattr(self._connector, handler_name)
                if callable(method):
                    return await cast(
                        Callable[[dict[str, Any], dict[str, Any] | None], Awaitable[dict[str, Any]]],
                        method,
                    )(payload, context)
            # Fall back to op_execute
            return await self.op_execute(operation, payload, context)

        dispatch = _dispatch_wired

        # Dynamically wire _<opname> methods from the connector
        def _setup_methods(self) -> None:
            for op_name in ["search", "get", "create", "update", "delete", "execute", "list", "describe"]:
                attr_name = f"_{op_name}"
                if hasattr(self._connector, attr_name):
                    method = getattr(self._connector, attr_name)
                    if callable(method):
                        # Bind the method so it can be called as self._meth(...)
                        setattr(self, attr_name, method)

    return _Ops()
