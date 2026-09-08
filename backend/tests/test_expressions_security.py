"""Security tests for the safe expression engine (Phase 40).

Guarantees under attack/bad input:
1. No eval/exec/__import__ anywhere in the module source.
2. Dunder traversal (prototype pollution) is refused.
3. Malformed/hostile expressions never raise — they resolve to None or
   stay visibly unresolved.
4. Deep nesting cannot blow the Python stack (depth cap).
5. Secrets in context are only reachable by exact path; error output
   never echoes them.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.engine import expressions as expr_mod
from app.engine.expressions import build_context, resolve, _path_keys


MODULE_SRC = Path(expr_mod.__file__).read_text(encoding="utf-8")


# ----------------------------------------------------------------------
# 1) No eval / exec / __import__
# ----------------------------------------------------------------------

def test_module_source_has_no_eval_exec_import():
    import re as _re

    for banned in (r"(?<!re\.)\beval\s*\(", r"\bexec\s*\(", r"__import__\s*\(", r"os\.system\s*\("):
        assert not _re.search(banned, MODULE_SRC), f"banned call present: {banned}"


# ----------------------------------------------------------------------
# 2) Prototype-pollution / dunder traversal
# ----------------------------------------------------------------------

def _ctx(payload):
    return {"$json": payload}


@pytest.mark.parametrize(
    "expression",
    [
        "{{ $json.__class__ }}",
        "{{ $json.__init__ }}",
        '{{ $json["__class__"] }}',
        "{{ $json.a.__globals__ }}",
        '{{ $json["a"]["__dunder__"] }}',
    ],
)
def test_dunder_traversal_refused(expression):
    payload = {
        "a": {"b": 1},
        "__class__": "PWNED",
        "__init__": "PWNED",
    }
    out = resolve(expression, _ctx(payload))
    # Either stays visible-unresolved or resolves to null — never leaks
    assert "PWNED" not in str(out)
    assert out is None or out.startswith("{{")


# ----------------------------------------------------------------------
# 3) Hostile/malformed inputs never raise
# ----------------------------------------------------------------------

@pytest.mark.parametrize(
    "expr",
    [
        "{{",                                     # unclosed
        "}}",                                     # stray close
        "{{ }}",                                  # empty body
        "{{ $json. }}",                           # dangling dot
        '{{ $node["unclosed.json }}',             # unterminated quote
        "{{ $json[a][b }}",                       # unterminated bracket
        "{{ $json[[[[[[]]]]]] }}",
        "{{ 1 + + 2 }}",
        "{{ $json.x.y.z.w.v.u.t.s.r.q.p.o.n.m.l.k.j.i.h.g.f.e.d.c.b.a }}",
        "{{ !!!!$json.a }}",
        "{{ $json | | upper }}",
        "{{ $json.a > }}",
        "{{ ((($json.a)) }}",
        "{{ $json; import os }}",
        "{{ __builtins__ }}",
        "{{ $env.__dict__ }}",
    ],
)
def test_hostile_expressions_never_raise(expr):
    ctx = build_context([{"a": {"b": 1}}], {}, "wf", "exec")
    try:
        out = resolve(expr, ctx)
    except Exception as exc:  # noqa: BLE001 - the contract is: never raises
        raise AssertionError(f"expression {expr!r} raised {exc}") from exc
    assert not isinstance(out, BaseException)


# ----------------------------------------------------------------------
# 4) Depth cap
# ----------------------------------------------------------------------

def test_deep_path_is_capped_not_crashing():
    payload = current = {}
    for i in range(500):
        nxt = {}
        current[f"d{i}"] = nxt
        current = nxt
    deep_path = "$json." + ".".join(f"d{i}" for i in range(500))
    out = resolve("{{ %s }}" % deep_path, _ctx(payload))
    # Capped paths stay visibly unresolved (contract: unresolvable is
    # never silently dropped) and no recursion crash occurs.
    assert str(out).startswith("{{ $json.d0.d1")


def test_deep_payload_walk_is_bounded():
    payload = {"k": "v"}
    node = payload
    for i in range(300):
        node["n"] = {}
        node = node["n"]
    keys = _path_keys("$json." + ".n" * 300)
    assert keys is None  # beyond MAX_PATH_DEPTH*2 → refused


# ----------------------------------------------------------------------
# 5) Secret hygiene in errors/output
# ----------------------------------------------------------------------

def test_unresolved_expression_does_not_echo_other_context_values():
    creds_ctx = {"$cred": {"http": {"api_key": "SUPER_SECRET_KEY"}}, "$json": {"a": 1}}
    out = resolve("{{ $cred.http.nonexistent_key }}", creds_ctx)
    assert out == "{{ $cred.http.nonexistent_key }}"
    assert "SUPER_SECRET_KEY" not in str(out)


def test_null_handling_explicit():
    ctx = _ctx({"empty": None, "zero": 0, "falsy_str": ""})
    assert resolve("{{ $json.empty }}", ctx) == "{{ $json.empty }}"
    assert resolve("{{ $json.zero ?? 'default' }}", ctx) == 0          # ?? keeps falsy-but-present
    assert resolve("{{ $json.empty ?? 'fallback' }}", ctx) == "fallback"
    assert resolve("{{ $json.falsy_str == '' }}", ctx) is True


# ----------------------------------------------------------------------
# Type pipes (type validation support)
# ----------------------------------------------------------------------

def test_type_pipes():
    ctx = _ctx({"n": "42", "f": "3.5", "flag": "x", "nothing": None})
    assert resolve("{{ $json.n | int }}", ctx) == 42
    assert isinstance(resolve("{{ $json.f | float }}", ctx), float)
    assert resolve("{{ $json.flag | bool }}", ctx) is True
    assert resolve("{{ $json.nothing | typeof }}", ctx) is None
    assert resolve("{{ $json.n | typeof }}", ctx) == "string"


# ----------------------------------------------------------------------
# Quoted-key + bracket access (new surface)
# ----------------------------------------------------------------------

def test_quoted_bracket_access():
    from app.engine.expressions import build_context

    nodes = {"My Node": {"json": {"value": 5}}, "other-node": {"json": {"v": "x"}}}
    ctx = build_context([], {}, "wf", "e")
    ctx["$node"] = nodes
    assert resolve('{{ $node["My Node"].json.value }}', ctx) == 5
    assert resolve("{{ $node['other-node'].json.v }}", ctx) == "x"
    assert resolve('{{ $node["missing"].json }}', ctx) == "{{ $node[\"missing\"].json }}"
