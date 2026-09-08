"""Connector Registry tests (spec 37+): registration, discovery,
operation/trigger/credential discovery, versioning, lifecycle,
validation and duplicate-registration protection."""

from __future__ import annotations

from typing import Any

import pytest

from app.connectors import (
    ConnectorCategory,
    ConnectorDefinitionV1,
    ConnectorError,
    ConnectorErrorCode,
    ConnectorLifecycle,
    ConnectorOperationV1,
    ConnectorSDK,
    ConnectorTriggerV1,
    CredentialTypeV1,
)
from app.connectors.registry import ConnectorRegistry, validate_definition


class AcmeConnector(ConnectorSDK):
    connector_id = "acme"
    display_name = "Acme"
    description = "Test connector"
    version = "1.0.0"
    category = ConnectorCategory.API

    def __init__(self, connector_id: str | None = None, version: str | None = None) -> None:
        super().__init__(
            connector_id or self.connector_id,
            self.display_name,
            self.description,
        )
        self.version = version or self.version

    @property
    def node_types(self) -> list[str]:
        return ["acme_action"]

    async def op_execute(self, operation: str, payload: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
        return {"output": {"via": "acme"}, "success": True}


def make_defn(
    key: str = "acme",
    version: str = "1.0.0",
    lifecycle: str = ConnectorLifecycle.STABLE.value,
    operations: dict[str, ConnectorOperationV1] | None = None,
    triggers: dict[str, ConnectorTriggerV1] | None = None,
    credential_types: dict[str, CredentialTypeV1] | None = None,
    category: str = "api",
) -> ConnectorDefinitionV1:
    return ConnectorDefinitionV1(
        connector_key=key,
        display_name="Acme",
        description="Test connector",
        category=category,
        connector_version=version,
        lifecycle_status=lifecycle,
        operations=operations or {},
        triggers=triggers or {},
        credential_types=credential_types or {},
    )


def make_op(key: str = "query", *, version: str = "1.0.0", connector_version: str = "1.0.0",
            connector_key: str = "acme", credential_require: str | None = None) -> ConnectorOperationV1:
    return ConnectorOperationV1(
        connector_key=connector_key,
        connector_version=connector_version,
        operation_key=key,
        operation_version=version,
        display_name="Query",
        description="Run a query.",
        input_schema={"type": "object", "properties": {}},
        credential_require=credential_require,
    )


def make_trigger(key: str = "cron", *, version: str = "1.0.0", connector_version: str = "1.0.0",
                 connector_key: str = "acme", trigger_type: str = "scheduled") -> ConnectorTriggerV1:
    return ConnectorTriggerV1(
        connector_key=connector_key,
        connector_version=connector_version,
        trigger_key=key,
        trigger_version=version,
        trigger_type=trigger_type,
        configuration_schema={"type": "object", "properties": {}},
    )


def make_credential(key: str = "api_key") -> CredentialTypeV1:
    return CredentialTypeV1(
        type_key=key,
        display_name="API Key",
        description="API key.",
        secret_fields=["key"],
        validation_schema={"type": "object"},
        encryption_required=True,
    )


@pytest.fixture
def registry() -> ConnectorRegistry:
    reg = ConnectorRegistry()
    reg.initialize()
    return reg


def _register(reg: ConnectorRegistry, connector: ConnectorSDK | None = None, definition: ConnectorDefinitionV1 | None = None) -> ConnectorSDK:
    connector = connector or AcmeConnector()
    reg.register(connector, definition or make_defn())
    return connector


# ----------------------------------------------------------------------
# Registration + duplicate protection
# ----------------------------------------------------------------------


def test_register_and_discover(registry):
    connector = _register(registry)
    assert registry.is_initialized()
    assert registry.get("acme") is connector
    assert registry.get_definition("acme") is not None
    assert [c.connector_id for c in registry.list_all()] == ["acme"]
    assert [d.connector_key for d in registry.list_definitions()] == ["acme"]


def test_duplicate_registration_rejected(registry):
    _register(registry)
    with pytest.raises(ConnectorError) as exc:
        _register(registry, AcmeConnector())  # same key, same version
    assert exc.value.code == ConnectorErrorCode.VALIDATION_FAILED.value
    assert "already registered" in exc.value.args[0]


def test_duplicate_definition_rejected(registry):
    _register(registry)
    with pytest.raises(ConnectorError) as exc:
        registry.set_definition(make_defn())
    assert "already registered" in exc.value.args[0]


def test_failed_register_leaves_no_orphan(registry):
    """A failed registration must not leave an instance behind."""
    registry.set_definition(make_defn())  # definition registered first
    with pytest.raises(ConnectorError):
        registry.register(AcmeConnector(), make_defn())  # same key/version
    assert registry.get("acme") is None  # instance never inserted


def test_register_rejects_key_mismatch(registry):
    with pytest.raises(ConnectorError) as exc:
        registry.register(AcmeConnector(), make_defn(key="other"))
    assert "does not match" in exc.value.args[0]
    assert registry.get("acme") is None
    assert registry.get("other") is None


# ----------------------------------------------------------------------
# Discovery
# ----------------------------------------------------------------------


def test_discovery_by_node_type_category_lifecycle(registry):
    connector = _register(registry)
    assert registry.get_by_node_type("acme_action") == [connector]
    assert registry.get_by_node_type("nope") == []
    assert registry.get_by_category("api") == [connector]
    assert registry.get_by_lifecycle(ConnectorLifecycle.STABLE) == [connector]
    assert registry.get_by_lifecycle(ConnectorLifecycle.BETA) == []
    assert registry.primary_for_node_type("acme_action") is connector
    assert registry.primary_for_node_type("nope") is None


def test_operation_trigger_credential_discovery(registry):
    defn = make_defn(
        operations={"query": make_op()},
        triggers={"cron": make_trigger()},
        credential_types={"api_key": make_credential()},
    )
    _register(registry, definition=defn)

    assert registry.get_operation_definition("acme", "query").operation_key == "query"
    assert registry.get_operation_definition("acme", "nope") is None
    assert registry.get_trigger_definition("acme", "cron").trigger_type == "scheduled"
    assert registry.get_trigger_definition("acme", "nope") is None
    assert registry.get_credential_type_definition("acme", "api_key").type_key == "api_key"
    assert registry.get_credential_type_definition("acme", "nope") is None
    # Unknown connector key -> None everywhere
    assert registry.get_operation_definition("ghost", "query") is None
    assert registry.get_trigger_definition("ghost", "cron") is None
    assert registry.get_credential_type_definition("ghost", "api_key") is None


def test_definition_node_types_indexed(registry):
    defn = make_defn(operations={"query": make_op()})
    defn.operations["query"].node_types = ["acme_query"]
    _register(registry, definition=defn)
    assert registry.get_by_node_type("acme_query")  # indexed from the definition


# ----------------------------------------------------------------------
# Validation
# ----------------------------------------------------------------------


@pytest.mark.parametrize("mutate,expected", [
    (lambda d: setattr(d, "connector_key", ""), "empty connector_key"),
    (lambda d: setattr(d, "display_name", ""), "empty display_name"),
    (lambda d: setattr(d, "connector_version", "abc"), "invalid version 'abc'"),
    (lambda d: setattr(d, "connector_version", "1.0"), "invalid version '1.0'"),
    (lambda d: setattr(d, "lifecycle_status", "shipping"), "Invalid lifecycle status"),
])
def test_definition_validation_rejects_bad_metadata(registry, mutate, expected):
    defn = make_defn()
    mutate(defn)
    with pytest.raises(ConnectorError) as exc:
        validate_definition(defn)
    assert exc.value.code == ConnectorErrorCode.VALIDATION_FAILED.value
    assert expected in exc.value.args[0]


def test_definition_validation_rejects_bad_operation(registry):
    defn = make_defn(operations={"query": make_op(connector_key="other")})
    with pytest.raises(ConnectorError) as exc:
        validate_definition(defn)
    assert "belongs to connector 'other'" in exc.value.args[0]

    defn = make_defn(operations={"query": make_op(connector_version="2.0.0")})
    with pytest.raises(ConnectorError) as exc:
        validate_definition(defn)
    assert "does not match definition version" in exc.value.args[0]

    defn = make_defn(operations={"query": make_op(version="x")})
    with pytest.raises(ConnectorError) as exc:
        validate_definition(defn)
    assert "invalid version 'x'" in exc.value.args[0]

    # dict key must match operation_key
    defn = make_defn(operations={"typo": make_op()})
    with pytest.raises(ConnectorError) as exc:
        validate_definition(defn)
    assert "does not match operation_key" in exc.value.args[0]


def test_definition_validation_rejects_bad_credential_reference(registry):
    defn = make_defn(operations={"query": make_op(credential_require="oauth2")})
    with pytest.raises(ConnectorError) as exc:
        validate_definition(defn)
    assert "credential type 'oauth2'" in exc.value.args[0]


def test_definition_validation_rejects_bad_trigger(registry):
    defn = make_defn(triggers={"cron": make_trigger(trigger_type="cronjob")})
    with pytest.raises(ConnectorError) as exc:
        validate_definition(defn)
    assert "invalid trigger_type 'cronjob'" in exc.value.args[0]

    defn = make_defn(triggers={"typo": make_trigger()})
    with pytest.raises(ConnectorError) as exc:
        validate_definition(defn)
    assert "does not match trigger_key" in exc.value.args[0]


def test_definition_validation_rejects_bad_credential_type(registry):
    defn = make_defn(credential_types={"typo": make_credential()})
    with pytest.raises(ConnectorError) as exc:
        validate_definition(defn)
    assert "does not match type_key" in exc.value.args[0]


def test_definition_validation_accepts_full_definition(registry):
    defn = make_defn(
        operations={"query": make_op(credential_require="api_key")},
        triggers={"cron": make_trigger()},
        credential_types={"api_key": make_credential()},
    )
    validate_definition(defn)  # must not raise
    _register(registry, definition=defn)


# ----------------------------------------------------------------------
# Versioning
# ----------------------------------------------------------------------


def test_same_version_rejected(registry):
    _register(registry)
    with pytest.raises(ConnectorError) as exc:
        _register(registry, AcmeConnector(version="1.0.0"), make_defn(version="1.0.0"))
    assert "already registered" in exc.value.args[0]


def test_downgrade_rejected(registry):
    _register(registry, AcmeConnector(version="2.0.0"), make_defn(version="2.0.0"))
    with pytest.raises(ConnectorError) as exc:
        registry.set_definition(make_defn(version="1.5.0"))
    assert "no downgrade" in exc.value.args[0]


def test_upgrade_replaces_active_definition_and_instance(registry):
    v1 = _register(registry)
    upgrade = AcmeConnector(version="1.1.0")
    _register(registry, upgrade, make_defn(version="1.1.0"))

    assert registry.get("acme") is upgrade  # instance replaced
    active = registry.get_definition("acme")
    assert active is not None and active.connector_version == "1.1.0"
    assert registry.list_versions("acme") == ["1.0.0", "1.1.0"]
    # Old version is no longer active; versioned lookup reflects that.
    assert registry.get_definition("acme", "1.0.0") is None
    assert registry.get_definition("acme", "1.1.0").connector_version == "1.1.0"
    assert registry.get_definition("acme", "9.9.9") is None
    # Indexes follow the active definition.
    assert registry.get_by_lifecycle(ConnectorLifecycle.STABLE)


def test_version_history_per_key(registry):
    _register(registry)
    _register(registry, AcmeConnector(version="2.0.0"), make_defn(version="2.0.0"))
    _register(registry, AcmeConnector(version="3.0.0"), make_defn(version="3.0.0"))
    assert registry.list_versions("acme") == ["1.0.0", "2.0.0", "3.0.0"]
    assert registry.list_versions("ghost") == []


def test_initialize_resets_versions(registry):
    _register(registry)
    _register(registry, AcmeConnector(version="2.0.0"), make_defn(version="2.0.0"))
    registry.initialize()
    assert registry.list_all() == []
    assert registry.list_definitions() == []
    assert registry.list_versions("acme") == []
    assert registry.is_initialized()


# ----------------------------------------------------------------------
# Lifecycle
# ----------------------------------------------------------------------


def test_set_lifecycle_transition(registry):
    connector = _register(registry)
    assert connector in registry.get_by_lifecycle(ConnectorLifecycle.STABLE)
    registry.set_lifecycle("acme", ConnectorLifecycle.BETA)
    definition = registry.get_definition("acme")
    assert definition is not None
    assert definition.lifecycle_status == "beta"
    assert registry.get_by_lifecycle(ConnectorLifecycle.BETA) == [connector]
    assert registry.get_by_lifecycle(ConnectorLifecycle.STABLE) == []
    assert [c.connector_id for c in registry.list_by_lifecycle(ConnectorLifecycle.BETA)] == ["acme"]
    # String form works too; same-value transition is a no-op.
    registry.set_lifecycle("acme", "deprecated")
    assert registry.get_definition("acme").lifecycle_status == "deprecated"
    registry.set_lifecycle("acme", "deprecated")
    assert registry.get_definition("acme").lifecycle_status == "deprecated"


def test_set_lifecycle_invalid_value_rejected(registry):
    _register(registry)
    with pytest.raises(ConnectorError) as exc:
        registry.set_lifecycle("acme", "shipping")
    assert exc.value.code == ConnectorErrorCode.VALIDATION_FAILED.value
    assert registry.get_definition("acme").lifecycle_status == "stable"


def test_set_lifecycle_unknown_connector_rejected(registry):
    with pytest.raises(ConnectorError) as exc:
        registry.set_lifecycle("ghost", ConnectorLifecycle.BETA)
    assert "not registered" in exc.value.args[0]


def test_invalid_lifecycle_on_register_rejected(registry):
    with pytest.raises(ConnectorError) as exc:
        _register(registry, definition=make_defn(lifecycle="shipping"))
    assert exc.value.code == ConnectorErrorCode.VALIDATION_FAILED.value
    assert registry.get("acme") is None


# ----------------------------------------------------------------------
# Unregister + reset
# ----------------------------------------------------------------------


def test_unregister_cleans_all_indexes(registry):
    _register(registry)
    registry.set_lifecycle("acme", ConnectorLifecycle.BETA)
    registry.unregister("acme")
    assert registry.get("acme") is None
    assert registry.get_definition("acme") is None
    assert registry.list_versions("acme") == []
    assert registry.get_by_node_type("acme_action") == []
    assert registry.get_by_category("api") == []
    assert registry.get_by_lifecycle(ConnectorLifecycle.BETA) == []
    assert registry.list_all() == []
    registry.unregister("acme")  # idempotent


def test_unregister_keeps_other_connectors(registry):
    _register(registry)
    other = AcmeConnector(connector_id="other", version="1.0.0")
    _register(registry, other, make_defn(key="other", version="1.0.0"))
    registry.unregister("acme")
    assert registry.get("other") is other
    assert registry.get_by_node_type("acme_action") == [other]  # acme gone, other remains