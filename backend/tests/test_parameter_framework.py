"""Unit tests for the FlowSmith Parameter Configuration Framework.

Covers ``ParameterSchemaBuilder`` / ``ParameterField`` — the shared contract
between the backend catalog API and the frontend configuration panel:

* type mapping and option labels
* conditional visibility (operation membership, JSON Schema ``if/then``)
* required-field resolution (schema-level and per-operation)
* grouping / advanced classification
* validation metadata extraction
* operation specs incl. output previews
"""

from __future__ import annotations

from app.parameters import ParameterField, ParameterSchemaBuilder


BUILDER = ParameterSchemaBuilder


def _field(fields, name):
    return next(f for f in fields if f.name == name)


class TestTypeMapping:
    def test_maps_json_schema_types_to_control_kinds(self):
        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "count": {"type": "integer"},
                "ratio": {"type": "number"},
                "enabled": {"type": "boolean"},
                "props": {"type": "object"},
                "tags": {"type": "array"},
            },
        }
        fields = {f.name: f for f in BUILDER.extract_from_json_schema(schema)}

        assert fields["name"].type == "string"
        assert fields["count"].type == "number"
        assert fields["ratio"].type == "number"
        assert fields["enabled"].type == "boolean"
        assert fields["props"].type == "json"
        assert fields["tags"].type == "list"

    def test_enum_becomes_select_with_labelled_options(self):
        schema = {
            "type": "object",
            "properties": {
                "mode": {
                    "type": "string",
                    "enum": ["fast", "slow_lane"],
                    "title": "Mode",
                }
            },
        }
        field = BUILDER.extract_from_json_schema(schema)[0]

        assert field.type == "select"
        assert field.enum == ["fast", "slow_lane"]
        assert field.options == [
            {"label": "Fast", "value": "fast"},
            {"label": "Slow Lane", "value": "slow_lane"},
        ]

    def test_nullable_union_type_takes_first_non_null(self):
        schema = {"type": "object", "properties": {"note": {"type": ["string", "null"]}}}
        assert BUILDER.extract_from_json_schema(schema)[0].type == "string"

    def test_malformed_schema_returns_empty_list_not_crash(self):
        assert BUILDER.extract_from_json_schema({}) == []
        assert BUILDER.extract_from_json_schema({"properties": None}) == []
        assert BUILDER.extract_from_json_schema({"properties": {"x": "not-a-dict"}}) == []
        assert BUILDER.extract_from_json_schema(None) == []  # type: ignore[arg-type]


class TestValidationMetadata:
    def test_extracts_numeric_and_string_constraints(self):
        schema = {
            "type": "object",
            "properties": {
                "timeout_seconds": {"type": "number", "minimum": 1, "maximum": 300},
                "query": {"type": "string", "minLength": 1, "maxLength": 4000, "pattern": "^SELECT"},
                "items": {"type": "array", "minItems": 1},
                "token": {"type": "string", "format": "password"},
            },
        }
        fields = {f.name: f for f in BUILDER.extract_from_json_schema(schema)}

        assert fields["timeout_seconds"].minimum == 1.0
        assert fields["timeout_seconds"].maximum == 300.0
        assert fields["query"].min_length == 1
        assert fields["query"].max_length == 4000
        assert fields["query"].pattern == "^SELECT"
        assert fields["items"].min_items == 1
        assert fields["token"].format == "password"

    def test_required_from_schema_block(self):
        schema = {
            "type": "object",
            "properties": {"a": {"type": "string"}, "b": {"type": "string"}},
            "required": ["a"],
        }
        fields = {f.name: f for f in BUILDER.extract_from_json_schema(schema)}
        assert fields["a"].required is True
        assert fields["b"].required is False

    def test_defaults_and_descriptions_are_carried_through(self):
        schema = {
            "type": "object",
            "properties": {
                "page_size": {
                    "type": "integer",
                    "default": 50,
                    "description": "Rows per page.",
                    "placeholder": "e.g. 50",
                    "title": "Page Size",
                }
            },
        }
        field = BUILDER.extract_from_json_schema(schema)[0]
        assert field.default == 50
        assert field.description == "Rows per page."
        assert field.placeholder == "e.g. 50"
        assert field.title == "Page Size"


class TestGrouping:
    def test_anchor_fields_go_to_main_group(self):
        schema = {
            "type": "object",
            "properties": {
                "resource": {"type": "string"},
                "entity": {"type": "string"},
                "mode": {"type": "string"},
            },
        }
        fields = {f.name: f for f in BUILDER.extract_from_json_schema(schema)}
        assert fields["resource"].group == "main"
        assert fields["entity"].group == "main"
        assert fields["mode"].group == "parameters"

    def test_known_advanced_keys_are_flagged(self):
        schema = {
            "type": "object",
            "properties": {
                "timeout_seconds": {"type": "number"},
                "retry_max_attempts": {"type": "integer"},
                "max_pages": {"type": "integer"},
                "page_size": {"type": "integer"},
                "continue_on_error": {"type": "boolean"},
            },
        }
        fields = {f.name: f for f in BUILDER.extract_from_json_schema(schema)}
        for name in ("timeout_seconds", "retry_max_attempts", "max_pages", "page_size", "continue_on_error"):
            assert fields[name].advanced is True, name
            assert fields[name].group == "advanced", name

    def test_explicit_advanced_flag_and_x_group_override(self):
        schema = {
            "type": "object",
            "properties": {
                "weird": {"type": "string", "advanced": True},
                "explicit": {"type": "string", "x-group": "advanced"},
                "named": {"type": "string", "x-group": "options"},
            },
        }
        fields = {f.name: f for f in BUILDER.extract_from_json_schema(schema)}
        assert fields["weird"].advanced is True
        assert fields["explicit"].advanced is True
        assert fields["named"].group == "options"
        assert fields["named"].advanced is False


class TestConditionalVisibility:
    def test_operation_membership_rule(self):
        schema = {"type": "object", "properties": {"soql": {"type": "string"}}}
        ops = {
            "query": {"properties": ["soql"], "required": ["soql"]},
            "create": {"properties": ["record"]},
            "delete": {"properties": ["record_id"]},
        }
        fields = BUILDER.extract_from_json_schema(schema, ops)

        assert _field(fields, "soql").show_if == {"operation": ["query"]}

    def test_field_used_by_every_operation_has_no_rule(self):
        schema = {"type": "object", "properties": {"timeout_seconds": {"type": "number"}}}
        ops = {
            "query": {"properties": ["timeout_seconds"]},
            "create": {"properties": ["timeout_seconds"]},
        }
        fields = BUILDER.extract_from_json_schema(schema, ops)
        assert _field(fields, "timeout_seconds").show_if is None

    def test_field_used_by_no_operation_has_no_rule(self):
        schema = {"type": "object", "properties": {"unrelated": {"type": "string"}}}
        ops = {"query": {"properties": ["soql"]}}
        fields = BUILDER.extract_from_json_schema(schema, ops)
        assert _field(fields, "unrelated").show_if is None

    def test_minority_operation_uses_positive_membership(self):
        schema = {"type": "object", "properties": {"soql": {"type": "string"}}}
        ops = {
            "query": {"properties": ["soql"]},
            "create": {"properties": ["record"]},
            "delete": {"properties": ["record_id"]},
            "update": {"properties": ["record", "record_id"]},
        }
        fields = BUILDER.extract_from_json_schema(schema, ops)
        assert _field(fields, "soql").show_if == {"operation": ["query"]}

    def test_majority_operation_uses_negated_membership(self):
        schema = {
            "type": "object",
            "properties": {"common": {"type": "string"}, "rare": {"type": "string"}},
        }
        ops = {
            "a": {"properties": ["common", "rare"]},
            "b": {"properties": ["common", "rare"]},
            "c": {"properties": ["common"]},
        }
        fields = {f.name: f for f in BUILDER.extract_from_json_schema(schema, ops)}
        # `common` is in 3/3 -> no rule; `rare` is in 2/3 -> negated rule
        assert fields["common"].show_if is None
        assert fields["rare"].show_if == {"operation": ["!c"]}

    def test_json_schema_if_then_conditional(self):
        schema = {
            "type": "object",
            "properties": {
                "mode": {"type": "string", "enum": ["advanced", "simple"]},
                "api_url": {"type": "string"},
            },
            "if": {"properties": {"mode": {"const": "advanced"}}, "required": ["mode"]},
            "then": {"required": ["api_url"]},
        }
        fields = {f.name: f for f in BUILDER.extract_from_json_schema(schema)}
        assert fields["api_url"].show_if == {"mode": ["advanced"]}
        # `mode` itself is not conditional
        assert fields["mode"].show_if is None

    def test_if_then_enum_variant(self):
        schema = {
            "type": "object",
            "properties": {"auth": {"type": "string"}, "secret": {"type": "string"}},
            "allOf": [
                {
                    "if": {"properties": {"auth": {"enum": ["basic", "digest"]}}, "required": ["auth"]},
                    "then": {"required": ["secret"]},
                }
            ],
        }
        fields = {f.name: f for f in BUILDER.extract_from_json_schema(schema)}
        assert fields["secret"].show_if == {"auth": ["basic", "digest"]}


class TestRequiredResolution:
    def test_required_by_all_consuming_operations(self):
        schema = {"type": "object", "properties": {"soql": {"type": "string"}}}
        ops = {
            "query": {"properties": ["soql"], "required": ["soql"]},
            "explain": {"properties": ["soql"], "required": ["soql"]},
        }
        assert _field(BUILDER.extract_from_json_schema(schema, ops), "soql").required is True

    def test_required_by_no_consuming_operations(self):
        schema = {"type": "object", "properties": {"note": {"type": "string"}}}
        ops = {"query": {"properties": ["note"], "required": []}}
        assert _field(BUILDER.extract_from_json_schema(schema, ops), "note").required is False

    def test_required_by_some_operations_is_not_marked_required(self):
        schema = {"type": "object", "properties": {"record": {"type": "object"}}}
        ops = {
            "create": {"properties": ["record"], "required": ["record"]},
            "search": {"properties": ["record"], "required": []},
        }
        # Conditionally required -> must not show a permanent required marker
        assert _field(BUILDER.extract_from_json_schema(schema, ops), "record").required is False

    def test_falls_back_to_schema_required_when_op_metadata_absent(self):
        schema = {
            "type": "object",
            "properties": {"soql": {"type": "string"}},
            "required": ["soql"],
        }
        ops = {"query": {"properties": ["soql"]}}  # no per-op `required`
        assert _field(BUILDER.extract_from_json_schema(schema, ops), "soql").required is True


class TestOperationSpecs:
    def test_build_operations_normalises_metadata(self):
        specs = BUILDER.build_operations(
            {
                "create_contact": {
                    "display_name": None,
                    "description": "",
                    "idempotency": "non_idempotent",
                    "retryable": False,
                    "properties": ["email"],
                    "required": ["email"],
                    "output_preview": {"type": "object", "properties": {"id": {"type": "string"}}},
                }
            }
        )
        spec = specs["create_contact"]
        assert spec.key == "create_contact"
        assert spec.display_name == "Create Contact"  # generated from the key
        assert spec.idempotency == "non_idempotent"
        assert spec.required == ["email"]
        assert spec.output_preview["properties"]["id"]["type"] == "string"

    def test_build_operations_ignores_non_dict_entries(self):
        assert BUILDER.build_operations({"x": "bad"}) == {}
        assert BUILDER.build_operations(None) == {}  # type: ignore[arg-type]

    def test_output_preview_lookup(self):
        ops = {
            "list": {"output_preview": {"type": "object", "properties": {"items": {"type": "array"}}}},
            "get": {},
        }
        assert BUILDER.output_preview_for(ops, "list")["properties"]["items"]["type"] == "array"
        assert BUILDER.output_preview_for(ops, "get") is None
        assert BUILDER.output_preview_for(ops, "missing") is None
        assert BUILDER.output_preview_for(None, "list") is None
        assert BUILDER.output_preview_for(ops, None) is None


class TestNodeOperationDeclarations:
    """The API layer's node/connector operation metadata.

    These pin the contract between ``BaseNode.operations`` and the config
    panel. A node that declares operations has to keep its declaration in
    step with the selector enum it actually accepts, because the panel builds
    its operation dropdown from the declared keys — a gap there is not an
    error, it is a value the user simply cannot pick.
    """

    def test_builtin_node_operations_are_declared(self):
        from app.nodes.registry import NODE_REGISTRY, _load_builtin_nodes
        from app.api.nodes import _operations_meta_from_definitions, _selector_values

        _load_builtin_nodes()
        cls = NODE_REGISTRY["crypto_tools"]
        schema = cls.parameters_schema.model_json_schema()
        selector = getattr(cls, "operation_selector", None)
        values = _selector_values(cls, schema, selector)
        meta = _operations_meta_from_definitions(cls.operations, values)

        # Every value the selector accepts is selectable in the panel.
        assert set(meta) == set(values)
        # ...and none of them had to be invented to get there.
        assert not any(v.get("undeclared") for v in meta.values())

    def test_declared_properties_are_not_dropped(self):
        from app.nodes.registry import NODE_REGISTRY, _load_builtin_nodes
        from app.api.nodes import _operations_meta_from_definitions, _selector_values

        _load_builtin_nodes()
        cls = NODE_REGISTRY["crypto_tools"]
        schema = cls.parameters_schema.model_json_schema()
        meta = _operations_meta_from_definitions(
            cls.operations, _selector_values(cls, schema, getattr(cls, "operation_selector", None))
        )

        # Nodes declare `properties` directly; reading only `input_schema`
        # would have silently emptied every one of these.
        assert meta["hmac"]["properties"] == ["text", "algorithm", "key"]
        assert meta["jwt_verify"]["properties"] == [
            "jwt_token", "secret", "issuer", "audience", "leeway_seconds",
        ]
        assert meta["hmac"]["required"] == ["key"]

    def test_non_operation_selector_gates_its_own_fields(self):
        from app.nodes.registry import NODE_REGISTRY, _load_builtin_nodes
        from app.api.nodes import _operations_meta_from_definitions, _selector_values
        from app.parameters import ParameterSchemaBuilder as B

        _load_builtin_nodes()
        cls = NODE_REGISTRY["rename_keys"]
        schema = cls.parameters_schema.model_json_schema()
        selector = cls.operation_selector
        assert selector == "mode"
        values = _selector_values(cls, schema, selector)
        meta = _operations_meta_from_definitions(cls.operations, values)
        fields = {
            f.name: f
            for f in B.extract_from_json_schema(schema, meta, selector=selector)
        }

        # The selector is the control that changes operation, so it is never
        # itself gated by one.
        assert fields["mode"].group == "main"
        assert fields["mode"].show_if is None
        # keep_unmatched only affects rename/copy; remove ignores it. The
        # builder expresses a majority rule as a negation so the rule stays
        # correct if a fourth mode is ever added.
        assert fields["keep_unmatched"].show_if == {"mode": ["!remove"]}
        assert fields["use_paths"].show_if is None  # used by all three

    def test_connector_definition_properties_are_read_from_input_schema(self):
        from app.api.nodes import _operations_meta_from_definitions

        definition = {
            "query": {
                "idempotency": "idempotent",
                "retryable": True,
                "properties": ["soql", "top"],
                "required": ["soql"],
            },
            "get": {
                # Connector definitions nest the same list under input_schema.
                "input_schema": {"properties": {"record_id": {}}, "required": ["record_id"]},
            },
        }
        meta = _operations_meta_from_definitions(definition)

        assert meta["query"]["properties"] == ["soql", "top"]
        assert meta["get"]["properties"] == ["record_id"]
        assert meta["get"]["required"] == ["record_id"]
        assert meta["query"]["retryable"] is True

    def test_undeclared_selector_value_is_filled_not_dropped(self):
        from app.api.nodes import _operations_meta_from_definitions

        meta = _operations_meta_from_definitions(
            {"query": {"properties": ["soql"], "required": ["soql"]}},
            ["query", "create", "delete"],
        )

        assert set(meta) == {"query", "create", "delete"}
        # Declared operations keep their real metadata.
        assert meta["query"]["required"] == ["soql"]
        assert meta["query"].get("undeclared") is None
        # Gaps stay selectable and get a usable label, but are marked so no
        # caller mistakes them for a declared operation.
        for key in ("create", "delete"):
            assert meta[key]["undeclared"] is True
            assert meta[key]["properties"] == []
            assert meta[key]["display_name"] == key.title()

    def test_selector_values_reads_literal_from_pydantic(self):
        from app.nodes.registry import NODE_REGISTRY, _load_builtin_nodes
        from app.api.nodes import _selector_values

        _load_builtin_nodes()
        cls = NODE_REGISTRY["crypto_tools"]
        # No JSON-schema enum here — the values live in the Literal annotation.
        assert _selector_values(cls, {}) == [
            "hash", "hmac", "base64_encode", "base64_decode", "uuid", "token",
            "jwt_sign", "jwt_verify", "totp_generate", "totp_verify",
        ]
        assert _selector_values(cls, {}, "mode") == []

    def test_selector_values_reads_enum_from_json_schema(self):
        from app.api.nodes import _selector_values

        class _Fake:
            parameters_schema = None

        schema = {"properties": {"operation": {"type": "string", "enum": ["a", "b"]}}}
        assert _selector_values(_Fake, schema) == ["a", "b"]
        assert _selector_values(_Fake, {"properties": {}}) == []


class TestEndToEnd:
    def test_field_model_round_trips_to_dict(self):
        """The API serialises fields with model_dump(); assert nothing is lost."""
        schema = {
            "type": "object",
            "properties": {
                "mode": {"type": "string", "enum": ["a", "b"], "description": "Pick one"},
                "n": {"type": "integer", "minimum": 0, "maximum": 10, "default": 3},
            },
            "required": ["mode"],
        }
        ops = {"run": {"properties": ["mode", "n"], "required": ["mode"]}}

        dumped = [f.model_dump() for f in BUILDER.extract_from_json_schema(schema, ops)]
        assert len(dumped) == 2

        mode = next(d for d in dumped if d["name"] == "mode")
        assert mode["type"] == "select"
        assert mode["required"] is True
        assert mode["options"][0] == {"label": "A", "value": "a"}
        assert mode["description"] == "Pick one"
        assert mode["group"] == "parameters"

        n = next(d for d in dumped if d["name"] == "n")
        assert n["default"] == 3
        assert n["minimum"] == 0.0
        assert n["maximum"] == 10.0

        # Reconstructing must be lossless
        rebuilt = ParameterField(**mode)
        assert rebuilt.name == "mode"
        assert rebuilt.options == mode["options"]

    def test_no_fields_are_invented_for_empty_schema(self):
        assert BUILDER.extract_from_json_schema({"type": "object"}) == []
