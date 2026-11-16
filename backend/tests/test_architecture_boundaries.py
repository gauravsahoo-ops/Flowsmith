"""Architecture guardrail: domain modules must not import ``app.api``."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = BACKEND_ROOT / "app"
REPO_ROOT = BACKEND_ROOT.parent

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.check_architecture import check  # noqa: E402

DOMAIN_PACKAGES = ("platform", "orchestration", "tools", "agents", "approvals", "repositories")


def test_domain_packages_do_not_import_api_layer() -> None:
    violations = check(APP_ROOT)
    assert violations == [], "Architecture boundary violations:\n" + "\n".join(
        violations
    )


def test_checker_reports_control_plane_imports(tmp_path: Path) -> None:
    for package in DOMAIN_PACKAGES:
        (tmp_path / package).mkdir()
    (tmp_path / "platform" / "bad.py").write_text(
        "from app.api import auth\n", encoding="utf-8"
    )

    violations = check(tmp_path)

    assert len(violations) == 1
    assert "bad.py:1" in violations[0]
    assert "app.api" in violations[0]


def _fastapi_import_lines(path: Path) -> list[int]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    lines: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "fastapi" or alias.name.startswith("fastapi."):
                    lines.append(node.lineno)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module == "fastapi" or module.startswith("fastapi."):
                lines.append(node.lineno)
    return lines


def test_repositories_do_not_import_fastapi() -> None:
    package = APP_ROOT / "repositories"
    offenders: list[str] = []
    for path in sorted(package.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        for line in _fastapi_import_lines(path):
            offenders.append(f"{path.relative_to(APP_ROOT).as_posix()}:{line}")

    assert offenders == [], "app.repositories must not import fastapi:\n" + "\n".join(
        offenders
    )
