"""Shared condition model + evaluator.

Supports:
- Multiple conditions with AND/OR combinator
- String, number, boolean, null, array, date types
- Convert types where required
- All required operators
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from app.engine.errors import NodeExecutionError


# Operator definitions by type
STRING_OPERATORS = [
    "is equal to", "is not equal to",
    "contains", "does not contain",
    "starts with", "does not start with",
    "ends with", "does not end with",
    "matches regex", "does not match regex",
    "is empty", "is not empty",
]

NUMBER_OPERATORS = [
    "is equal to", "is not equal to",
    "is greater than", "is greater than or equal to",
    "is less than", "is less than or equal to",
    "is empty", "is not empty",
]

BOOLEAN_OPERATORS = ["is true", "is false"]

NULL_OPERATORS = ["is null", "is not null", "exists", "does not exist"]

ARRAY_OPERATORS = [
    "contains", "does not contain",
    "is empty", "is not empty",
]

DATE_OPERATORS = [
    "is equal to", "is not equal to",
    "is before", "is after",
    "is before or equal to", "is after or equal to",
    "is empty", "is not empty",
]

ALL_OPERATORS = list(set(STRING_OPERATORS + NUMBER_OPERATORS + BOOLEAN_OPERATORS + NULL_OPERATORS + ARRAY_OPERATORS + DATE_OPERATORS))

# For backward compat with old literal operators and LLM dialects
LEGACY_OPERATOR_MAP = {
    # Equality
    "equals": "is equal to",
    "equal": "is equal to",
    "eq": "is equal to",
    "==": "is equal to",
    "=": "is equal to",
    "is": "is equal to",
    "exact": "is equal to",
    "same": "is equal to",
    "not_equals": "is not equal to",
    "not_equal": "is not equal to",
    "neq": "is not equal to",
    "ne": "is not equal to",
    "!=": "is not equal to",
    "!==": "is not equal to",
    "is_not": "is not equal to",
    # Substrings & collections
    "contains": "contains",
    "contain": "contains",
    "does_not_contain": "does not contain",
    "doesnotcontain": "does not contain",
    "not_contains": "does not contain",
    "not_contain": "does not contain",
    "starts_with": "starts with",
    "startswith": "starts with",
    "does_not_start_with": "does not start with",
    "doesnotstartwith": "does not start with",
    "ends_with": "ends with",
    "endswith": "ends with",
    "does_not_end_with": "does not end with",
    "doesnotendwith": "does not end with",
    # Regex
    "regex": "matches regex",
    "matches_regex": "matches regex",
    "matchesregex": "matches regex",
    "matches": "matches regex",
    "match": "matches regex",
    "does_not_match_regex": "does not match regex",
    "doesnotmatchregex": "does not match regex",
    # Numbers / Comparisons
    "greater_than": "is greater than",
    "greaterthan": "is greater than",
    ">": "is greater than",
    "gt": "is greater than",
    "greater_than_or_equal": "is greater than or equal to",
    "greater_than_or_equals": "is greater than or equal to",
    "greaterthanorequal": "is greater than or equal to",
    ">=": "is greater than or equal to",
    "gte": "is greater than or equal to",
    "less_than": "is less than",
    "lessthan": "is less than",
    "<": "is less than",
    "lt": "is less than",
    "less_than_or_equal": "is less than or equal to",
    "less_than_or_equals": "is less than or equal to",
    "lessthanorequal": "is less than or equal to",
    "<=": "is less than or equal to",
    "lte": "is less than or equal to",
    # Empty / Null / Exists / Boolean
    "empty": "is empty",
    "is_empty": "is empty",
    "isempty": "is empty",
    "not_empty": "is not empty",
    "is_not_empty": "is not empty",
    "isnotempty": "is not empty",
    "null": "is null",
    "is_null": "is null",
    "isnull": "is null",
    "not_null": "is not null",
    "is_not_null": "is not null",
    "isnotnull": "is not null",
    "exists": "exists",
    "exist": "exists",
    "does_not_exist": "does not exist",
    "doesnotexist": "does not exist",
    "not_exists": "does not exist",
    "true": "is true",
    "is_true": "is true",
    "istrue": "is true",
    "false": "is false",
    "is_false": "is false",
    "isfalse": "is false",
    # Dates
    "before": "is before",
    "is_before": "is before",
    "isbefore": "is before",
    "after": "is after",
    "is_after": "is after",
    "isafter": "is after",
    "is_before_or_equal_to": "is before or equal to",
    "is_after_or_equal_to": "is after or equal to",
}


class Condition(BaseModel):
    left: Any = ""
    operator: str = "is equal to"
    right: Any = None

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        d = dict(data)
        if "left" not in d or d["left"] is None:
            for k in ("leftValue", "value1", "left_value"):
                if k in d and d[k] is not None:
                    d["left"] = d[k]
                    break
        if "right" not in d or d["right"] is None:
            for k in ("rightValue", "value2", "right_value"):
                if k in d and d[k] is not None:
                    d["right"] = d[k]
                    break
        op = d.get("operator")
        if isinstance(op, dict):
            op = op.get("operation") or op.get("operator") or op.get("type") or "is equal to"
        elif op is None:
            op = d.get("operation") or "is equal to"
        op_str = str(op).strip()
        op_lookup = op_str.lower().replace("-", "_")
        d["operator"] = LEGACY_OPERATOR_MAP.get(op_lookup, LEGACY_OPERATOR_MAP.get(op_str, op_str))
        return d


class ConditionRow(BaseModel):
    id: str = Field(default_factory=lambda: __import__("uuid").uuid4().hex[:8])
    left: Any = ""
    operator: str = "is equal to"
    right: Any = ""
    combinator: Literal["AND", "OR"] = "AND"

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        d = dict(data)
        # 1. Alias left / right fields
        if "left" not in d or d["left"] is None or d["left"] == "":
            for k in ("leftValue", "value1", "left_value", "lhs", "variable"):
                if k in d and d[k] is not None:
                    d["left"] = d[k]
                    break
        if "right" not in d or d["right"] is None or d["right"] == "":
            for k in ("rightValue", "value2", "right_value", "rhs", "value"):
                if k in d and d[k] is not None:
                    d["right"] = d[k]
                    break

        # 2. Clean '={{ expr }}' -> '{{ expr }}'
        for k in ("left", "right"):
            val = d.get(k)
            if isinstance(val, str):
                s = val.strip()
                if s.startswith("={") and s.endswith("}"):
                    d[k] = s[1:]

        # 3. Handle operator (can be dict, e.g. {"operation": "equals", "type": "string"})
        op = d.get("operator")
        if isinstance(op, dict):
            op = op.get("operation") or op.get("operator") or op.get("type") or "is equal to"
        elif op is None:
            op = d.get("operation") or "is equal to"

        op_str = str(op).strip()
        op_lookup = op_str.lower().replace("-", "_")
        d["operator"] = LEGACY_OPERATOR_MAP.get(op_lookup, LEGACY_OPERATOR_MAP.get(op_str, op_str))

        # 4. Handle combinator
        comb = d.get("combinator")
        if isinstance(comb, str):
            comb_upper = comb.strip().upper()
            d["combinator"] = comb_upper if comb_upper in ("AND", "OR") else "AND"

        return d


def _is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and value.strip() == "":
        return True
    if isinstance(value, (list, dict)) and len(value) == 0:
        return True
    return False


def _to_number(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, str):
        s = value.strip()
        if s == "":
            return None
        try:
            # Handle "10", "10.5", "-3", etc.
            return float(s)
        except:
            return None
    return None


def _to_boolean(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        s = value.strip().lower()
        if s in ("true", "1", "yes", "y"):
            return True
        if s in ("false", "0", "no", "n"):
            return False
    if isinstance(value, (int, float)):
        return bool(value)
    return None


def _to_date(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        s = value.strip()
        # Try ISO formats
        for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d", "%m/%d/%Y"):
            try:
                return datetime.strptime(s, fmt)
            except:
                continue
        # Try fromisoformat
        try:
            # Handle Z
            if s.endswith("Z"):
                s = s[:-1] + "+00:00"
            return datetime.fromisoformat(s)
        except:
            pass
    return None


def _compare_string(left: Any, operator: str, right: Any, convert_types: bool, ignore_case: bool = False) -> bool:
    ls = str(left) if left is not None else ""
    rs = str(right) if right is not None else ""
    if ignore_case:
        ls = ls.lower()
        rs = rs.lower()
    # For empty checks, don't convert
    if operator == "is empty":
        return _is_empty(left)
    if operator == "is not empty":
        return not _is_empty(left)
    # For regex, handle accordingly
    if operator == "matches regex":
        try:
            flags = re.IGNORECASE if ignore_case else 0
            return bool(re.search(str(right), str(left) if left is not None else "", flags=flags))
        except re.error as e:
            raise NodeExecutionError(f"Invalid regex '{right}': {e}", code="INVALID_CONDITION", retryable=False) from e
    if operator == "does not match regex":
        try:
            flags = re.IGNORECASE if ignore_case else 0
            return not re.search(str(right), str(left) if left is not None else "", flags=flags)
        except re.error as e:
            raise NodeExecutionError(f"Invalid regex '{right}': {e}", code="INVALID_CONDITION", retryable=False) from e
    if operator == "is equal to":
        if not convert_types and type(left) != type(right):
            # Strict: different types are not equal
            # But allow int vs float as same numeric type
            if isinstance(left, (int, float)) and isinstance(right, (int, float)):
                return float(left) == float(right)
            # Allow boolean vs string "true"/"false" comparison
            if isinstance(left, bool) and isinstance(right, str):
                return str(left).lower() == right.strip().lower()
            if isinstance(right, bool) and isinstance(left, str):
                return left.strip().lower() == str(right).lower()
            return False
        # Handle boolean vs string even when types match (both strings after conversion)
        if isinstance(left, bool) and isinstance(right, str):
            return str(left).lower() == right.strip().lower()
        if isinstance(right, bool) and isinstance(left, str):
            return left.strip().lower() == str(right).lower()
        return ls == rs
    if operator == "is not equal to":
        if not convert_types and type(left) != type(right):
            if isinstance(left, (int, float)) and isinstance(right, (int, float)):
                return float(left) != float(right)
            # Allow boolean vs string "true"/"false" comparison
            if isinstance(left, bool) and isinstance(right, str):
                return str(left).lower() != right.strip().lower()
            if isinstance(right, bool) and isinstance(left, str):
                return left.strip().lower() != str(right).lower()
            return True
        if isinstance(left, bool) and isinstance(right, str):
            return str(left).lower() != right.strip().lower()
        if isinstance(right, bool) and isinstance(left, str):
            return left.strip().lower() != str(right).lower()
        return ls != rs
    if operator == "contains":
        return rs in ls
    if operator == "does not contain":
        return rs not in ls
    if operator == "starts with":
        return ls.startswith(rs)
    if operator == "does not start with":
        return not ls.startswith(rs)
    if operator == "ends with":
        return ls.endswith(rs)
    if operator == "does not end with":
        return not ls.endswith(rs)
    raise NodeExecutionError(f"Unsupported string operator '{operator}'", code="INVALID_CONDITION", retryable=False)


def _compare_number(left: Any, operator: str, right: Any, convert_types: bool) -> bool:
    # Handle empty
    if operator == "is empty":
        return _is_empty(left)
    if operator == "is not empty":
        return not _is_empty(left)
    # Convert types if required
    if convert_types:
        ln = _to_number(left)
        rn = _to_number(right)
        if ln is None or rn is None:
            # If conversion fails and convertTypes is on, try string comparison as fallback? No, should be false
            # For is equal to with convertTypes, "10" == 10 should be true
            # If one is not a number, then is equal to should be false
            if operator == "is equal to":
                return str(left) == str(right)
            if operator == "is not equal to":
                return str(left) != str(right)
            raise NodeExecutionError(f"Cannot convert '{left}' or '{right}' to number", code="INVALID_CONDITION", retryable=False)
    else:
        # Strict: both must be numbers
        if not isinstance(left, (int, float)) or isinstance(left, bool):
            raise NodeExecutionError(f"Left value '{left}' is not a number (convert types is OFF)", code="INVALID_CONDITION", retryable=False)
        if not isinstance(right, (int, float)) or isinstance(right, bool):
            rn = _to_number(right)
            if rn is None:
                raise NodeExecutionError(f"Right value '{right}' is not a number (convert types is OFF)", code="INVALID_CONDITION", retryable=False)
        else:
            rn = float(right)
        ln = float(left)
    # Now compare
    if operator == "is equal to":
        return ln == rn
    if operator == "is not equal to":
        return ln != rn
    if operator == "is greater than":
        return ln > rn
    if operator == "is greater than or equal to":
        return ln >= rn
    if operator == "is less than":
        return ln < rn
    if operator == "is less than or equal to":
        return ln <= rn
    raise NodeExecutionError(f"Unsupported number operator '{operator}'", code="INVALID_CONDITION", retryable=False)


def _compare_boolean(left: Any, operator: str, right: Any, convert_types: bool) -> bool:
    if convert_types:
        lb = _to_boolean(left)
        if lb is None:
            raise NodeExecutionError(f"Cannot convert '{left}' to boolean", code="INVALID_CONDITION", retryable=False)
    else:
        if not isinstance(left, bool):
            raise NodeExecutionError(f"Left value '{left}' is not a boolean (convert types is OFF)", code="INVALID_CONDITION", retryable=False)
        lb = left
    if operator == "is true":
        return lb is True
    if operator == "is false":
        return lb is False
    # For is equal to with boolean, handle string right values like "true"/"false"
    if operator == "is equal to":
        if convert_types:
            rb = _to_boolean(right)
            return lb == rb
        # Allow comparing boolean to string "true"/"false"
        if isinstance(right, str):
            return lb == (right.strip().lower() == "true")
        return left == right
    if operator == "is not equal to":
        if convert_types:
            rb = _to_boolean(right)
            return lb != rb
        if isinstance(right, str):
            return lb != (right.strip().lower() == "true")
        return left != right
    raise NodeExecutionError(f"Unsupported boolean operator '{operator}'", code="INVALID_CONDITION", retryable=False)


def _compare_null(left: Any, operator: str, right: Any, convert_types: bool) -> bool:
    if operator == "is null":
        return left is None
    if operator == "is not null":
        return left is not None
    if operator == "exists":
        return left is not None
    if operator == "does not exist":
        return left is None
    raise NodeExecutionError(f"Unsupported null operator '{operator}'", code="INVALID_CONDITION", retryable=False)


def _compare_array(left: Any, operator: str, right: Any, convert_types: bool) -> bool:
    if operator == "is empty":
        return _is_empty(left)
    if operator == "is not empty":
        return not _is_empty(left)
    if not isinstance(left, (list, tuple)):
        if _is_empty(left):
            return operator in ("does not contain", "is empty")
        raise NodeExecutionError("Left value is not an array", code="INVALID_CONDITION", retryable=False)
    if operator == "contains":
        return right in left or str(right) in [str(x) for x in left]
    if operator == "does not contain":
        return right not in left and str(right) not in [str(x) for x in left]
    # Length comparisons
    if operator in ("is equal to", "is not equal to", "is greater than", "is greater than or equal to", "is less than", "is less than or equal to"):
        # Compare length
        ln = len(left)
        rn = _to_number(right)
        if rn is None:
            raise NodeExecutionError(f"Right value '{right}' is not a number for length comparison", code="INVALID_CONDITION", retryable=False)
        rn = int(rn)
        if operator == "is equal to":
            return ln == rn
        if operator == "is not equal to":
            return ln != rn
        if operator == "is greater than":
            return ln > rn
        if operator == "is greater than or equal to":
            return ln >= rn
        if operator == "is less than":
            return ln < rn
        if operator == "is less than or equal to":
            return ln <= rn
    raise NodeExecutionError(f"Unsupported array operator '{operator}'", code="INVALID_CONDITION", retryable=False)


def _compare_date(left: Any, operator: str, right: Any, convert_types: bool) -> bool:
    if operator == "is empty":
        return _is_empty(left)
    if operator == "is not empty":
        return not _is_empty(left)
    # Convert to date
    ld = _to_date(left)
    rd = _to_date(right)
    if convert_types:
        if ld is None or rd is None:
            # Try string comparison as fallback for is equal to
            if operator == "is equal to":
                return str(left) == str(right)
            if operator == "is not equal to":
                return str(left) != str(right)
            raise NodeExecutionError(f"Cannot convert '{left}' or '{right}' to date", code="INVALID_CONDITION", retryable=False)
    else:
        if ld is None or rd is None:
            raise NodeExecutionError("Left or right value is not a valid date (convert types is OFF)", code="INVALID_CONDITION", retryable=False)
    if operator == "is equal to":
        return ld == rd
    if operator == "is not equal to":
        return ld != rd
    if operator == "is before":
        return ld < rd
    if operator == "is after":
        return ld > rd
    if operator == "is before or equal to":
        return ld <= rd
    if operator == "is after or equal to":
        return ld >= rd
    raise NodeExecutionError(f"Unsupported date operator '{operator}'", code="INVALID_CONDITION", retryable=False)


def _detect_type(value: Any, operator: str) -> str:
    """Detect type for operator routing."""
    # Check operator first for explicit type hints
    if operator in ("is true", "is false"):
        return "boolean"
    if operator in ("is null", "is not null", "exists", "does not exist"):
        return "null"
    if operator in ("is empty", "is not empty") and isinstance(value, (list, dict)):
        # Could be array or string, check value type
        if isinstance(value, list):
            return "array"
        return "string"
    if operator in ("is before", "is after", "is before or equal to", "is after or equal to"):
        return "date"
    # For contains, check if left is array
    if operator in ("contains", "does not contain") and isinstance(value, list):
        return "array"
    # Try to detect number
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return "number"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, list):
        return "array"
    if isinstance(value, datetime):
        return "date"
    # Default to string
    return "string"


def evaluate_condition(left: Any, operator: str, right: Any, convert_types: bool = False, left_type_hint: str | None = None, ignore_case: bool = False) -> bool:
    """Evaluate a single condition with type handling."""
    # Normalize operator via legacy map
    op = LEGACY_OPERATOR_MAP.get(operator, operator)
    # Handle empty / null operators that don't need right value
    if op in ("is empty", "is not empty", "is null", "is not null", "exists", "does not exist", "is true", "is false"):
        # For these, right is ignored
        # Detect type based on left and operator
        detected = left_type_hint or _detect_type(left, op)
        if detected == "boolean" or op in ("is true", "is false"):
            return _compare_boolean(left, op, right, convert_types)
        if detected == "null" or op in ("is null", "is not null", "exists", "does not exist"):
            return _compare_null(left, op, right, convert_types)
        if detected == "array":
            return _compare_array(left, op, right, convert_types)
        if detected == "date":
            return _compare_date(left, op, right, convert_types)
        # Default to string for empty checks
        return _compare_string(left, op, right, convert_types, ignore_case=ignore_case)

    # For other operators, detect types
    # Try to infer type from values
    left_is_num = isinstance(left, (int, float)) and not isinstance(left, bool)
    right_is_num = isinstance(right, (int, float)) and not isinstance(right, bool)
    # Also check if string can be converted to number when convertTypes is on
    # For now, route based on operator
    if op in ("is greater than", "is greater than or equal to", "is less than", "is less than or equal to"):
        # Could be number or date
        # Check if either is date
        ld = _to_date(left) if isinstance(left, str) else None
        rd = _to_date(right) if isinstance(right, str) else None
        if ld is not None and rd is not None and (isinstance(left, str) or isinstance(right, str)):
            # Both are dates (or one is date string)
            # Prefer date if both can be parsed as date
            # But also check if they are numbers
            # For now, if both look like dates, use date comparison
            # Simple heuristic: if string contains "-" and is date-like
            if isinstance(left, str) and "-" in left and _to_date(left) is not None and isinstance(right, str) and "-" in right and _to_date(right) is not None:
                return _compare_date(left, op, right, convert_types)
        # Otherwise number
        return _compare_number(left, op, right, convert_types)
    if op in ("contains", "does not contain"):
        # Could be string or array
        if isinstance(left, list):
            return _compare_array(left, op, right, convert_types)
        return _compare_string(left, op, right, convert_types, ignore_case=ignore_case)
    if op in ("starts with", "does not start with", "ends with", "does not end with", "matches regex", "does not match regex"):
        return _compare_string(left, op, right, convert_types, ignore_case=ignore_case)
    if op in ("is equal to", "is not equal to"):
        # For equal, try to handle numbers, booleans, dates
        # If both are numbers or can be converted, use number
        # If both are booleans, use boolean
        # If both are dates, use date
        # Otherwise string
        # Check boolean
        if isinstance(left, bool) or isinstance(right, bool):
            return _compare_boolean(left, op, right, convert_types)
        # Check date
        ld = _to_date(left)
        rd = _to_date(right)
        if ld is not None and rd is not None and (isinstance(left, str) or isinstance(right, str) or isinstance(left, datetime) or isinstance(right, datetime)):
            # Only use date if original values look date-like
            if isinstance(left, str) and isinstance(right, str) and "-" in left and "-" in right:
                return _compare_date(left, op, right, convert_types)
            if isinstance(left, datetime) or isinstance(right, datetime):
                return _compare_date(left, op, right, convert_types)
        # Check number
        if left_is_num and right_is_num:
            return _compare_number(left, op, right, convert_types)
        if convert_types:
            # Try number conversion for is equal to with convertTypes
            ln = _to_number(left)
            rn = _to_number(right)
            if ln is not None and rn is not None:
                return _compare_number(left, op, right, convert_types)
            # Try boolean
            lb = _to_boolean(left)
            rb = _to_boolean(right)
            if lb is not None and rb is not None and (isinstance(left, str) or isinstance(right, str)):
                # Only if one is boolean string
                if str(left).lower() in ("true","false") or str(right).lower() in ("true","false"):
                    return _compare_boolean(left, op, right, convert_types)
        # Default to string
        return _compare_string(left, op, right, convert_types, ignore_case=ignore_case)
    # Fallback to string
    return _compare_string(left, op, right, convert_types, ignore_case=ignore_case)


def evaluate(condition: Condition, item: dict[str, Any], convert_types: bool = False) -> bool:
    """Legacy single condition evaluator (for backward compat)."""
    op = LEGACY_OPERATOR_MAP.get(condition.operator, condition.operator)
    left = resolve_left(condition.left, item)
    right = condition.right
    # Handle right being an expression string that needs resolving? The caller should have resolved it via expressions
    # But we handle simple $json. case here for legacy
    return evaluate_condition(left, op, right, convert_types)


def resolve_left(left: Any, item: dict[str, Any]) -> Any:
    if isinstance(left, str):
        stripped = left.strip()
        if stripped.startswith("{{") and stripped.endswith("}}"):
            stripped = stripped[2:-2].strip()
        if stripped.startswith("$json."):
            key = stripped[len("$json."):]
            parts = key.split(".")
            value: Any = item
            for part in parts:
                if isinstance(value, dict):
                    value = value.get(part)
                else:
                    return None
            return value
    return left


def coerce(value: Any, target: Any) -> Any:
    if isinstance(target, bool):
        return value in (True, "true", "True", 1, "1")
    if isinstance(target, (int, float)):
        return float(value)
    return value


# New multi-condition evaluator
def evaluate_conditions(conditions: list[ConditionRow], item: dict[str, Any], convert_types: bool = False, ignore_case: bool = False) -> bool:
    """Evaluate multiple conditions with AND/OR combinators."""
    if not conditions:
        return False
    # Resolve expressions for each condition's left and right via simple $json handling
    # The caller (if_condition node) should have already resolved expressions via expressions.resolve,
    # but we handle any remaining $json. strings here for safety.
    results: list[bool] = []
    combinators: list[str] = []
    for idx, cond in enumerate(conditions):
        left_val = cond.left
        right_val = cond.right
        # If left/right are still expression strings (e.g., "={{ $json.age }}"), resolve them.
        # The IF node's run() should have already resolved these via expressions.resolve,
        # but as a safety net we resolve any remaining {{ }} or bare $json. references here.
        from app.engine import expressions as _expr_mod

        def _resolve_val(val: Any, item_dict: dict[str, Any]) -> Any:
            """Resolve a condition value that may contain expressions or $json refs."""
            if not isinstance(val, str):
                return val
            # {{ $json.field }} or ={{ $json.field }}
            stripped_s = val.strip()
            if stripped_s.startswith("={"):
                stripped_s = stripped_s[1:]
            if "{{" in stripped_s:
                resolved = _expr_mod.resolve(stripped_s, {"$json": item_dict})
                if not (isinstance(resolved, str) and "{{" in resolved):
                    return resolved
                return val
            # bare $json.field reference
            if stripped_s.startswith("$json."):
                _field = stripped_s[len("$json."):]
                _parts = _field.split(".")
                r: Any = item_dict
                for _p in _parts:
                    if isinstance(r, dict):
                        r = r.get(_p)
                    else:
                        return None
                return r
            return val

        left_val = _resolve_val(left_val, item)
        right_val = _resolve_val(right_val, item)
        # Evaluate single condition
        res = evaluate_condition(left_val, cond.operator, right_val, convert_types, ignore_case=ignore_case)
        results.append(res)
        if idx > 0:
            combinators.append(cond.combinator)
        else:
            combinators.append("AND")  # First has no combinator, but we treat as AND

    # Apply AND/OR logic left-to-right (no precedence)
    if not results:
        return False
    current = results[0]
    for i in range(1, len(results)):
        comb = combinators[i] if i < len(combinators) else "AND"
        if comb == "OR":
            current = current or results[i]
        else:  # AND
            current = current and results[i]
    return current
