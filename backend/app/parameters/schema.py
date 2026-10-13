"""FlowSmith Parameter Configuration Framework.

Schema models and utilities used to build dynamic, schema-driven parameter
forms for **every** node in the platform. The framework is the single source of
truth shared by the backend catalog API and the frontend configuration panel:

    Pydantic / JSON Schema  ──►  ParameterSchemaBuilder  ──►  ParameterField[]
                                                                      │
                                                  GET /api/nodes/{type} │
                                                                      ▼
                                        DynamicNodeConfigPanel (React)

A ``ParameterField`` carries everything the UI needs to render one control:

* rendering hints — ``type``, ``options``, ``placeholder``, ``group``, ``advanced``
* conditional visibility — ``show_if`` rules evaluated against the current form state
* validation — ``required``, ``minimum``/``maximum``, ``pattern``, ``min_length``
* guidance — ``title``, ``description``, ``default``
* expectations — ``output_preview`` describing the shape the operation returns

Design rules
------------
1. **No invented data.** Everything emitted here is derived from the schema that
   the node/connector itself declares. The framework never fabricates defaults,
   fields, or output shapes.
2. **Operation-aware.** When a node declares which properties each operation
   consumes, fields become conditionally visible for the selected operation, and
   per-operation required markers are emitted.
3. **Backwards compatible.** Fields are additive; existing consumers that read
   ``parameters_schema`` continue to work unchanged.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

# Fields that belong in the "advanced" accordion rather than the main form.
ADVANCED_KEYS = frozenset(
    {
        "timeout_seconds",
        "retry_max_attempts",
        "retry_backoff_seconds",
        "continue_on_error",
        "max_pages",
        "page_size",
        "max_results",
        "return_all",
        "poll_interval_seconds",
        "max_polls",
        "_advanced_overrides",
    }
)

# Fields that act as the node's primary "what should I do" selector. They are
# rendered as a dedicated bar above the form rather than as ordinary inputs.
GROUP_ANCHORS = frozenset({"operation", "resource", "entity", "object_type"})

# JSON Schema types we know how to render, mapped to panel control kinds.
_TYPE_MAP = {
    "string": "string",
    "number": "number",
    "integer": "number",
    "boolean": "boolean",
    "object": "json",
    "array": "list",
}


class ParameterField(BaseModel):
    """Specification of one input parameter field in the node configuration panel."""

    name: str = Field(description="Unique parameter key/name in payload.")
    title: str = Field(description="User-facing label.")
    type: str = Field(
        default="string",
        description="Control kind: string, number, boolean, select, json, list, key_value, expression.",
    )
    default: Any = Field(default=None, description="Default value if not specified.")
    description: str = Field(default="", description="Field tooltip / help text.")
    placeholder: str = Field(default="", description="Input placeholder text.")
    required: bool = Field(default=False, description="Whether this parameter is strictly required.")
    enum: Optional[List[Any]] = Field(default=None, description="Allowed values for select dropdown.")
    options: Optional[List[Dict[str, Any]]] = Field(
        default=None,
        description="Label/value options for a select dropdown: [{'label':..,'value':..}].",
    )
    show_if: Optional[Dict[str, Any]] = Field(
        default=None,
        description=(
            "Conditional visibility rule evaluated against form state. "
            "Either {'operation': ['op1','op2']} (operation membership, possibly "
            "negated with an '!' prefix) or {'field': {'equals': value}}."
        ),
    )
    group: str = Field(default="main", description="Field section group: main, parameters, options, advanced.")
    advanced: bool = Field(default=False, description="Whether this field belongs in the advanced accordion.")

    # -- validation -------------------------------------------------------
    minimum: Optional[float] = Field(default=None, description="Inclusive lower bound (numeric).")
    maximum: Optional[float] = Field(default=None, description="Inclusive upper bound (numeric).")
    min_length: Optional[int] = Field(default=None, description="Minimum string length.")
    max_length: Optional[int] = Field(default=None, description="Maximum string length.")
    pattern: Optional[str] = Field(default=None, description="Regular expression the value must match.")
    min_items: Optional[int] = Field(default=None, description="Minimum array length.")
    format: Optional[str] = Field(default=None, description="Semantic format hint, e.g. 'password'.")


class OperationSpec(BaseModel):
    """How a single operation influences the configuration form."""

    key: str = Field(description="Operation key as registered on the connector.")
    display_name: str = Field(default="", description="Human-readable operation label.")
    description: str = Field(default="", description="One-line explanation shown under the operation picker.")
    idempotency: str = Field(default="", description="idempotent | conditionally_idempotent | non_idempotent")
    retryable: bool = Field(default=False, description="Whether the operation is safe to auto-retry.")
    properties: List[str] = Field(default_factory=list, description="Properties this operation consumes.")
    required: List[str] = Field(default_factory=list, description="Properties this operation requires.")
    output_preview: Optional[Dict[str, Any]] = Field(
        default=None,
        description="JSON Schema describing the shape this operation returns.",
    )


class ParameterSchemaBuilder:
    """Builds and enriches node parameter schemas for configuration UI rendering."""

    # ------------------------------------------------------------------ #
    # public API
    # ------------------------------------------------------------------ #

    @classmethod
    def extract_from_json_schema(
        cls,
        raw_schema: Dict[str, Any],
        operations_meta: Optional[Dict[str, Dict[str, Any]]] = None,
        selector: Optional[str] = None,
    ) -> List[ParameterField]:
        """Convert a JSON schema into enriched ``ParameterField`` models.

        ``operations_meta`` is the per-operation metadata produced by
        ``app.api.nodes`` (properties, required, description, idempotency,
        retryable, output schema). When supplied, fields gain operation-scoped
        visibility rules and per-operation required markers.

        ``selector`` names the property that chooses between operations. It
        defaults to ``operation``; nodes that gate on a differently-named enum
        (``mode`` on rename_keys, ``resource`` on others) pass it explicitly so
        that field is treated as the group anchor rather than as one more input.
        """
        if not isinstance(raw_schema, dict):
            return []

        properties = raw_schema.get("properties") or {}
        if not isinstance(properties, dict):
            return []

        schema_required = set(raw_schema.get("required") or [])
        operations_meta = operations_meta or {}

        prop_operations = cls._index_property_operations(operations_meta)
        # The selector is never itself gated by an operation rule: it is the
        # control the user changes to pick one.
        selector = selector or "operation"
        prop_operations.pop(selector, None)
        conditional_rules = cls._extract_schema_conditionals(raw_schema)
        conditional_rules.pop(selector, None)

        fields: List[ParameterField] = []
        for prop_name, prop_data in properties.items():
            if not isinstance(prop_data, dict):
                continue

            fields.append(
                cls._build_field(
                    prop_name=prop_name,
                    prop_data=prop_data,
                    prop_operations=prop_operations,
                    conditional_rules=conditional_rules,
                    schema_required=schema_required,
                    operations_meta=operations_meta,
                    selector=selector,
                )
            )
        return fields

    @classmethod
    def build_operations(cls, operations_meta: Dict[str, Dict[str, Any]]) -> Dict[str, OperationSpec]:
        """Normalise raw operation metadata into ``OperationSpec`` models."""
        specs: Dict[str, OperationSpec] = {}
        for key, meta in (operations_meta or {}).items():
            if not isinstance(meta, dict):
                continue
            specs[key] = OperationSpec(
                key=key,
                display_name=meta.get("display_name") or key.replace("_", " ").title(),
                description=meta.get("description") or "",
                idempotency=meta.get("idempotency") or "",
                retryable=bool(meta.get("retryable")),
                properties=list(meta.get("properties") or []),
                required=list(meta.get("required") or []),
                output_preview=meta.get("output_preview") or meta.get("output_schema"),
            )
        return specs

    @classmethod
    def output_preview_for(
        cls,
        operations_meta: Optional[Dict[str, Dict[str, Any]]],
        operation: Optional[str],
    ) -> Optional[Dict[str, Any]]:
        """Return the declared output schema for ``operation``, if any."""
        if not operations_meta or not operation:
            return None
        meta = operations_meta.get(operation) or {}
        return meta.get("output_preview") or meta.get("output_schema")

    # ------------------------------------------------------------------ #
    # internals
    # ------------------------------------------------------------------ #

    @staticmethod
    def _index_property_operations(operations_meta: Dict[str, Dict[str, Any]]) -> Dict[str, List[str]]:
        """Reverse index: property name -> list of operations that consume it."""
        prop_operations: Dict[str, List[str]] = {}
        for op_key, op_info in operations_meta.items():
            if not isinstance(op_info, dict):
                continue
            for prop_name in op_info.get("properties") or []:
                prop_operations.setdefault(prop_name, []).append(op_key)
        return prop_operations

    @staticmethod
    def _extract_schema_conditionals(raw_schema: Dict[str, Any]) -> Dict[str, Any]:
        """Read JSON Schema conditional clauses into show_if rules.

        Supports both spellings — a top-level ``if``/``then`` pair and the
        equivalent ``allOf: [{if, then}]`` form::

            {"if": {"properties": {"mode": {"const": "advanced"}},
                    "required": ["mode"]},
             "then": {"required": ["api_url"]}}

        which becomes ``show_if = {"mode": ["advanced"]}`` on ``api_url``.

        Only single-condition rules using ``const``/``enum`` are mapped, so an
        unrecognised conditional is ignored rather than mis-rendered.
        """
        rules: Dict[str, Any] = {}

        clauses: List[Any] = []
        if isinstance(raw_schema.get("allOf"), list):
            clauses.extend(raw_schema["allOf"])
        # Top-level if/then is shorthand for a single allOf clause.
        if isinstance(raw_schema.get("if"), dict) and isinstance(raw_schema.get("then"), dict):
            clauses.append({"if": raw_schema["if"], "then": raw_schema["then"]})

        for clause in clauses:
            if not isinstance(clause, dict):
                continue
            if_clause = clause.get("if")
            then_clause = clause.get("then")
            if not isinstance(if_clause, dict) or not isinstance(then_clause, dict):
                continue

            props = if_clause.get("properties") or {}
            if not isinstance(props, dict) or len(props) != 1:
                # Only single-condition rules are mapped to the simple show_if form.
                continue
            ((condition_field, condition_schema),) = props.items()
            if not isinstance(condition_schema, dict):
                continue

            if "const" in condition_schema:
                allowed: List[Any] = [condition_schema["const"]]
            elif isinstance(condition_schema.get("enum"), list):
                allowed = list(condition_schema["enum"])
            else:
                continue

            rule = {condition_field: allowed}
            then_props = then_clause.get("properties") or {}
            targets = list(then_clause.get("required") or [])
            if isinstance(then_props, dict):
                targets.extend(then_props.keys())

            for target in dict.fromkeys(targets):
                rules.setdefault(target, rule)
        return rules

    @classmethod
    def _build_field(
        cls,
        *,
        prop_name: str,
        prop_data: Dict[str, Any],
        prop_operations: Dict[str, List[str]],
        conditional_rules: Dict[str, Any],
        schema_required: set[str],
        operations_meta: Dict[str, Dict[str, Any]],
        selector: str = "operation",
    ) -> ParameterField:
        raw_type = prop_data.get("type", "string")
        # ``type`` may be a list, e.g. ["string", "null"] — take the first real one.
        if isinstance(raw_type, list):
            raw_type = next((t for t in raw_type if t != "null"), "string")

        enum_values = prop_data.get("enum") if isinstance(prop_data.get("enum"), list) else None
        control_type = "select" if enum_values else _TYPE_MAP.get(raw_type, "string")

        options = None
        if enum_values:
            options = cls._build_options(enum_values, prop_data.get("options"))

        show_if = cls._build_show_if(
            prop_name, prop_operations, conditional_rules, operations_meta, selector
        )

        is_advanced = (
            prop_name in ADVANCED_KEYS or bool(prop_data.get("advanced")) or (prop_data.get("x-group") == "advanced")
        )

        group = str(prop_data.get("x-group") or "")
        if not group:
            if is_advanced:
                group = "advanced"
            elif prop_name in GROUP_ANCHORS or prop_name == selector:
                group = "main"
            else:
                group = "parameters"

        # Per-operation required: required only if EVERY operation consuming the
        # field lists it as required. Otherwise the mark would flicker on switch.
        required = cls._resolve_required(prop_name, schema_required, prop_operations, operations_meta)

        return ParameterField(
            name=prop_name,
            title=prop_data.get("title") or prop_name.replace("_", " ").title(),
            type=control_type,
            default=prop_data.get("default"),
            description=prop_data.get("description") or "",
            placeholder=prop_data.get("placeholder") or "",
            required=required,
            enum=enum_values,
            options=options,
            show_if=show_if,
            group=group,
            advanced=is_advanced,
            minimum=cls._as_number(prop_data.get("minimum")),
            maximum=cls._as_number(prop_data.get("maximum")),
            min_length=cls._as_int(prop_data.get("minLength")),
            max_length=cls._as_int(prop_data.get("maxLength")),
            pattern=prop_data.get("pattern") if isinstance(prop_data.get("pattern"), str) else None,
            min_items=cls._as_int(prop_data.get("minItems")),
            format=prop_data.get("format") if isinstance(prop_data.get("format"), str) else None,
        )

    @staticmethod
    def _build_options(enum_values: List[Any], declared: Any) -> List[Dict[str, Any]]:
        """Build label/value pairs, honouring ``x-enum-labels`` when present."""
        labels: Dict[str, str] = {}
        if isinstance(declared, dict):
            for k, v in declared.items():
                labels[str(k)] = str(v)
        elif isinstance(declared, list):
            # [{"value":..,"label":..}] form
            for item in declared:
                if isinstance(item, dict) and "value" in item:
                    labels[str(item["value"])] = str(item.get("label", item["value"]))

        options: List[Dict[str, Any]] = []
        for value in enum_values:
            key = str(value)
            options.append({"label": labels.get(key, key.replace("_", " ").title()), "value": value})
        return options

    @staticmethod
    def _build_show_if(
        prop_name: str,
        prop_operations: Dict[str, List[str]],
        conditional_rules: Dict[str, Any],
        operations_meta: Dict[str, Dict[str, Any]],
        selector: str = "operation",
    ) -> Optional[Dict[str, Any]]:
        # 1. Explicit JSON Schema if/then conditional wins.
        if prop_name in conditional_rules:
            return conditional_rules[prop_name]

        # 2. Operation membership: show only for ops that consume this field.
        ops = prop_operations.get(prop_name)
        if not ops:
            # A field consumed by no operation at all is operation-independent.
            return None
        known = set(operations_meta)
        if known and set(ops) == known:
            return None  # every operation uses it — no need to toggle
        # Negation keeps the rule stable as operations are added: show unless the
        # current operation is one that explicitly excludes the field.
        excluded = sorted(known - set(ops))
        if excluded and len(ops) >= len(known) / 2:
            return {selector: [f"!{o}" for o in excluded]}
        return {selector: sorted(ops)}

    @staticmethod
    def _resolve_required(
        prop_name: str,
        schema_required: set[str],
        prop_operations: Dict[str, List[str]],
        operations_meta: Dict[str, Dict[str, Any]],
    ) -> bool:
        ops_using = prop_operations.get(prop_name)
        if not ops_using:
            return prop_name in schema_required

        consuming_required = 0
        for op in ops_using:
            meta = operations_meta.get(op) or {}
            req = meta.get("required")
            if req is None:
                # No per-op data: fall back to the schema-level declaration.
                consuming_required += 1 if prop_name in schema_required else 0
            elif prop_name in req:
                consuming_required += 1

        if consuming_required == 0:
            return False
        if consuming_required == len(ops_using):
            return True
        # Required by some but not all operations -> conditionally required.
        return False

    @staticmethod
    def _as_number(value: Any) -> Optional[float]:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return float(value)

    @staticmethod
    def _as_int(value: Any) -> Optional[int]:
        if isinstance(value, bool) or not isinstance(value, int):
            return None
        return value
