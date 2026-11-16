#!/usr/bin/env python3
"""Enforce the Phase 3 dependency direction for domain modules.

The control plane (``app.api``) may import domain modules; domain modules must
not import the HTTP layer. Cross-boundary communication goes through
``app.platform`` contracts and events instead.

Scanned packages: platform, orchestration, tools, agents, approvals, repositories.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / "backend" / "app"
DOMAIN_PACKAGES = (
    "platform",
    "orchestration",
    "tools",
    "agents",
    "approvals",
    "repositories",
)
FORBIDDEN_MODULE = ("app", "api")


def _display(path: Path) -> str:
    """Render a path relative to the repository root when possible."""
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _relative_target(
    path: Path,
    app_root: Path,
    node: ast.ImportFrom,
) -> tuple[str, ...]:
    """Resolve a relative import against the package containing ``path``."""
    relative = path.relative_to(app_root.parent).with_suffix("")
    parts = list(relative.parts)
    is_package = parts[-1] == "__init__"
    if is_package:
        parts.pop()
    package = parts if is_package else parts[:-1]

    if node.level > len(package):
        return ()
    base = package[: len(package) - (node.level - 1)]
    if node.module:
        base = [*base, *node.module.split(".")]
    return tuple(base)


def _is_api_target(target: tuple[str, ...]) -> bool:
    return target[:2] == FORBIDDEN_MODULE


def _violations(path: Path, app_root: Path) -> list[str]:
    source = path.read_text(encoding="utf-8", errors="replace")
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        return [f"{_display(path)}:{exc.lineno or 1}: cannot parse module: {exc.msg}"]

    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _is_api_target(tuple(alias.name.split("."))):
                    found.append(
                        (
                            node.lineno,
                            f"imports {alias.name} (control-plane package)",
                        )
                    )
        elif isinstance(node, ast.ImportFrom):
            target = (
                _relative_target(path, app_root, node)
                if node.level
                else tuple((node.module or "").split("."))
            )
            if _is_api_target(target):
                module = "." * node.level + (node.module or "")
                found.append(
                    (
                        node.lineno,
                        f"imports app.api via 'from {module} import ...'",
                    )
                )
                continue
            for alias in node.names:
                candidate = (*target, *alias.name.split("."))
                if _is_api_target(candidate):
                    found.append(
                        (
                            node.lineno,
                            f"imports app.api via '{alias.name}'",
                        )
                    )

    display = _display(path)
    return [f"{display}:{line}: {message}" for line, message in sorted(found)]


def check(app_root: Path) -> list[str]:
    """Return boundary violations found under ``app_root`` (``backend/app``)."""
    violations: list[str] = []
    for package in DOMAIN_PACKAGES:
        package_root = app_root / package
        if not package_root.is_dir():
            violations.append(
                f"{_display(package_root)}: missing architecture scan root"
            )
            continue
        for path in sorted(package_root.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            violations.extend(_violations(path, app_root))
    return violations


def main() -> int:
    violations = check(APP_ROOT)
    if violations:
        print(
            f"Architecture boundary violations: {len(violations)}",
            file=sys.stderr,
        )
        for violation in violations:
            print(f"  {violation}", file=sys.stderr)
        return 1
    print(
        "Architecture boundaries OK: no domain module imports app.api "
        f"({len(DOMAIN_PACKAGES)} packages scanned)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
