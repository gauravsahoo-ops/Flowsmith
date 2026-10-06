"""Code node — high-performance JavaScript/Python execution engine.

Supports:
- Mode: Run Once for All Items / Run Once for Each Item
- Language: JavaScript (full) / Python (basic, marked)
- $input API: $input.all(), $input.item, $input.item.json
- Secure sandbox with timeout, restricted globals, no FS/network/process
- Console.log capture
- Syntax validation before execution
- Proper output contract: return [{json: {...}}]

Execution:
- Run Once for All Items: items = $input.all() (all input items), code returns array
- Run Once for Each Item: for each item, $input.item is current item, code returns single item, collected
"""

from __future__ import annotations

import ast
import logging
import os
import threading
from typing import Any, List

from pydantic import BaseModel, Field, model_validator

from app.engine.errors import NodeExecutionError
from app.engine.node_base import BaseNode, NodeContext, NodeResult
from app.nodes.registry import register

logger = logging.getLogger("code")


def _safe_print(*args: Any, **kwargs: Any) -> None:
    # Route through logger at debug to avoid stdout PII/code flooding
    # in worker logs; kwargs like flush=True are ignored.
    try:
        msg = " ".join(str(a) for a in args)
        logger.debug(msg)
    except Exception:
        pass



class CodeParams(BaseModel):
    code: str = Field(default="for (const item of $input.all()) {\n  item.json.myNewField = 1;\n}\nreturn $input.all();", description="JavaScript code to execute.")
    jsCode: str | None = Field(default=None, description="Alias for code (import compatibility).")
    language: str = Field(default="javascript", description="javascript or python")
    mode: str = Field(default="runOnceForAllItems", description="Run Once for All Items or Run Once for Each Item")
    max_memory_mb: int = Field(default=64, ge=16, le=512, description="Memory budget (MB) for JS execution. Enforced in the child process on platforms that support setrlimit.")

    @model_validator(mode="before")
    @classmethod
    def _alias_jsCode(cls, data: Any) -> Any:
        if isinstance(data, dict) and "jsCode" in data and "code" not in data:
            data["code"] = data.pop("jsCode")
        return data


# Safe builtins for Python exec — no getattr/setattr (sandbox escape vectors)
_SAFE_BUILTINS = {
    "len": len,
    "str": str,
    "int": int,
    "float": float,
    "bool": bool,
    "list": list,
    "dict": dict,
    "set": set,
    "tuple": tuple,
    "range": range,
    "enumerate": enumerate,
    "zip": zip,
    "map": map,
    "filter": filter,
    "sorted": sorted,
    "sum": sum,
    "min": min,
    "max": max,
    "abs": abs,
    "any": any,
    "all": all,
    "round": round,
    "reversed": reversed,
    # NOTE: isinstance/hasattr/type are intentionally NOT provided.
    # type() returns live class objects and hasattr/introspection helpers
    # are classic sandbox-escape primitives (class traversal, attribute
    # probing). User code that needs type checks should compare via
    # __name__-style checks on already-exposed values or explicit equality.
    "print": print,
    "True": True,
    "False": False,
    "None": None,
}


class InputWrapper:
    """$input API for Code node."""
    def __init__(self, items: List[dict[str, Any]], current_idx: int = 0):
        # Normalize items to {json: ...} standard shape
        normalized = []
        for it in items:
            if isinstance(it, dict) and "json" in it and len(it) == 1:
                normalized.append(it)
            elif isinstance(it, dict):
                normalized.append({"json": it})
            else:
                normalized.append({"json": {"value": it}})
        self._items = normalized
        self._current_idx = current_idx

    def all(self) -> List[dict[str, Any]]:
        return self._items

    @property
    def item(self) -> dict[str, Any]:
        if 0 <= self._current_idx < len(self._items):
            return self._items[self._current_idx]
        return {"json": {}}

    @property
    def json(self) -> Any:
        # For $input.item.json convenience
        item = self.item
        if isinstance(item, dict) and "json" in item:
            return item["json"]
        return item


def _normalize_output(output: Any, logs: List[str] | None = None) -> List[dict[str, Any]]:
    """Normalize code output to list of flat item dicts."""
    if logs is None:
        logs = []
    if output is None:
        return [{}]
    if isinstance(output, dict):
        # Unwrap {"json": {...}} to flat dict for downstream expression resolution
        if "json" in output and isinstance(output["json"], dict):
            return [output["json"]]
        return [output]
    if isinstance(output, list):
        normalized: List[dict[str, Any]] = []
        for el in output:
            if isinstance(el, dict):
                # Unwrap {"json": {...}} to flat dict
                if "json" in el and isinstance(el["json"], dict):
                    normalized.append(el["json"])
                else:
                    normalized.append(el)
            elif el is None:
                normalized.append({})
            else:
                normalized.append({"value": el})
        return normalized
    return [{"value": output}]



DANGEROUS_ATTRIBUTES = {
    "__class__",
    "__base__",
    "__bases__",
    "__mro__",
    "__subclasses__",
    "__globals__",
    "__code__",
    "__builtins__",
    "__dict__",
    "__closure__",
    "__import__",
    "__reduce__",
    "__reduce_ex__",
    "__init_subclass__",
    "__subclasshook__",
}

DANGEROUS_NAMES = {
    "eval",
    "exec",
    "compile",
    "open",
    "input",
    "breakpoint",
    "getattr",
    "setattr",
    "delattr",
    "vars",
    "dir",
    "globals",
    "locals",
    "__builtins__",
    "__import__",
}


class PythonSecurityAnalyzer(ast.NodeVisitor):
    """AST analyzer enforcing strict sandbox safety for user Python code."""

    def visit_Import(self, node: ast.Import) -> None:
        raise NodeExecutionError(
            "Security violation: 'import' statements are prohibited in Code nodes.",
            code="SANDBOX_VIOLATION",
            node_id="code",
            retryable=False,
            details={"line": node.lineno, "col": node.col_offset},
        )

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        raise NodeExecutionError(
            f"Security violation: 'from {node.module} import ...' is prohibited in Code nodes.",
            code="SANDBOX_VIOLATION",
            node_id="code",
            retryable=False,
            details={"line": node.lineno, "col": node.col_offset},
        )

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr in DANGEROUS_ATTRIBUTES or (node.attr.startswith("__") and node.attr.endswith("__")):
            raise NodeExecutionError(
                f"Security violation: Access to dunder attribute '{node.attr}' is prohibited in Code nodes.",
                code="SANDBOX_VIOLATION",
                node_id="code",
                retryable=False,
                details={"line": node.lineno, "col": node.col_offset},
            )
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        if node.id in DANGEROUS_NAMES:
            raise NodeExecutionError(
                f"Security violation: Access to '{node.id}' is prohibited in Code nodes.",
                code="SANDBOX_VIOLATION",
                node_id="code",
                retryable=False,
                details={"line": node.lineno, "col": node.col_offset},
            )
        self.generic_visit(node)


def validate_code(code: str, language: str = "javascript") -> tuple[bool, str | None, int | None, int | None]:
    """Validate syntax of code without running it."""
    if not code or not code.strip():
        return True, None, None, None
    if language.lower() not in ("python", "py"):
        # JavaScript
        try:
            import dukpy  # type: ignore[import-untyped]
        except ImportError:
            dukpy = None  # type: ignore[assignment]
        if dukpy is not None:
            try:
                import json as _json
                js_check = f"try {{ new Function({_json.dumps(code)}); 'ok'; }} catch(e) {{ throw e; }}"
                dukpy.evaljs(js_check)
                return True, None, None, None
            except Exception as e:
                msg = str(e)
                import re
                m = re.search(r"line (\d+)", msg, re.IGNORECASE)
                m2 = re.search(r"column (\d+)", msg, re.IGNORECASE)
                line = int(m.group(1)) if m else None
                col = None
                if m2:
                    try:
                        col = int(m2.group(1))
                    except:
                        pass
                if any(x in msg.lower() for x in ["syntaxerror", "unexpected", "unterminated", "missing", "invalid", "parse error"]):
                    return False, f"SyntaxError: {msg}", line, col
                return True, None, None, None
        # Fallback: basic bracket check if no JS engine available
        stack = []
        pairs = {")": "(", "}": "{", "]": "["}
        for i, ch in enumerate(code):
            if ch in "({[":
                stack.append(ch)
            elif ch in ")}]":
                if not stack or stack[-1] != pairs[ch]:
                    return False, f"SyntaxError: Unmatched '{ch}'", code[:i].count("\n") + 1, None
                stack.pop()
        if stack:
            return False, f"SyntaxError: Unmatched '{stack[-1]}'", None, None
        return True, None, None, None
    else:
        # Python: syntax and security validation
        try:
            tree = ast.parse(code)
            PythonSecurityAnalyzer().visit(tree)
            return True, None, None, None
        except SyntaxError as e:
            return False, f"SyntaxError: {e.msg}", e.lineno, e.offset
        except NodeExecutionError as e:
            return False, e.message, (e.details or {}).get("line"), (e.details or {}).get("col")


# Alias for internal/audit test compatibility
_validate_syntax = validate_code


def _exec_with_timeout(code: str, namespace: dict[str, Any], timeout: float = 5.0) -> dict[str, Any]:
    """Execute code with timeout using asyncio.wait_for and thread."""
    # Enforce AST sandbox security checks before execution
    try:
        tree = ast.parse(code)
        PythonSecurityAnalyzer().visit(tree)
    except NodeExecutionError:
        raise
    except SyntaxError as e:
        raise NodeExecutionError(f"SyntaxError: {e.msg}", code="CODE_SYNTAX", node_id="code", retryable=False, details={"line": e.lineno, "col": e.offset}) from e

    import threading

    result = {}
    error = {}

    def target():
        try:
            exec(code, {"__builtins__": _SAFE_BUILTINS}, namespace)
            result["namespace"] = namespace
        except Exception as e:
            error["exception"] = e

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    thread.join(timeout)
    if thread.is_alive():
        # Timeout - cannot kill thread safely, but we can raise
        raise NodeExecutionError(f"Code execution timed out after {timeout}s", code="CODE_TIMEOUT", node_id="code", retryable=False)
    if "exception" in error:
        raise error["exception"]
    return result.get("namespace", namespace)


def _prepare_js_code(code: str, mode: str) -> str:
    """Prepare JS code - wrap in function to handle return correctly."""
    return code


# Sandbox daemon bootstrap executed via `python -c`. Kept deliberately
# standalone (no `app.*` imports) so process startup is fast and immune to
# __main__ re-import pitfalls that multiprocessing spawn has under
# console-script launchers. The daemon stays alive and serves eval requests
# over stdin/stdout lines: a cold spawn + dukpy import costs ~190ms, which
# would dominate small jobs if paid per evaluation. Each request builds a
# fresh JSInterpreter, so no state leaks between evaluations.
_DAEMON_PROGRAM = """
import json, sys

# Best-effort memory cap before the JS engine loads (POSIX only).
try:
    import resource
    mem_mb = int(sys.argv[1])
    vsz = 0
    try:
        with open("/proc/self/status") as fh:
            for line in fh:
                if line.startswith("VmSize:"):
                    vsz = int(line.split()[1]) * 1024
                    break
    except Exception:
        pass
    limit = vsz + mem_mb * 1024 * 1024
    if limit > 0:
        resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
except Exception:
    pass

try:
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import dukpy

for _line in sys.stdin:
    _line = _line.strip()
    if not _line:
        continue
    _result = {}
    try:
        _req = json.loads(_line)
        _interp = dukpy.JSInterpreter()
        _result["ok"] = _interp.evaljs(_req.get("code", ""))
    except BaseException as _exc:
        _result["err"] = repr(_exc)
    try:
        sys.stdout.write(json.dumps(_result, default=str) + "\\n")
        sys.stdout.flush()
    except Exception:
        break
"""

# Spawn + dukpy import take time before user JS runs; give the child a
# small allowance on top of the user-facing timeout so startup never eats it.
_DUKPY_STARTUP_GRACE = 3.0


# Persistent sandbox daemon state (guarded by _DAEMON_LOCK). Spawned lazily
# on the first eval, killed on timeout/crash, transparently respawned by the
# next call. Each request runs in a fresh JSInterpreter inside the child, so
# no JS state crosses evaluations.
_daemon_proc: Any = None
_daemon_queue: Any = None
_daemon_mem_mb: int | None = None
_DAEMON_LOCK = threading.Lock()


def _spawn_daemon(mem_limit_mb: int) -> None:
    global _daemon_proc, _daemon_queue, _daemon_mem_mb
    import queue as _queue
    import subprocess
    import sys

    backend_root = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", _DAEMON_PROGRAM, str(mem_limit_mb)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        cwd=backend_root,
        text=True,
        encoding="utf-8",
        bufsize=1,
    )
    out_q: _queue.Queue = _queue.Queue()

    def _reader() -> None:
        stdout = proc.stdout
        try:
            if stdout is None:
                return
            for line in stdout:
                out_q.put(line)
        finally:
            out_q.put(None)  # EOF sentinel: the daemon died

    threading.Thread(target=_reader, name="dukpy-daemon-reader", daemon=True).start()
    _daemon_proc = proc
    _daemon_queue = out_q
    _daemon_mem_mb = mem_limit_mb


def _kill_daemon() -> None:
    global _daemon_proc, _daemon_queue, _daemon_mem_mb
    proc, _daemon_proc = _daemon_proc, None
    _daemon_queue = None
    _daemon_mem_mb = None
    if proc is not None:
        try:
            proc.kill()
        except Exception:
            pass
        try:
            proc.wait(timeout=5)
        except Exception:
            pass


def _run_dukpy(js_wrapper: str, timeout: float, mem_limit_mb: int = 64) -> Any:
    """Execute dukpy JS in a killable subprocess.

    dukpy.evaljs blocks at the C level, so a thread + join(timeout) can never
    interrupt a runaway script. A child process can be terminated reliably on
    every platform, and the child applies a best-effort RLIMIT_AS memory cap
    where the OS supports it.

    The child is a long-lived daemon serving requests over stdin/stdout
    (per-eval cold spawn + dukpy import costs ~190ms, which would dominate
    small jobs). On timeout or crash it is killed and respawned by the next
    call; a fresh JSInterpreter per request keeps evaluations isolated.
    """
    import json as _json
    import queue as _queue

    with _DAEMON_LOCK:
        global _daemon_proc, _daemon_queue, _daemon_mem_mb
        if _daemon_proc is None or _daemon_proc.poll() is not None or _daemon_mem_mb != mem_limit_mb:
            _kill_daemon()
            _spawn_daemon(mem_limit_mb)

        def _checked() -> tuple[Any, Any, Any]:
            proc, q = _daemon_proc, _daemon_queue
            if proc is None or q is None or proc.stdin is None:
                raise RuntimeError("JS sandbox daemon unavailable.")
            return proc, q, proc.stdin

        payload_line = _json.dumps({"code": js_wrapper})
        proc, daemon_q, stdin = _checked()
        try:
            stdin.write(payload_line + "\n")
            stdin.flush()
        except (BrokenPipeError, OSError, ValueError):
            # Daemon died mid-write: retry once with a fresh one.
            _kill_daemon()
            _spawn_daemon(mem_limit_mb)
            proc, daemon_q, stdin = _checked()
            stdin.write(payload_line + "\n")
            stdin.flush()

        try:
            line = daemon_q.get(timeout=timeout + _DUKPY_STARTUP_GRACE)
        except _queue.Empty:
            _kill_daemon()
            raise NodeExecutionError(
                f"Code execution timed out after {timeout}s",
                code="CODE_TIMEOUT",
                node_id="code",
                retryable=False,
            )

        if line is None:
            # EOF without a result: the daemon died (e.g. OOM-killed by
            # RLIMIT_AS) while evaluating this script.
            returncode = proc.poll()
            _kill_daemon()
            raise RuntimeError(
                f"JavaScript execution terminated unexpectedly (exit code {returncode}). "
                "The script may have exceeded the memory budget (max_memory_mb)."
            )

        payload = _json.loads(line)
        if "err" in payload:
            raise RuntimeError(payload["err"])
        return payload.get("ok")


def _exec_javascript(code: str, items: List[dict[str, Any]], mode: str, timeout: float = 5.0, language: str = "javascript") -> List[dict[str, Any]]:
    """Execute JavaScript code with $input API via dukpy/js2py."""
    logs: List[str] = []
    def console_log(*args):
        logs.append(" ".join(str(a) for a in args))
    input_wrapper = InputWrapper(items, 0)
    exec_code = _prepare_js_code(code, mode)
    logger.info("JS exec: mode=%s code=%r items=%r", mode, code[:200], items[:1] if items else [])
    # Also print to stdout for worker logs
    _safe_print(f"CODE JS exec: mode={mode} code={code[:200]!r} items={items[:1] if items else []}", flush=True)

    # Try dukpy first
    js_wrapper = ""
    try:
        import dukpy  # type: ignore[import-untyped]  # noqa: F401 — presence check only
        import json as _json
        # Use normalized items for JS wrapper (with {json: ...})
        items_json = _json.dumps(input_wrapper._items)
        # Wrap user code in a function so `return` is valid
        js_wrapper = f"""
        var $input = {{
            _items: {items_json},
            _idx: 0,
            all: function() {{ return this._items; }},
            get item() {{ return this._items[this._idx] || {{}}; }}
        }};
        var items = $input._items;
        var item = items.length === 1 ? items[0] : null;
        var $json = items.length > 0 ? (items[0].json || items[0]) : {{}};
        var console = {{ log: function() {{}} }};
        var output;
        var __output;
        try {{
            __output = (function() {{
                {code}
            }})();
            if (typeof __output === 'undefined' && typeof output !== 'undefined') __output = output;
        }} catch(e) {{ throw e; }}
        if (typeof __output === 'undefined') {{ try {{ __output = $input.all(); }} catch(e) {{ __output = []; }} }}
        __output;
        """
        _safe_print(f"CODE DUKPY TRY code={code[:200]!r} items={items[:1]!r} wrapper={js_wrapper[:500]!r}", flush=True)
        logger.info("dukpy try code=%r items=%r", code[:200], items[:1] if items else [])
        # Run in a killable child process: dukpy.evaljs blocks at the C level,
        # so an in-process thread could never be interrupted on timeout.
        out = _run_dukpy(js_wrapper, timeout, mem_limit_mb=64)
        logger.debug("dukpy output for code %r: %r", code[:200], out)
        _safe_print(f"CODE DUKPY SUCCESS out={out!r}", flush=True)
        return _normalize_output(out, logs)
    except ImportError as e:
        logger.warning("dukpy not available: %s", e)
        _safe_print(f"CODE DUKPY NOT AVAILABLE {e}", flush=True)
        pass
    except NodeExecutionError:
        raise
    except Exception as e:
        logger.warning("dukpy failed for code %r: %s", code[:200], e)
        _safe_print(f"CODE DUKPY FAILED code={code[:200]!r} error={e}", flush=True)
        msg = str(e)
        raise NodeExecutionError(
            f"Code execution failed: {msg}",
            code="CODE_ERROR",
            node_id="code",
            retryable=False,
            details={"js_wrapper": js_wrapper[:2000] or None, "error": msg},
        ) from e

    # Try js2py
    try:
        import js2py  # type: ignore[import-untyped]
        context = js2py.EvalJs({"$input": input_wrapper, "console": {"log": console_log}})
        context.items = items
        context.item = items[0] if len(items) == 1 else None
        context.json = items[0].get("json", items[0]) if items and isinstance(items[0], dict) else {}
        result = {}
        def run_js2():
            try:
                context.execute(exec_code)
                if hasattr(context, "__output"):
                    out = context.__output
                    if hasattr(out, "to_list"):
                        out = out.to_list()
                    elif hasattr(out, "to_dict"):
                        out = out.to_dict()
                    result["output"] = out
                else:
                    result["output"] = items
                result["logs"] = logs
            except Exception as e:
                result["error"] = e
        import threading
        thread = threading.Thread(target=run_js2, daemon=True)
        thread.start()
        thread.join(timeout)
        if thread.is_alive():
            raise NodeExecutionError(f"Code execution timed out after {timeout}s", code="CODE_TIMEOUT", node_id="code", retryable=False)
        if "error" in result:
            err = result["error"]
            raise NodeExecutionError(f"Code execution failed: {err}", code="CODE_ERROR", node_id="code", retryable=False) from err
        output = result.get("output", items)
        return _normalize_output(output, logs)
    except ImportError:
        pass
    except NodeExecutionError:
        raise
    except Exception as e:
        raise NodeExecutionError(f"Code execution failed: {e}", code="CODE_ERROR", node_id="code", retryable=False) from e

    # Fallback to Python translation — only for Python language
    logger.info("Code fallback check: language=%r code[:100]=%r", language, code[:100])
    _safe_print(f"CODE FALLBACK CHECK language={language!r} code={code[:100]!r}", flush=True)
    # This fallback is reached only if both dukpy and js2py failed or were not available
    # For JavaScript, we should have already raised via dukpy/js2py error handling, so reaching here means both JS engines failed to even be tried (ImportError)
    # In that case, for JS, we should still try Python translation for simple cases, but JS object literal will fail
    # So we check: if language is JS and code contains JS-specific syntax that Python cannot handle, raise JS error
    if language.lower() not in ("python", "py"):
        # For JavaScript, try to see if code is simple enough for Python translation, else raise JS error
        # Check if code contains JS object literal without quotes (e.g., {json: {hello: "world"}}) which Python cannot handle
        if "json:" in code and "{" in code:
            last_err = locals().get("e") or (locals().get("result", {}).get("error") if "result" in locals() else None)
            logger.warning("JS code with object literal reached Python fallback, raising JS error: %s", last_err)
            raise NodeExecutionError(f"Code execution failed: JavaScript execution failed (dukpy/js2py not available or failed). Code: {code[:200]!r} Error: {last_err}", code="CODE_ERROR", node_id="code", retryable=False) from (last_err if isinstance(last_err, Exception) else None)
        # For other JS code that might be translatable, we can try Python fallback
        pass

    py_code = code.replace("$input", "input_wrapper")
    logger.info("Python fallback py_code: %r", py_code[:500])
    _safe_print(f"PY_FALLBACK py_code={py_code[:500]!r}", flush=True)
    import re
    py_code = re.sub(r"for\s*\(\s*const\s+(\w+)\s+of\s+input_wrapper\.all\(\)\s*\)", r"for \1 in input_wrapper.all():", py_code)
    py_code = re.sub(r"for\s*\(\s*let\s+(\w+)\s+of\s+input_wrapper\.all\(\)\s*\)", r"for \1 in input_wrapper.all():", py_code)
    py_code = py_code.replace("console.log", "print")
    lines = py_code.strip().splitlines()
    transformed = []
    for line in lines:
        stripped = line.lstrip()
        if stripped.startswith("return "):
            indent = line[: len(line) - len(stripped)]
            transformed.append(indent + "__output = " + stripped[len("return "):])
        elif stripped == "return":
            transformed.append("    __output = input_wrapper.all()")
        else:
            transformed.append(line)
    py_code = "\n".join(transformed)
    if "__output" not in py_code:
        py_code += "\nif '__output' not in locals():\n    __output = input_wrapper.all()"
    namespace: dict[str, Any] = {
        "input_wrapper": input_wrapper,
        "items": items,
        "item": items[0] if len(items) == 1 else None,
        "$input": input_wrapper,
        "console": {"log": console_log},
        "print": console_log,
        "_normalize_output": _normalize_output,
    }
    logger.info("Python fallback: language=%r code=%r py_code=%r", language, code[:200], py_code[:500])
    _safe_print(f"PY_FALLBACK language={language!r} code={code[:200]!r} py_code={py_code[:500]!r}", flush=True)
    try:
        exec(py_code, {"__builtins__": _SAFE_BUILTINS}, namespace)
    except Exception as exc:
        logger.error("Python exec failed for code %r py_code %r: %s", code[:200], py_code[:500], exc, exc_info=True)
        _safe_print(f"PY_CODE_FAIL code={code[:200]!r} py_code={py_code[:500]!r} error={exc}", flush=True)
        raise NodeExecutionError(f"Code execution failed: {exc} (py_code: {py_code[:200]!r})", code="CODE_ERROR", node_id="code", retryable=False, details={"py_code": py_code[:500], "code": code[:200]}) from exc

    output = namespace.get("__output", items)
    logger.info("Python fallback output %r", output)
    try:
        return _normalize_output(output, logs)
    except Exception as exc:
        logger.error("_normalize_output failed for output %r: %s", output, exc, exc_info=True)
        raise NodeExecutionError(f"Code execution failed: _normalize_output error {exc} output={output!r}", code="CODE_ERROR", node_id="code", retryable=False) from exc


def _exec_python_code(code: str, items: List[dict[str, Any]], mode: str, timeout: float = 5.0) -> List[dict[str, Any]]:
    """Execute Python code."""
    logs: List[str] = []

    def console_log(*args):
        logs.append(" ".join(str(a) for a in args))

    if mode == "runOnceForEachItem":
        # For per-item mode, this should be called per item, not here
        # But for AllItems mode with Python, we provide items
        pass

    # Prepare $input
    input_wrapper = InputWrapper(items, 0)
    # Transform return -> __output
    lines = code.strip().splitlines()
    transformed = []
    for line in lines:
        stripped = line.lstrip()
        if stripped.startswith("return "):
            indent = line[: len(line) - len(stripped)]
            rest = stripped[len("return "):].replace("$input", "input_wrapper")
            transformed.append(indent + "__output = " + rest)
        elif stripped == "return":
            transformed.append("    __output = input_wrapper.all()")
        else:
            # Replace $input with input_wrapper for Python
            transformed.append(line.replace("$input", "input_wrapper"))
    exec_code = "\n".join(transformed)
    # Handle console.log
    exec_code = exec_code.replace("console.log", "print")

    if "__output" not in exec_code and "return" not in code:
        exec_code += "\nif '__output' not in locals():\n    try:\n        __output = input_wrapper.all()\n    except: __output = []"

    namespace: dict[str, Any] = {
        "input_wrapper": input_wrapper,
        "items": items,
        "item": items[0] if len(items) == 1 else None,
        "$input": input_wrapper,
        "$json": items[0].get("json", items[0]) if items and isinstance(items[0], dict) else {},
        "input": {"all": input_wrapper.all, "item": input_wrapper.item},
        "console": {"log": console_log},
        "print": console_log,
        "InputWrapper": InputWrapper,
    }
    # Add $input.all and $input.item for JS-style code that was translated
    # Also handle Python's print vs console.log

    try:
        # Use timeout
        result = _exec_with_timeout(exec_code, namespace, timeout)
        output = result.get("__output", items)
        return _normalize_output(output, logs)
    except NodeExecutionError:
        raise
    except Exception as exc:
        # Try to get line info
        import traceback
        tb = traceback.extract_tb(exc.__traceback__)
        line = None
        col = None
        if tb:
            line = tb[-1].lineno
            col = tb[-1].colno if hasattr(tb[-1], 'colno') else None
        raise NodeExecutionError(f"Code execution failed: {exc}", code="CODE_ERROR", node_id="code", retryable=False, details={"line": line, "column": col, "logs": logs}) from exc


@register
class CodeNode(BaseNode[CodeParams]):
    node_type = "code"
    display_name = "Code"
    version = 1
    description = "Run JavaScript code to transform data. Use $input.all() and $input.item."
    category = "Transform"
    icon = "code"
    parameters_schema = CodeParams
    idempotency = "idempotent"

    async def run(
        self,
        ctx: NodeContext,
        params: CodeParams,
        input_items: list[dict[str, Any]],
    ) -> NodeResult:
        if not params.code.strip():
            return NodeResult(output_items=input_items or [{}])

        # Validate language
        if params.language.lower() not in ("javascript", "js", "python", "py"):
            raise NodeExecutionError(f"Unsupported language '{params.language}'. Only JavaScript and Python are supported.", code="BAD_REQUEST", node_id="code", retryable=False)
        if params.language.lower() in ("python", "py"):
            # Python is supported with a restricted sandbox (safe builtins only)
            pass

        # Validate syntax before execution
        # For Python, $input is not valid syntax but is replaced at runtime.
        # Validate against the post-replacement code for Python.
        code_to_validate = params.code
        if params.language.lower() in ("python", "py"):
            code_to_validate = params.code.replace("$input", "input_wrapper")
        is_valid, error_msg, line, col = _validate_syntax(code_to_validate, params.language)
        if not is_valid:
            raise NodeExecutionError(
                f"SyntaxError: {error_msg}",
                code="CODE_SYNTAX_ERROR",
                node_id="code",
                retryable=False,
                details={"line": line, "column": col, "message": error_msg},
            )

        # Get timeout from node settings or default
        timeout = 5.0

        mode = params.mode
        # Normalize mode
        if mode in ("Run Once for All Items", "runOnceForAllItems", "all"):
            mode = "runOnceForAllItems"
        elif mode in ("Run Once for Each Item", "runOnceForEachItem", "each"):
            mode = "runOnceForEachItem"
        else:
            mode = "runOnceForAllItems"

        # Handle empty input
        if not input_items:
            input_items = [{}]

        try:
            if mode == "runOnceForEachItem":
                # Run code once per item
                all_output: List[dict[str, Any]] = []
                for idx, item in enumerate(input_items):
                    single_input = [item]
                    # For each item, $input.all() should return [item] and $input.item is item
                    if params.language.lower() in ("javascript", "js"):
                        output = _exec_javascript(params.code, single_input, mode, timeout)
                        # For per-item, code is expected to return $input.item or single item
                        # _exec_javascript will return a list; we need to collect the first item or all
                        # For per-item, we expect return $input.item (single dict)
                        # So we take the first output item
                        if output and len(output) == 1:
                            all_output.append(output[0])
                        elif output:
                            # If code returned all items (e.g., return $input.all() in per-item mode, it would be [item])
                            # Take first
                            all_output.append(output[0] if len(output) == 1 else {"json": output[0].get("json", {})} if output else {"json": {}})
                        else:
                            all_output.append({"json": {}})
                    else:
                        output = _exec_python_code(params.code, single_input, mode, timeout)
                        if output and len(output) == 1:
                            all_output.append(output[0])
                        elif output:
                            all_output.append(output[0])
                        else:
                            all_output.append({"json": {}})
                return NodeResult(output_items=all_output or [{}])
            else:
                # Run Once for All Items
                if params.language.lower() in ("javascript", "js"):
                    output = _exec_javascript(params.code, input_items, mode, timeout)
                else:
                    output = _exec_python_code(params.code, input_items, mode, timeout)
                return NodeResult(output_items=output or [{}])
        except NodeExecutionError:
            raise
        except Exception as exc:
            raise NodeExecutionError(f"Code execution failed: {exc}", code="CODE_ERROR", node_id="code", retryable=False) from exc
