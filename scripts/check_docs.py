#!/usr/bin/env python3
"""Verify the committed documentation package.

Checks:
- relative Markdown links resolve;
- local and cross-file anchors resolve;
- backticked repository file references in the current package exist;
- reports the documentation inventory.

Usage (from the repository root):
    .venv/Scripts/python.exe scripts/check_docs.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
HEADING_RE = re.compile(r"^#{1,6}\s+(.+)$", re.MULTILINE)
CODE_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
REF_RE = re.compile(r"`((?:docs|backend|frontend|scripts|deploy)/[A-Za-z0-9_./-]+)`")

# Historical GSD guidance points at a removed internal playbook. It is not part
# of the product documentation package.
KNOWN_LINK_EXCEPTIONS = {
    ("GSD-STYLE.md", "docs/model-selection-playbook.md"),
}

PACKAGE_FILES = [
    "USER_MANUAL.md",
    "docs/README.md",
    "docs/PROJECT_STATUS_2026-11-17.md",
    "docs/DOCUMENTATION_VERIFICATION_2026-11-18.md",
    "docs/ADMINISTRATOR_GUIDE.md",
    "docs/ORCHESTRATION_RUNTIME.md",
    "docs/LAUNCH_READINESS_CHECKLIST.md",
    "docs/CLIENT_REPLY_2026-11-17.md",
    "docs/DEMO_PLAN_2026-11-17.md",
]


def slug(heading: str) -> str:
    """Approximate GitHub's heading anchor algorithm."""
    text = heading.strip().lower().replace("`", "")
    text = re.sub(r"[^\w\s-]", "", text)
    return text.replace(" ", "-")


def strip_code(text: str) -> str:
    return CODE_FENCE_RE.sub("", text)


def markdown_files() -> list[Path]:
    return sorted(
        {*ROOT.glob("*.md"), *DOCS.rglob("*.md")},
        key=lambda p: str(p).lower(),
    )


def heading_anchors(text: str) -> set[str]:
    return {slug(m.group(1)) for m in HEADING_RE.finditer(strip_code(text))}


def check_links(files: list[Path]) -> list[tuple[str, str, str]]:
    broken: list[tuple[str, str, str]] = []
    anchors_cache: dict[Path, set[str]] = {}

    for path in files:
        text = strip_code(path.read_text(encoding="utf-8", errors="ignore"))
        for match in LINK_RE.finditer(text):
            target = match.group(1).strip()
            if not target or target.startswith(("http://", "https://", "mailto:", "file:")):
                continue
            if target.startswith("#"):
                if target[1:] not in anchors_cache.setdefault(path, heading_anchors(text)):
                    broken.append((str(path.relative_to(ROOT)), target, "missing local anchor"))
                continue
            file_part, _, fragment = target.partition("#")
            file_part = file_part.strip()
            if not file_part:
                continue
            resolved = (path.parent / file_part).resolve()
            if not resolved.exists():
                key = (str(path.relative_to(ROOT)), target)
                if key not in KNOWN_LINK_EXCEPTIONS:
                    broken.append((str(path.relative_to(ROOT)), target, "missing file"))
                continue
            if fragment and resolved.suffix.lower() == ".md":
                target_text = resolved.read_text(encoding="utf-8", errors="ignore")
                anchors = anchors_cache.setdefault(resolved, heading_anchors(target_text))
                if fragment not in anchors:
                    broken.append(
                        (str(path.relative_to(ROOT)), target, "missing cross-file anchor")
                    )
    return broken


def check_package_refs() -> list[tuple[str, str]]:
    missing: list[tuple[str, str]] = []
    for relative in PACKAGE_FILES:
        path = ROOT / relative
        if not path.exists():
            missing.append((relative, "package file missing"))
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for match in REF_RE.finditer(text):
            raw = match.group(1).rstrip(".,);")
            if raw.endswith("/"):
                continue
            if not ((path.parent / raw).exists() or (ROOT / raw).exists()):
                missing.append((relative, raw))
    return sorted(set(missing))


def main() -> int:
    files = markdown_files()
    broken = check_links(files)
    missing_refs = check_package_refs()
    words = 0
    for path in files:
        words += len(path.read_text(encoding="utf-8", errors="ignore").split())

    print(f"Markdown files checked: {len(files)}")
    print(f"Words: {words:,}")
    print(f"Broken links/anchors: {len(broken)}")
    for path, target, reason in broken[:20]:
        print(f"  {path} -> {target} ({reason})")
    print(f"Missing package file references: {len(missing_refs)}")
    for path, target in missing_refs[:20]:
        print(f"  {path} -> {target}")

    return 1 if broken or missing_refs else 0


if __name__ == "__main__":
    sys.exit(main())
