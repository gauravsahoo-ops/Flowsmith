"""Safe `{{ }}` expression evaluator with arithmetic, string, and array ops.

Supported expressions:
  {{ $json.field }}              -> value from the first input item
  {{ $json.field.nested }}       -> nested dot-path traversal
  {{ $json.items[0] }}           -> array index access
  {{ $json.items.length }}       -> array length
  {{ $node.<id>.json.field }}    -> value from a specific node's output
  {{ $cred.<type>.<field> }}     -> value from the node's resolved credential
  {{ $workflow.id }}             -> workflow id
  {{ $execution.id }}            -> execution id
  {{ $now }}                     -> current ISO timestamp

Arithmetic:  {{ $json.a + $json.b }}, {{ $json.x * 2 }}, {{ $json.y - 1 }}
String ops:  {{ $json.name | upper }}, {{ $json.name | lower }}, {{ $json.name | length }}
             {{ $json.name | trim }}, {{ $json.text | replace("old", "new") }}
             {{ $json.name | contains("ali") }}
Comparisons: {{ $json.status == "active" }}, {{ $json.count > 5 }}
             {{ $json.x != null }}, {{ $json.a <= 10 }}
Logical:     {{ $json.a && $json.b }}, {{ $json.a || $json.b }}, {{ !$json.a }}
Ternary:     {{ $json.status == "active" ? "Yes" : "No" }}
Coalesce:    {{ $json.fallback ?? "default" }}

Security rules (spec 30): pure evaluator. No eval, no exec, no imports,
no shell, no filesystem. Unresolvable expressions are left intact.
"""

from __future__ import annotations

import operator
import re
from datetime import datetime, timezone
from typing import Any

_EXPR_RE = re.compile(r"\{\{\s*(.+?)\s*\}\}")
_INDEX_RE = re.compile(r"^(.+)\[(\d+)\]$")
_SEGMENT_RE = re.compile(r"^([^\[\]]+)((?:\[[^\]\[]*\])*)$")
_BRACKET_RE = re.compile(r"\[([^\]\[]*)\]")
_DUNDER_RE = re.compile(r"^__.*__$")
MAX_PATH_DEPTH = 32
_PIPE_RE = re.compile(r"^(.+?)\s*\|\s*(\w+)(?:\(([^)]*)\))?$")
_COMPARE_RE = re.compile(
    r"^(.+?)\s*(==|!=|>=|<=|>|<)\s*(.+)$"
)
_LOGIC_RE = re.compile(
    r"^(.+?)\s*(&&|\|\|)\s*(.+)$"
)
_NEGATE_RE = re.compile(r"^!\s*(.+)$"
)
_COALESCE_RE = re.compile(r"^(.+?)\s*\?\?\s*(.+)$"
)
_TERNARY_RE = re.compile(
    r"^(.+?)\s*\?\s*(.+?)\s*:\s*(.+)$"
)
_ARITH_RE = re.compile(
    r"^(.+?)\s*([+\-*/%])\s*(.+)$"
)
# Named node reference: $('Node Name').item.json.field or $('Node Name').first.json.field
_NAMED_NODE_RE = re.compile(r"\$\(\s*['\"](.+?)['\"]\s*\)\s*\.\s*(?:item|first)\s*\.")

_ARITH_OPS = {
    "+": operator.add,
    "-": operator.sub,
    "*": operator.mul,
    "/": operator.truediv,
    "%": operator.mod,
}


def _lookup(path: str, context: dict[str, Any]) -> Any:
    """Resolve a dotted path with optional array index, e.g. 'items[0]' or 'a.b[2]'."""
    clean_path = path.replace("?.", ".").replace("?[", "[")
    # Check for array index at the end
    idx_match = _INDEX_RE.match(clean_path)
    if idx_match:
        base_path = idx_match.group(1)
        idx = int(idx_match.group(2))
        value = _resolve_path(base_path, context)
        if isinstance(value, list) and 0 <= idx < len(value):
            return value[idx]
        return None
    return _resolve_path(clean_path, context)


def _path_keys(path: str) -> list[Any] | None:
    """Tokenize 'a.b[0]["My Node"].c' into ['a','b',0,'My Node','c'].

    Returns None for malformed paths, unsafe (dunder) keys, or paths
    deeper than MAX_PATH_DEPTH * 2 segments.
    """
    clean_path = path.replace("?.", ".").replace("?[", "[")
    parts = clean_path.split(".")
    if not parts or len(parts) > MAX_PATH_DEPTH * 2:
        return None
    keys: list[Any] = []
    for part in parts:
        m = _SEGMENT_RE.match(part)
        if not m:
            return None
        base, brackets = m.group(1), m.group(2)
        if base:
            keys.append(base)
        if brackets:
            for tok in _BRACKET_RE.findall(brackets):
                tok = tok.strip()
                if re.fullmatch(r"-?\d+", tok):
                    keys.append(int(tok))
                elif len(tok) >= 2 and tok[0] in "\"'" and tok[-1] == tok[0]:
                    inner = tok[1:-1]
                    if _DUNDER_RE.match(inner):
                        return None
                    keys.append(inner)
                else:
                    if _DUNDER_RE.match(tok):
                        return None
                    keys.append(tok)
    if any(isinstance(k, str) and _DUNDER_RE.match(k) for k in keys):
        return None
    return keys


def _resolve_path(path: str, context: dict[str, Any]) -> Any:
    """Resolve a dotted/bracketed path against context.

    Supports nested fields, arrays (numeric index), quoted string keys
    ($node["My Node"].json), and `.length` on lists. Dunder keys are
    refused and depth is capped for safety.
    """
    keys = _path_keys(path)
    if not keys:
        return None
    root, rest = keys[0], keys[1:]
    if not isinstance(root, str):
        return None
    value = context.get(root)
    if value is None:
        return None
    for key in rest[:MAX_PATH_DEPTH]:
        if isinstance(key, int):
            if isinstance(value, list) and 0 <= key < len(value):
                value = value[key]
            else:
                return None
        elif isinstance(key, str) and key == "length" and isinstance(value, list):
            value = len(value)
        elif isinstance(value, dict):
            value = value.get(key)
        else:
            return None
        if value is None:
            return None
    return value


def _coerce(rendered: str) -> Any:
    """Try to convert a fully-rendered scalar back to its native type.

    Fast-path order (most common first):
    1. Non-numeric strings (vast majority) -> skip int/float attempts entirely
    2. Boolean / null literals
    3. Integer (only if string is all digits / starts with - and digits)
    4. Float (only if string contains a decimal point or exponent marker)
    """
    if not rendered:
        return rendered
    lowered = rendered.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered == "null":
        return None
    # Fast-path: skip numeric conversion for strings that obviously cannot be numbers
    first_ch = rendered[0]
    might_be_numeric = first_ch.isdigit() or (first_ch in "-+" and len(rendered) > 1)
    if not might_be_numeric:
        return rendered
    # Integer fast-path: only try int() when no decimal point or exponent present
    if "." not in rendered and "e" not in lowered:
        try:
            return int(rendered)
        except ValueError:
            pass
    # Float: only try when a decimal point or exponent is present
    if "." in rendered or "e" in lowered:
        try:
            return float(rendered)
        except ValueError:
            pass
    return rendered


def _to_number(val: Any) -> float | None:
    """Convert a value to a number if possible."""
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        try:
            return float(val)
        except ValueError:
            return None
    return None


def _apply_pipe(func_name: str, value: Any, args_str: str = "") -> Any:
    """Apply a pipe operation to a value (string ops + type validators)."""
    if func_name == "typeof":
        if value is None:
            return "null"
        if isinstance(value, bool):
            return "boolean"
        if isinstance(value, (int, float)):
            return "number"
        if isinstance(value, str):
            return "string"
        if isinstance(value, list):
            return "array"
        if isinstance(value, dict):
            return "object"
        return "unknown"
    if value is None:
        return None
    if func_name == "int":
        try:
            return int(float(value))  # "3.0" -> 3, rejects junk via ValueError below
        except (TypeError, ValueError):
            return None
    if func_name == "float":
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
    if func_name == "bool":
        return bool(value)
    if func_name == "typeof":
        if value is None:
            return "null"
        if isinstance(value, bool):
            return "boolean"
        if isinstance(value, (int, float)):
            return "number"
        if isinstance(value, str):
            return "string"
        if isinstance(value, list):
            return "array"
        if isinstance(value, dict):
            return "object"
        return "unknown"
    s = str(value)
    if func_name == "upper":
        return s.upper()
    if func_name == "lower":
        return s.lower()
    if func_name == "trim":
        return s.strip()
    if func_name == "length":
        return len(s)
    if func_name == "contains":
        # Parse quoted arg: contains("ali") -> "ali"
        arg = args_str.strip().strip("\"'")
        return arg in s
    if func_name == "replace":
        # Parse two quoted args: replace("old", "new")
        parts = [p.strip().strip("\"'") for p in args_str.split(",", 1)]
        if len(parts) == 2:
            return s.replace(parts[0], parts[1])
        return s
    return s


def build_context(
    input_items: list[dict[str, Any]],
    node_results: dict[str, dict[str, list[dict[str, Any]]]],
    workflow_id: str,
    execution_id: str,
    credentials: dict[str, Any] | None = None,
    env_vars: dict[str, str] | None = None,
    node_name_map: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build expression context.

    Args:
        node_name_map: Optional mapping of display_name -> node_id for
                       named ``$('Node Name')`` expressions.
    """
    first = input_items[0] if input_items else {}
    node_ctx: dict[str, Any] = {}
    for node_id, by_handle in node_results.items():
        main_items = by_handle.get("main") or []
        node_ctx[node_id] = {"json": main_items[0] if main_items else None}
    return {
        "$json": first,
        "$node": node_ctx,
        "$cred": credentials or {},
        "$env": env_vars or {},
        "$workflow": {"id": workflow_id},
        "$execution": {"id": execution_id},
        "$now": datetime.now(timezone.utc).isoformat(),
        "_node_name_map": node_name_map or {},
    }


def _edit_distance(a: str, b: str) -> int:
    """Levenshtein edit distance between two strings (for fuzzy name matching)."""
    if len(a) < len(b):
        return _edit_distance(b, a)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a):
        curr = [i + 1]
        for j, cb in enumerate(b):
            cost = 0 if ca == cb else 1
            curr.append(min(prev[j + 1] + 1, curr[j] + 1, prev[j] + cost))
        prev = curr
    return prev[-1]


def _convert_named_node_expressions(expr: str, context: dict[str, Any]) -> str:
    """Convert named node $('Node Name').item.json.field to $node.id.json.field."""
    name_map = context.get("_node_name_map", {})
    if not name_map:
        return expr

    def _replace_named(m: re.Match) -> str:
        node_name = m.group(1)
        # 1. Exact match
        node_id = name_map.get(node_name) or name_map.get(node_name.lower())
        if not node_id:
            # 2. Case-insensitive scan
            lower_name = node_name.lower()
            for key, val in name_map.items():
                if key.lower() == lower_name:
                    node_id = val
                    break
        if not node_id:
            # 3. Fuzzy match: find closest name (edit distance <= 3)
            lower_name = node_name.lower()
            best_dist = 4  # max threshold
            for key, val in name_map.items():
                dist = _edit_distance(key.lower(), lower_name)
                if dist < best_dist:
                    best_dist = dist
                    node_id = val
            if best_dist > 3:
                node_id = None  # too far, don't match
        if node_id:
            return f"$node.{node_id}."
        # Fallback: try the name as-is (might be a node ID already)
        return f"$node.{node_name}."

    return _NAMED_NODE_RE.sub(_replace_named, expr)


def resolve(value: Any, context: dict[str, Any]) -> Any:
    """Resolve expressions in a parameter value (recurses dicts/lists)."""
    if isinstance(value, str):
        if not _EXPR_RE.search(value):
            return value
        # Convert $('Node Name').item.json.field to $node.id.json.field
        value = _convert_named_node_expressions(value, context)
        # Strip leading '=' used in assignment expressions (e.g. "={{$json.x}}")
        stripped = value
        if value.lstrip().startswith("={"):
            stripped = value.lstrip()[1:]
        rendered = _EXPR_RE.sub(lambda m: _render(m.group(1), context), stripped)
        if rendered != stripped:
            match = _EXPR_RE.fullmatch(stripped.strip())
            if match:
                return _coerce(rendered)
        return rendered
    if isinstance(value, dict):
        return {k: resolve(v, context) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve(v, context) for v in value]
    return value


def _render(expr: str, context: dict[str, Any]) -> str:
    """Render a single expression to string."""
    expr = expr.strip()

    # 1. Ternary: cond ? a : b
    ternary_m = _TERNARY_RE.match(expr)
    if ternary_m:
        cond_str = ternary_m.group(1).strip()
        true_expr = ternary_m.group(2).strip()
        false_expr = ternary_m.group(3).strip()
        cond_val = _eval_expr(cond_str, context)
        chosen = true_expr if cond_val else false_expr
        result = _eval_expr(chosen, context)
        return str(result) if result is not None else ""

    # 2. Coalesce: a ?? b
    coalesce_m = _COALESCE_RE.match(expr)
    if coalesce_m:
        left_str = coalesce_m.group(1).strip()
        right_str = coalesce_m.group(2).strip()
        left_val = _eval_expr(left_str, context)
        if left_val is not None:
            return str(left_val)
        right_val = _eval_expr(right_str, context)
        return str(right_val) if right_val is not None else ""

    # 3. Logical OR: a || b
    or_m = _LOGIC_RE.match(expr)
    if or_m and or_m.group(2) == "||":
        left_val = _eval_expr(or_m.group(1).strip(), context)
        if left_val:
            return str(left_val)
        right_val = _eval_expr(or_m.group(3).strip(), context)
        return str(right_val) if right_val is not None else ""

    # 4. Logical AND: a && b
    and_m = _LOGIC_RE.match(expr)
    if and_m and and_m.group(2) == "&&":
        left_val = _eval_expr(and_m.group(1).strip(), context)
        if not left_val:
            return str(left_val) if left_val is not None else ""
        right_val = _eval_expr(and_m.group(3).strip(), context)
        return str(right_val) if right_val is not None else ""

    # 5. Negation: !a
    negate_m = _NEGATE_RE.match(expr)
    if negate_m:
        inner_val = _eval_expr(negate_m.group(1).strip(), context)
        return str(not inner_val)

    # 6. Comparison: ==, !=, >, <, >=, <=
    cmp_m = _COMPARE_RE.match(expr)
    if cmp_m:
        left_val = _eval_expr(cmp_m.group(1).strip(), context)
        op_str = cmp_m.group(2)
        right_val = _eval_expr(cmp_m.group(3).strip(), context)
        result = _compare(left_val, op_str, right_val)
        return str(result)

    # 7. Arithmetic: +, -, *, /, %
    arith_m = _ARITH_RE.match(expr)
    if arith_m:
        left_val = _eval_expr(arith_m.group(1).strip(), context)
        op_char = arith_m.group(2)
        right_val = _eval_expr(arith_m.group(3).strip(), context)
        result = _arith(op_char, left_val, right_val)
        if result is not None:
            return str(result)

    # 8. Pipe operations: value | func(args)
    pipe_m = _PIPE_RE.match(expr)
    if pipe_m:
        base_path = pipe_m.group(1).strip()
        func_name = pipe_m.group(2)
        args_str = pipe_m.group(3) or ""
        # Check if base_path is a pipe chain
        inner_val = _eval_expr(base_path, context)
        return str(_apply_pipe(func_name, inner_val, args_str))

    # 9. Simple path lookup
    resolved = _lookup(expr, context)
    if resolved is None:
        if "?." in expr or "?[" in expr:
            return ""
        return f"{{{{ {expr} }}}}"
    return str(resolved)


def _eval_expr(expr: str, context: dict[str, Any]) -> Any:
    """Evaluate an expression and return its Python value (not string-rendered)."""
    expr = expr.strip()

    # Handle quoted string literals: "hello" or 'hello'
    if len(expr) >= 2 and expr[0] in ('"', "'") and expr[-1] == expr[0]:
        return expr[1:-1]

    # Handle numeric literals
    try:
        return int(expr)
    except ValueError:
        pass
    try:
        return float(expr)
    except ValueError:
        pass

    # Handle boolean/null literals
    if expr == "true":
        return True
    if expr == "false":
        return False
    if expr == "null":
        return None

    # Ternary
    ternary_m = _TERNARY_RE.match(expr)
    if ternary_m:
        cond_val = _eval_expr(ternary_m.group(1).strip(), context)
        if cond_val:
            return _eval_expr(ternary_m.group(2).strip(), context)
        return _eval_expr(ternary_m.group(3).strip(), context)

    # Coalesce
    coalesce_m = _COALESCE_RE.match(expr)
    if coalesce_m:
        left_val = _eval_expr(coalesce_m.group(1).strip(), context)
        if left_val is not None:
            return left_val
        return _eval_expr(coalesce_m.group(2).strip(), context)

    # Logical OR
    or_m = _LOGIC_RE.match(expr)
    if or_m and or_m.group(2) == "||":
        left_val = _eval_expr(or_m.group(1).strip(), context)
        if left_val:
            return left_val
        return _eval_expr(or_m.group(3).strip(), context)

    # Logical AND
    and_m = _LOGIC_RE.match(expr)
    if and_m and and_m.group(2) == "&&":
        left_val = _eval_expr(and_m.group(1).strip(), context)
        if not left_val:
            return left_val
        return _eval_expr(and_m.group(3).strip(), context)

    # Negation
    negate_m = _NEGATE_RE.match(expr)
    if negate_m:
        inner_val = _eval_expr(negate_m.group(1).strip(), context)
        return not inner_val

    # Comparison
    cmp_m = _COMPARE_RE.match(expr)
    if cmp_m:
        left_val = _eval_expr(cmp_m.group(1).strip(), context)
        op_str = cmp_m.group(2)
        right_val = _eval_expr(cmp_m.group(3).strip(), context)
        return _compare(left_val, op_str, right_val)

    # Arithmetic
    arith_m = _ARITH_RE.match(expr)
    if arith_m:
        left_val = _eval_expr(arith_m.group(1).strip(), context)
        op_char = arith_m.group(2)
        right_val = _eval_expr(arith_m.group(3).strip(), context)
        return _arith(op_char, left_val, right_val)

    # Pipe operations
    pipe_m = _PIPE_RE.match(expr)
    if pipe_m:
        base_path = pipe_m.group(1).strip()
        func_name = pipe_m.group(2)
        args_str = pipe_m.group(3) or ""
        inner_val = _eval_expr(base_path, context)
        return _apply_pipe(func_name, inner_val, args_str)

    # Simple path lookup
    return _lookup(expr, context)


def _compare(left: Any, op: str, right: Any) -> bool:
    """Compare two values with the given operator."""
    # Handle None comparisons specially
    if left is None or right is None:
        if op == "==":
            return left == right
        if op == "!=":
            return left != right
        return False

    # Try numeric comparison
    left_num = _to_number(left)
    right_num = _to_number(right)
    if left_num is not None and right_num is not None:
        if op == "==":
            return left_num == right_num
        if op == "!=":
            return left_num != right_num
        if op == ">":
            return left_num > right_num
        if op == "<":
            return left_num < right_num
        if op == ">=":
            return left_num >= right_num
        if op == "<=":
            return left_num <= right_num

    # String comparison
    left_str = str(left) if left is not None else ""
    right_str = str(right) if right is not None else ""
    if op == "==":
        return left_str == right_str
    if op == "!=":
        return left_str != right_str
    if op == ">":
        return left_str > right_str
    if op == "<":
        return left_str < right_str
    if op == ">=":
        return left_str >= right_str
    if op == "<=":
        return left_str <= right_str

    return False


def _arith(op: str, left: Any, right: Any) -> Any:
    """Perform arithmetic on two values."""
    func = _ARITH_OPS.get(op)
    if func is None:
        return None
    left_num = _to_number(left)
    right_num = _to_number(right)
    if left_num is None or right_num is None:
        return None
    if op in ("/", "%") and right_num == 0:
        return None  # avoid division by zero
    try:
        result = func(left_num, right_num)
        # Return int if result is a whole number
        if isinstance(result, float) and result == int(result):
            return int(result)
        return result
    except (ValueError, OverflowError):
        return None


def interpolate(template: str, base_item: dict[str, Any] | None = None, env_vars: dict[str, str] | None = None) -> Any:
    """Convenience helper to interpolate {{ ... }} expressions against an item and env."""
    context: dict[str, Any] = {
        "$json": (base_item or {}).get("json", base_item or {}),
        "$env": env_vars or {},
    }
    return resolve(template, context)

