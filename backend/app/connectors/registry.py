"""Connector Registry (spec 37+).

Manages connector registration, discovery, versioning, lifecycle and
validation. The registry is the single source of truth for all available
connectors and their current status. It supports auto-registration via
the `register` method and provides lookup by type, ID, or node type.

Versioning: one active definition per connector key. Registering the same
version again is a duplicate (rejected); registering a strictly newer
version upgrades the active definition (and replaces the connector
instance via ``register``); registering an older version is rejected.
"""

from __future__ import annotations

import asyncio
import re
import uuid
from typing import Any, Dict, List, Optional, Set

from pydantic import BaseModel

from app.connectors import (
    ConnectorSDK,
    ConnectorError,
    ConnectorHealthCheck,
    ConnectorInfo,
    ConnectorCategory,
    ConnectorStatus,
    OP_SEARCH,
    OP_GET,
    OP_CREATE,
    OP_UPDATE,
    OP_DELETE,
    OP_EXECUTE,
    OP_HEALTH_CHECK,
    ConnectorID,
    ConnectorType,
    ConnectorLifecycle,
    ConnectorDefinitionV1,
    ConnectorOperationV1,
    ConnectorTriggerV1,
    CredentialTypeV1,
    ConnectorErrorCode,
    make_connector_error,
)

_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
_VALID_TRIGGER_TYPES = frozenset({"webhook", "scheduled", "polling"})


def _version_tuple(version: str) -> tuple[int, int, int]:
    """Parse a validated MAJOR.MINOR.PATCH version into an int tuple."""
    return tuple(int(part) for part in version.split("."))  # type: ignore[return-value]


def _require_valid_version(version: str, what: str) -> None:
    """Raise ConnectorError unless *version* is MAJOR.MINOR.PATCH."""
    if not _VERSION_RE.match(version or ""):
        raise ConnectorError(
            f"{what} has invalid version '{version}'; expected MAJOR.MINOR.PATCH (e.g. 1.0.0).",
            code=ConnectorErrorCode.VALIDATION_FAILED,
        )


def validate_definition(definition: ConnectorDefinitionV1) -> None:
    """Validate a connector definition before it enters the registry.

    Checks required metadata, MAJOR.MINOR.PATCH versions, key consistency
    between dict keys and the payload models, that operations/triggers
    belong to the same connector/version, and that credential_require
    references a declared credential type. Raises ConnectorError with
    code CONNECTOR_VALIDATION_FAILED on the first problem.
    """
    if not definition.connector_key:
        raise ConnectorError(
            "Connector definition has an empty connector_key.",
            code=ConnectorErrorCode.VALIDATION_FAILED,
        )
    if not definition.display_name:
        raise ConnectorError(
            f"Connector '{definition.connector_key}' has an empty display_name.",
            code=ConnectorErrorCode.VALIDATION_FAILED,
        )
    _require_valid_version(definition.connector_version, f"Connector '{definition.connector_key}'")

    try:
        ConnectorLifecycle(definition.lifecycle_status.lower())
    except ValueError:
        raise ConnectorError(
            f"Invalid lifecycle status '{definition.lifecycle_status}'. Must be one of: "
            f"{', '.join(l.value for l in ConnectorLifecycle)}.",
            code=ConnectorErrorCode.VALIDATION_FAILED,
        )

    for op_key, op in definition.operations.items():
        if op_key != op.operation_key:
            raise ConnectorError(
                f"Operation dict key '{op_key}' does not match operation_key '{op.operation_key}' "
                f"on connector '{definition.connector_key}'.",
                code=ConnectorErrorCode.VALIDATION_FAILED,
            )
        if op.connector_key != definition.connector_key:
            raise ConnectorError(
                f"Operation '{op_key}' belongs to connector '{op.connector_key}', "
                f"not '{definition.connector_key}'.",
                code=ConnectorErrorCode.VALIDATION_FAILED,
            )
        if op.connector_version != definition.connector_version:
            raise ConnectorError(
                f"Operation '{op_key}' connector_version '{op.connector_version}' does not match "
                f"definition version '{definition.connector_version}'.",
                code=ConnectorErrorCode.VALIDATION_FAILED,
            )
        _require_valid_version(op.operation_version, f"Operation '{op_key}'")
        if op.credential_require and op.credential_require not in definition.credential_types:
            raise ConnectorError(
                f"Operation '{op_key}' requires credential type '{op.credential_require}' "
                f"which is not declared by connector '{definition.connector_key}'.",
                code=ConnectorErrorCode.VALIDATION_FAILED,
            )

    for trigger_key, trigger in definition.triggers.items():
        if trigger_key != trigger.trigger_key:
            raise ConnectorError(
                f"Trigger dict key '{trigger_key}' does not match trigger_key '{trigger.trigger_key}' "
                f"on connector '{definition.connector_key}'.",
                code=ConnectorErrorCode.VALIDATION_FAILED,
            )
        if trigger.connector_key != definition.connector_key:
            raise ConnectorError(
                f"Trigger '{trigger_key}' belongs to connector '{trigger.connector_key}', "
                f"not '{definition.connector_key}'.",
                code=ConnectorErrorCode.VALIDATION_FAILED,
            )
        if trigger.connector_version != definition.connector_version:
            raise ConnectorError(
                f"Trigger '{trigger_key}' connector_version '{trigger.connector_version}' does not match "
                f"definition version '{definition.connector_version}'.",
                code=ConnectorErrorCode.VALIDATION_FAILED,
            )
        _require_valid_version(trigger.trigger_version, f"Trigger '{trigger_key}'")
        if trigger.trigger_type not in _VALID_TRIGGER_TYPES:
            raise ConnectorError(
                f"Trigger '{trigger_key}' has invalid trigger_type '{trigger.trigger_type}'. "
                f"Must be one of: {', '.join(sorted(_VALID_TRIGGER_TYPES))}.",
                code=ConnectorErrorCode.VALIDATION_FAILED,
            )
        if trigger.credential_require and trigger.credential_require not in definition.credential_types:
            raise ConnectorError(
                f"Trigger '{trigger_key}' requires credential type '{trigger.credential_require}' "
                f"which is not declared by connector '{definition.connector_key}'.",
                code=ConnectorErrorCode.VALIDATION_FAILED,
            )

    for ct_key, cred in definition.credential_types.items():
        if ct_key != cred.type_key:
            raise ConnectorError(
                f"Credential type dict key '{ct_key}' does not match type_key '{cred.type_key}' "
                f"on connector '{definition.connector_key}'.",
                code=ConnectorErrorCode.VALIDATION_FAILED,
            )


class ConnectorMap(Dict[str, ConnectorSDK]):
    """connector_id -> ConnectorSDK"""


NodeTypeIndex = Dict[str, Set[str]]  # node_type -> set of connector ids


class ConnectorRegistry:
    """Singleton registry managing all connector instances."""

    def __init__(self) -> None:
        self._connectors: ConnectorMap = ConnectorMap()  # connector_id -> ConnectorSDK
        self._by_node_type: NodeTypeIndex = {}  # node_type -> set of connector ids
        self._by_category: Dict[str, Set[str]] = {}  # category -> set of connector ids
        self._by_lifecycle: Dict[str, Set[str]] = (  # lifecycle -> set of connector ids
            {}
        )
        self._definitions: Dict[str, ConnectorDefinitionV1] = (
            {}
        )  # connector_key -> active ConnectorDefinitionV1
        self._versions: Dict[str, List[str]] = {}  # connector_key -> registered versions (ascending)
        self._initialized: bool = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def initialize(self) -> None:
        """Reset the registry (called on app startup)."""
        self._connectors.clear()
        self._by_node_type.clear()
        self._by_category.clear()
        self._by_lifecycle.clear()
        self._definitions.clear()
        self._versions.clear()
        self._initialized = True

    def is_initialized(self) -> bool:
        return self._initialized

    # ------------------------------------------------------------------
    # Index maintenance
    # ------------------------------------------------------------------

    def _index_definition(self, definition: ConnectorDefinitionV1) -> None:
        """Add a definition to the lifecycle/category/node-type indexes."""
        cid = definition.connector_key
        ls = definition.lifecycle_status.lower()
        self._by_lifecycle.setdefault(ls, set()).add(cid)
        self._by_category.setdefault(definition.category, set()).add(cid)
        for op in definition.operations.values():
            for nt in getattr(op, "node_types", []) or []:
                self._by_node_type.setdefault(nt, set()).add(cid)
        for trig in definition.triggers.values():
            for nt in getattr(trig, "node_types", []) or []:
                self._by_node_type.setdefault(nt, set()).add(cid)

    def _unindex_definition(self, definition: ConnectorDefinitionV1) -> None:
        """Remove a definition from the lifecycle/category/node-type indexes."""
        cid = definition.connector_key
        ls = definition.lifecycle_status.lower()
        if ls in self._by_lifecycle:
            self._by_lifecycle[ls].discard(cid)
            if not self._by_lifecycle[ls]:
                del self._by_lifecycle[ls]
        if definition.category in self._by_category:
            self._by_category[definition.category].discard(cid)
            if not self._by_category[definition.category]:
                del self._by_category[definition.category]
        for op in definition.operations.values():
            for nt in getattr(op, "node_types", []) or []:
                self._by_node_type[nt].discard(cid)
                if not self._by_node_type[nt]:
                    del self._by_node_type[nt]
        for trig in definition.triggers.values():
            for nt in getattr(trig, "node_types", []) or []:
                self._by_node_type[nt].discard(cid)
                if not self._by_node_type[nt]:
                    del self._by_node_type[nt]

    # ------------------------------------------------------------------
    # Definition management
    # ------------------------------------------------------------------

    def set_definition(self, definition: ConnectorDefinitionV1) -> None:
        """Store a connector definition in the registry.

        Validates the definition on register; raises ConnectorError
        if the definition is invalid, if the same version is already
        registered (duplicate), or if an older version is registered
        (downgrades are not allowed). A strictly newer version upgrades
        the active definition.
        """
        validate_definition(definition)
        cid = definition.connector_key

        active = self._definitions.get(cid)
        if active is not None:
            new_v = definition.connector_version
            active_v = active.connector_version
            if _version_tuple(new_v) == _version_tuple(active_v):
                raise ConnectorError(
                    f"Connector definition '{cid}' version {new_v} is already registered.",
                    code=ConnectorErrorCode.VALIDATION_FAILED,
                )
            if _version_tuple(new_v) < _version_tuple(active_v):
                raise ConnectorError(
                    f"Cannot register connector '{cid}' version {new_v}: "
                    f"active version {active_v} is newer (no downgrade).",
                    code=ConnectorErrorCode.VALIDATION_FAILED,
                )
            # Upgrade: swap indexes before replacing the active definition.
            self._unindex_definition(active)

        self._definitions[cid] = definition
        self._versions.setdefault(cid, []).append(definition.connector_version)
        self._index_definition(definition)

    def get_definition(self, connector_key: str, version: str | None = None) -> Optional[ConnectorDefinitionV1]:
        """Retrieve a connector definition by key.

        Without *version* the active (latest) definition is returned;
        with *version* the definition is returned only if it is the
        active version (older registered versions are not active).
        """
        definition = self._definitions.get(connector_key)
        if definition is None or version is None:
            return definition
        return definition if definition.connector_version == version else None

    def list_definitions(self) -> List[ConnectorDefinitionV1]:
        """Return all active connector definitions."""
        return list(self._definitions.values())

    def list_versions(self, connector_key: str) -> List[str]:
        """Return the registration history of *connector_key* (ascending)."""
        return list(self._versions.get(connector_key, []))

    # ------------------------------------------------------------------
    # Registration / Auto-registration
    # ------------------------------------------------------------------

    def register(self, connector: ConnectorSDK, definition: ConnectorDefinitionV1) -> None:
        """Register a connector instance and its definition in the registry.

        Prevents duplicate registration: the same connector key/version
        cannot be registered twice, and an older version cannot replace
        a newer one. A strictly newer version is an upgrade: the active
        definition and the connector instance are both replaced.

        The definition is validated and stored *before* the instance is
        inserted, so a failed registration never leaves an orphaned
        connector instance behind.
        """
        cid = connector.connector_id
        if definition.connector_key != cid:
            raise ConnectorError(
                f"Definition connector_key '{definition.connector_key}' does not match "
                f"connector_id '{cid}'.",
                code=ConnectorErrorCode.VALIDATION_FAILED,
            )

        active = self._definitions.get(cid)
        if cid in self._connectors:
            # Duplicate instance guard; a strictly-newer version is an
            # upgrade (replaces the instance), anything else is a duplicate.
            if active is None or _version_tuple(definition.connector_version) <= _version_tuple(
                active.connector_version
            ):
                raise ConnectorError(
                    f"Connector '{cid}' is already registered.",
                    code=ConnectorErrorCode.VALIDATION_FAILED,
                )
            # Unindex the outgoing instance's node types before replacing it.
            old_instance = self._connectors[cid]
            for nt in old_instance.node_types:
                self._by_node_type[nt].discard(cid)
                if not self._by_node_type[nt]:
                    del self._by_node_type[nt]

        # Definition first (validates + raises before any mutation of the
        # connector map), then the instance.
        self.set_definition(definition)
        self._connectors[cid] = connector

        # Index the instance's node types
        for nt in connector.node_types:
            self._by_node_type.setdefault(nt, set()).add(cid)

        # Index by category
        cat = definition.category
        self._by_category.setdefault(cat, set()).add(cid)

        # Index by lifecycle
        lifecycle = ConnectorLifecycle(definition.lifecycle_status.lower())
        self._by_lifecycle.setdefault(lifecycle.value, set()).add(cid)

    def unregister(self, connector_id: ConnectorID) -> None:
        """Remove a connector from the registry."""
        connector = self._connectors.pop(connector_id, None)
        if connector is None:
            return

        # Remove from node type index
        for nt in connector.node_types:
            if nt in self._by_node_type:
                self._by_node_type[nt].discard(connector_id)
                if not self._by_node_type[nt]:
                    del self._by_node_type[nt]

        # Remove from category index
        definition = self._definitions.get(connector_id)
        if definition is not None:
            cat = definition.category
            if cat in self._by_category:
                self._by_category[cat].discard(connector_id)
                if not self._by_category[cat]:
                    del self._by_category[cat]

            # Remove from lifecycle index
            ls = definition.lifecycle_status.lower()
            if ls in self._by_lifecycle:
                self._by_lifecycle[ls].discard(connector_id)
                if not self._by_lifecycle[ls]:
                    del self._by_lifecycle[ls]

            # Remove definition + version history
            self._definitions.pop(connector_id, None)
            self._versions.pop(connector_id, None)

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------

    def get(self, connector_id: ConnectorID) -> Optional[ConnectorSDK]:
        return self._connectors.get(connector_id)

    def get_by_node_type(self, node_type: str) -> List[ConnectorSDK]:
        """Return all connectors that claim to support *node_type*."""
        cids = self._by_node_type.get(node_type) or ()
        return [self._connectors[cid] for cid in cids if cid in self._connectors]

    def get_by_category(self, category: str) -> List[ConnectorSDK]:
        """Return all connectors in *category*."""
        cids = self._by_category.get(category, [])
        return [self._connectors[cid] for cid in cids if cid in self._connectors]

    def get_by_lifecycle(self, lifecycle: ConnectorLifecycle) -> List[ConnectorSDK]:
        """Return all connectors with the given lifecycle status."""
        cids = self._by_lifecycle.get(lifecycle.value, set())
        return [self._connectors[cid] for cid in cids if cid in self._connectors]

    def list_all(self) -> List[ConnectorInfo]:
        """Return connector info for all registered connectors."""
        return [
            ConnectorInfo(
                connector_id=cid,
                name=conn.name,
                description=conn.description,
                version=conn.version,
                category=conn.category.value if isinstance(conn.category, ConnectorCategory) else conn.category,
                status=conn.status,
                node_types=conn.node_types,
                metadata=conn._metadata,
            )
            for cid, conn in self._connectors.items()
        ]

    def list_by_lifecycle(self, lifecycle: ConnectorLifecycle) -> List[ConnectorInfo]:
        """Return connectors filtered by lifecycle status."""
        cids = self._by_lifecycle.get(lifecycle.value, set())
        result: List[ConnectorInfo] = []
        for cid in cids:
            if cid in self._connectors:
                conn = self._connectors[cid]
                result.append(
                    ConnectorInfo(
                        connector_id=cid,
                        name=conn.name,
                        description=conn.description,
                        version=conn.version,
                        category=conn.category.value if isinstance(conn.category, ConnectorCategory) else conn.category,
                        status=conn.status,
                        node_types=conn.node_types,
                        metadata=conn._metadata,
                    )
                )
        return result

    # ------------------------------------------------------------------
    # Lifecycle transitions
    # ------------------------------------------------------------------

    def set_lifecycle(self, connector_key: str, lifecycle: ConnectorLifecycle | str) -> None:
        """Transition the active definition of *connector_key* to a new
        lifecycle status and reindex it (spec 30)."""
        try:
            new_ls = lifecycle if isinstance(lifecycle, ConnectorLifecycle) else ConnectorLifecycle(lifecycle)
        except ValueError:
            raise ConnectorError(
                f"Invalid lifecycle status '{lifecycle}'. Must be one of: "
                f"{', '.join(l.value for l in ConnectorLifecycle)}.",
                code=ConnectorErrorCode.VALIDATION_FAILED,
            )
        definition = self._definitions.get(connector_key)
        if definition is None:
            raise ConnectorError(
                f"Connector '{connector_key}' is not registered.",
                code=ConnectorErrorCode.VALIDATION_FAILED,
            )
        old_ls = definition.lifecycle_status.lower()
        if old_ls == new_ls.value:
            return
        definition.lifecycle_status = new_ls.value
        if old_ls in self._by_lifecycle:
            self._by_lifecycle[old_ls].discard(connector_key)
            if not self._by_lifecycle[old_ls]:
                del self._by_lifecycle[old_ls]
        self._by_lifecycle.setdefault(new_ls.value, set()).add(connector_key)

    # ------------------------------------------------------------------
    # Convenience: find primary connector for a node type
    # ------------------------------------------------------------------

    def primary_for_node_type(self, node_type: str) -> Optional[ConnectorSDK]:
        """Return the first connector registered for *node_type*, or None."""
        for conn in self.get_by_node_type(node_type):
            return conn
        return None

    # ------------------------------------------------------------------
    # Connector definition lookup via API methods
    # ------------------------------------------------------------------

    def get_operation_definition(
        self, connector_key: str, operation_key: str
    ) -> Optional[ConnectorOperationV1]:
        """Look up an operation definition for a given connector."""
        definition = self._definitions.get(connector_key)
        if definition is None:
            return None
        return definition.operations.get(operation_key)

    def get_trigger_definition(
        self, connector_key: str, trigger_key: str
    ) -> Optional[ConnectorTriggerV1]:
        """Look up a trigger definition for a given connector."""
        definition = self._definitions.get(connector_key)
        if definition is None:
            return None
        return definition.triggers.get(trigger_key)

    def get_credential_type_definition(
        self, connector_key: str, cred_type: str
    ) -> Optional[CredentialTypeV1]:
        """Look up a credential type definition for a given connector."""
        definition = self._definitions.get(connector_key)
        if definition is None:
            return None
        return definition.credential_types.get(cred_type)

    # ------------------------------------------------------------------
    # Health check batch
    # ------------------------------------------------------------------

    async def check_all_health(self) -> Dict[str, ConnectorHealthCheck]:
        """Run health_check on every connector and return {id: result}."""
        results: Dict[str, ConnectorHealthCheck] = {}
        for cid, conn in self._connectors.items():
            try:
                results[cid] = await conn.op_health_check()
            except Exception as exc:
                results[cid] = ConnectorHealthCheck(
                    healthy=False,
                    message=f"Health check failed: {exc}",
                )
        return results

    async def list_healthy_async(self) -> List[ConnectorInfo]:
        """Async version - return info for connectors that are currently healthy/connected."""
        result: List[ConnectorInfo] = []
        for cid, conn in self._connectors.items():
            try:
                hc = await conn.op_health_check()
                if hc and hc.healthy:
                    result.append(
                        ConnectorInfo(
                            connector_id=cid,
                            name=conn.name,
                            description=conn.description,
                            version=conn.version,
                            category=conn.category.value if isinstance(conn.category, ConnectorCategory) else conn.category,
                            status=conn.status,
                            node_types=conn.node_types,
                            metadata=conn._metadata,
                        )
                    )
            except Exception:
                pass
        return result

    def list_healthy(self) -> List[ConnectorInfo]:
        """Synchronous wrapper - returns info for connectors that appear healthy.

        Uses a synchronous health check (no network I/O) — connectors
        with status 'connected' are considered healthy."""
        result: List[ConnectorInfo] = []
        for cid, conn in self._connectors.items():
            if conn.status == "connected":
                result.append(
                    ConnectorInfo(
                        connector_id=cid,
                        name=conn.name,
                        description=conn.description,
                        version=conn.version,
                        category=conn.category.value if isinstance(conn.category, ConnectorCategory) else conn.category,
                        status=conn.status,
                        node_types=conn.node_types,
                        metadata=conn._metadata,
                    )
                )
        return result