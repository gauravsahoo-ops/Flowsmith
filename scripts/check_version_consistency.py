#!/usr/bin/env python3
"""Fail when product version markers drift apart.

Source of truth: the repository `VERSION` file. The API health payload,
Docker image label, Helm chart appVersion, and frontend package metadata
must all match it.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _match(pattern: str, text: str, label: str) -> str:
    match = re.search(pattern, text, re.MULTILINE)
    if not match:
        raise SystemExit(f"Could not find version marker: {label}")
    return match.group(1)


def main() -> int:
    version_file = ROOT / "VERSION"
    if not version_file.exists():
        raise SystemExit("Missing VERSION file")
    expected = _read(version_file).strip()

    checks: list[tuple[str, str]] = []

    package = json.loads(_read(ROOT / "frontend" / "package.json"))
    checks.append(("frontend/package.json", str(package.get("version", ""))))

    lock = json.loads(_read(ROOT / "frontend" / "package-lock.json"))
    checks.append(("frontend/package-lock.json", str(lock.get("version", ""))))
    checks.append((
        "frontend/package-lock.json packages['']",
        str((lock.get("packages") or {}).get("", {}).get("version", "")),
    ))

    checks.append((
        "deploy/helm/flowsmith/Chart.yaml appVersion",
        _match(r'^appVersion:\s*"?([^"\n]+)"?', _read(ROOT / "deploy" / "helm" / "flowsmith" / "Chart.yaml"), "Helm appVersion"),
    ))
    checks.append((
        "Dockerfile label version",
        _match(r'version="([^"]+)"', _read(ROOT / "Dockerfile"), "Dockerfile label"),
    ))
    checks.append((
        "backend/app/main.py health version",
        _match(r'"version":\s*"([^"]+)"', _read(ROOT / "backend" / "app" / "main.py"), "health version"),
    ))

    mismatches = [(label, value) for label, value in checks if value != expected]
    print(f"VERSION: {expected}")
    for label, value in checks:
        print(f"  {'OK ' if value == expected else 'BAD'} {label}: {value or '<missing>'}")

    if mismatches:
        print(f"\nVersion drift detected: {len(mismatches)} marker(s) differ from VERSION.", file=sys.stderr)
        return 1
    print("\nAll version markers match.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
