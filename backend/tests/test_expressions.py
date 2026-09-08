"""Tests for the enhanced expression engine.

Covers: arithmetic, string ops, array access, comparisons,
logical operators, ternary, coalesce, and backward compatibility.
"""

import pytest
from app.engine.expressions import build_context, resolve, _eval_expr


def _ctx(**overrides):
    """Build a test context with sample data."""
    base = {
        "$json": {
            "name": "Alice",
            "age": 30,
            "price": 9.99,
            "active": True,
            "status": "active",
            "tags": ["admin", "user"],
            "nested": {"key": "value"},
            "empty": None,
        },
        "$node": {
            "trigger": {"json": {"greeting": "hello"}},
        },
        "$cred": {"http": {"token": "abc123"}},
        "$workflow": {"id": "wf_1"},
        "$execution": {"id": "exec_1"},
        "$now": "2026-01-01T00:00:00+00:00",
    }
    base.update(overrides)
    return base


# === BACKWARD COMPATIBILITY ===

class TestBackwardCompat:
    def test_simple_lookup(self):
        ctx = _ctx()
        assert resolve("{{ $json.name }}", ctx) == "Alice"

    def test_nested_lookup(self):
        ctx = _ctx()
        assert resolve("{{ $json.nested.key }}", ctx) == "value"

    def test_node_lookup(self):
        ctx = _ctx()
        assert resolve("{{ $node.trigger.json.greeting }}", ctx) == "hello"

    def test_cred_lookup(self):
        ctx = _ctx()
        assert resolve("{{ $cred.http.token }}", ctx) == "abc123"

    def test_workflow_id(self):
        ctx = _ctx()
        assert resolve("{{ $workflow.id }}", ctx) == "wf_1"

    def test_execution_id(self):
        ctx = _ctx()
        assert resolve("{{ $execution.id }}", ctx) == "exec_1"

    def test_now(self):
        ctx = _ctx()
        result = resolve("{{ $now }}", ctx)
        assert "2026" in result or "T" in result

    def test_unresolved_left_intact(self):
        ctx = _ctx()
        assert resolve("{{ $json.missing }}", ctx) == "{{ $json.missing }}"

    def test_dict_recursion(self):
        ctx = _ctx()
        result = resolve({"a": "{{ $json.name }}", "b": 42}, ctx)
        assert result == {"a": "Alice", "b": 42}

    def test_list_recursion(self):
        ctx = _ctx()
        result = resolve(["{{ $json.name }}", 42], ctx)
        assert result == ["Alice", 42]

    def test_mixed_string_and_expr(self):
        ctx = _ctx()
        assert resolve("Hello {{ $json.name }}!", ctx) == "Hello Alice!"

    def test_coerce_int(self):
        ctx = _ctx()
        result = resolve("{{ $json.age }}", ctx)
        assert result == 30
        assert isinstance(result, int)

    def test_coerce_float(self):
        ctx = _ctx()
        result = resolve("{{ $json.price }}", ctx)
        assert result == pytest.approx(9.99)

    def test_coerce_bool(self):
        ctx = _ctx()
        result = resolve("{{ $json.active }}", ctx)
        assert result is True

    def test_coerce_null(self):
        ctx = _ctx()
        # $json.empty is None, which is indistinguishable from "not found"
        # in the lookup, so it renders as the unresolved expression text
        result = resolve("{{ $json.empty }}", ctx)
        assert result == "{{ $json.empty }}"


# === ARRAY ACCESS ===

class TestArrayAccess:
    def test_index_zero(self):
        ctx = _ctx()
        assert resolve("{{ $json.tags[0] }}", ctx) == "admin"

    def test_index_one(self):
        ctx = _ctx()
        assert resolve("{{ $json.tags[1] }}", ctx) == "user"

    def test_index_out_of_bounds(self):
        ctx = _ctx()
        assert resolve("{{ $json.tags[5] }}", ctx) == "{{ $json.tags[5] }}"

    def test_array_length(self):
        ctx = _ctx()
        result = resolve("{{ $json.tags.length }}", ctx)
        assert result == 2

    def test_index_in_mixed_expr(self):
        ctx = _ctx()
        assert resolve("Tag: {{ $json.tags[0] }}", ctx) == "Tag: admin"


# === ARITHMETIC ===

class TestArithmetic:
    def test_add(self):
        ctx = _ctx()
        result = resolve("{{ $json.age + 5 }}", ctx)
        assert result == 35

    def test_subtract(self):
        ctx = _ctx()
        result = resolve("{{ $json.age - 10 }}", ctx)
        assert result == 20

    def test_multiply(self):
        ctx = _ctx()
        result = resolve("{{ $json.price * 2 }}", ctx)
        assert result == pytest.approx(19.98)

    def test_divide(self):
        ctx = _ctx()
        result = resolve("{{ $json.age / 2 }}", ctx)
        assert result == 15

    def test_modulo(self):
        ctx = _ctx()
        result = resolve("{{ $json.age % 3 }}", ctx)
        assert result == 0

    def test_divide_by_zero_returns_none(self):
        ctx = _ctx()
        result = resolve("{{ $json.age / 0 }}", ctx)
        assert result == "{{ $json.age / 0 }}"

    def test_add_two_vars(self):
        ctx = _ctx()
        result = resolve("{{ $json.age + $json.price }}", ctx)
        assert result == pytest.approx(39.99)

    def test_int_result(self):
        ctx = _ctx()
        result = resolve("{{ $json.age * 2 }}", ctx)
        assert result == 60
        assert isinstance(result, int)


# === STRING OPERATIONS ===

class TestStringOps:
    def test_upper(self):
        ctx = _ctx()
        result = resolve("{{ $json.name | upper }}", ctx)
        assert result == "ALICE"

    def test_lower(self):
        ctx = _ctx()
        result = resolve("{{ $json.name | lower }}", ctx)
        assert result == "alice"

    def test_length(self):
        ctx = _ctx()
        result = resolve("{{ $json.name | length }}", ctx)
        assert result == 5

    def test_trim(self):
        ctx = _ctx()
        ctx2 = _ctx()
        ctx2["$json"] = {**ctx2["$json"], "padded": "  hello  "}
        result = resolve("{{ $json.padded | trim }}", ctx2)
        assert result == "hello"

    def test_contains_true(self):
        ctx = _ctx()
        result = resolve("{{ $json.name | contains(\"lic\") }}", ctx)
        assert result is True

    def test_contains_false(self):
        ctx = _ctx()
        result = resolve("{{ $json.name | contains(\"xyz\") }}", ctx)
        assert result is False

    def test_replace(self):
        ctx = _ctx()
        result = resolve("{{ $json.name | replace(\"Alice\", \"Bob\") }}", ctx)
        assert result == "Bob"

    def test_upper_in_string(self):
        ctx = _ctx()
        result = resolve("Name: {{ $json.name | upper }}", ctx)
        assert result == "Name: ALICE"


# === COMPARISONS ===

class TestComparisons:
    def test_equals_string(self):
        ctx = _ctx()
        result = resolve("{{ $json.name == \"Alice\" }}", ctx)
        assert result is True

    def test_not_equals_string(self):
        ctx = _ctx()
        result = resolve("{{ $json.name != \"Bob\" }}", ctx)
        assert result is True

    def test_gt(self):
        ctx = _ctx()
        result = resolve("{{ $json.age > 25 }}", ctx)
        assert result is True

    def test_lt(self):
        ctx = _ctx()
        result = resolve("{{ $json.age < 25 }}", ctx)
        assert result is False

    def test_gte(self):
        ctx = _ctx()
        result = resolve("{{ $json.age >= 30 }}", ctx)
        assert result is True

    def test_lte(self):
        ctx = _ctx()
        result = resolve("{{ $json.age <= 30 }}", ctx)
        assert result is True

    def test_eq_none(self):
        ctx = _ctx()
        result = resolve("{{ $json.empty == null }}", ctx)
        assert result is True

    def test_ne_none(self):
        ctx = _ctx()
        result = resolve("{{ $json.name != null }}", ctx)
        assert result is True

    def test_comparison_in_string(self):
        ctx = _ctx()
        result = resolve("Active: {{ $json.age > 25 }}", ctx)
        assert result == "Active: True"


# === LOGICAL OPERATORS ===

class TestLogical:
    def test_and_true(self):
        ctx = _ctx()
        result = resolve("{{ $json.active && $json.name }}", ctx)
        assert result == "Alice"

    def test_and_false(self):
        ctx = _ctx()
        result = resolve("{{ $json.empty && $json.name }}", ctx)
        assert result == ""

    def test_or_first(self):
        ctx = _ctx()
        result = resolve("{{ $json.name || $json.empty }}", ctx)
        assert result == "Alice"

    def test_or_second(self):
        ctx = _ctx()
        result = resolve("{{ $json.empty || $json.name }}", ctx)
        assert result == "Alice"

    def test_negate(self):
        ctx = _ctx()
        result = resolve("{{ !$json.active }}", ctx)
        assert result is False


# === TERNARY ===

class TestTernary:
    def test_ternary_true(self):
        ctx = _ctx()
        result = resolve("{{ $json.active ? \"yes\" : \"no\" }}", ctx)
        assert result == "yes"

    def test_ternary_false(self):
        ctx = _ctx()
        ctx2 = _ctx()
        ctx2["$json"] = {**ctx2["$json"], "active": False}
        result = resolve("{{ $json.active ? \"yes\" : \"no\" }}", ctx2)
        assert result == "no"

    def test_ternary_with_comparison(self):
        ctx = _ctx()
        result = resolve("{{ $json.age > 25 ? \"old\" : \"young\" }}", ctx)
        assert result == "old"

    def test_ternary_nested(self):
        """Ternary can reference results from nested lookups."""
        ctx = _ctx()
        result = resolve(
            "{{ $json.active ? $json.nested.key : $json.empty }}",
            ctx,
        )
        assert result == "value"


# === COALESCE ===

class TestCoalesce:
    def test_coalesce_first(self):
        ctx = _ctx()
        result = resolve("{{ $json.name ?? \"default\" }}", ctx)
        assert result == "Alice"

    def test_coalesce_second(self):
        ctx = _ctx()
        result = resolve("{{ $json.empty ?? \"default\" }}", ctx)
        assert result == "default"


# === ENV VARS (Phase 31) ===

class TestEnvVars:
    def test_env_lookup(self):
        ctx = _ctx(**{"$env": {"API_URL": "https://api.test"}})
        assert resolve("{{ $env.API_URL }}", ctx) == "https://api.test"

    def test_env_missing_stays_visible(self):
        ctx = _ctx(**{"$env": {}})
        assert resolve("{{ $env.NOPE }}", ctx) == "{{ $env.NOPE }}"

    def test_env_in_mixed_string(self):
        ctx = _ctx(**{"$env": {"HOST": "example.com"}})
        assert resolve("https://{{ $env.HOST }}/x", ctx) == "https://example.com/x"

    def test_env_default_via_coalesce(self):
        ctx = _ctx(**{"$env": {}})
        assert resolve("{{ $env.HOST ?? \"fallback\" }}", ctx) == "fallback"


# === EDGE CASES ===

class TestEdgeCases:
    def test_non_string_passthrough(self):
        ctx = _ctx()
        assert resolve(42, ctx) == 42
        assert resolve(None, ctx) is None
        assert resolve(True, ctx) is True

    def test_empty_string(self):
        ctx = _ctx()
        assert resolve("", ctx) == ""

    def test_no_expression(self):
        ctx = _ctx()
        assert resolve("plain text", ctx) == "plain text"

    def test_multiple_expressions(self):
        ctx = _ctx()
        result = resolve("{{ $json.name }} is {{ $json.age }}", ctx)
        assert result == "Alice is 30"

    def test_deeply_nested(self):
        ctx = _ctx()
        result = resolve({"a": {"b": "{{ $json.name }}"}}, ctx)
        assert result == {"a": {"b": "Alice"}}

    def test_chain_pipe_ops(self):
        """Pipe chain: first | upper | length."""
        ctx = _ctx()
        # Pipe chain is evaluated left-to-right in _render
        # $json.name | upper -> "ALICE" | length -> 5
        result = resolve("{{ $json.name | upper | length }}", ctx)
        assert result == 5


class TestOptionalChaining:
    def test_optional_chaining_existing_field(self):
        ctx = _ctx(**{"$json": {"user": {"profile": {"name": "Gaurav"}}}})
        assert resolve("{{ $json.user?.profile?.name }}", ctx) == "Gaurav"

    def test_optional_chaining_missing_field_returns_empty(self):
        ctx = _ctx(**{"$json": {"user": None}})
        assert resolve("{{ $json.user?.profile?.name }}", ctx) == ""

    def test_optional_chaining_array_index_zero_results(self):
        ctx = _ctx(**{"$json": {"records": []}})
        assert resolve("{{ $json.records?.[0]?.Id }}", ctx) == ""

    def test_optional_chaining_with_coalesce_default(self):
        ctx = _ctx(**{"$json": {"records": []}})
        assert resolve("{{ $json.records[0]?.Id ?? 'N/A' }}", ctx) == "N/A"
