"""Import an OpenAPI/Swagger spec as a Flowsmith connector (Phase 1).

Reads a spec from a URL or local file, parses it, emits provider +
definition + connector modules, byte-compiles them, and validates the
result through discovery + validate_definition before anything lands
in the output directory.

Usage:
    python scripts/import_openapi.py --spec https://api.example.com/openapi.json --name my_api --title "My API"
    python scripts/import_openapi.py --spec ./spec.yaml --name my_api --dry-run
    python scripts/import_openapi.py --spec ./spec.json --name my_api --out app/connectors/generated --force

Exit code 0 = validated (and written unless --dry-run), 1 = failure.
Generated modules are scanned at startup from app/connectors/generated/.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

GENERATED_DIR = BACKEND / "app" / "connectors" / "generated"


def _load_source(spec: str) -> str:
    if spec.startswith(("http://", "https://")):
        import urllib.request

        request = urllib.request.Request(
            spec, headers={"User-Agent": "Flowsmith-Connector-Importer/1.0"},
        )
        with urllib.request.urlopen(request, timeout=30) as resp:
            return resp.read().decode("utf-8", errors="replace")
    return Path(spec).read_text(encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    from app.connectors.openapi_emit import (
        connector_key_for,
        discover_generated,
        emit_connector_files,
    )
    from app.connectors.openapi_import import parse_spec
    from app.connectors.registry import validate_definition

    parser = argparse.ArgumentParser(description="Import an OpenAPI spec as a connector.")
    parser.add_argument("--spec", required=True, help="Spec URL or local file path.")
    parser.add_argument("--name", required=True, help="Connector key seed (slugified).")
    parser.add_argument("--title", default="", help="Display name (default: spec title).")
    parser.add_argument("--category", default="api")
    parser.add_argument("--base-url", default="", help="Override when the spec declares no server URL.")
    parser.add_argument("--out", default=str(GENERATED_DIR), help="Output directory.")
    parser.add_argument("--dry-run", action="store_true", help="Validate only, write nothing.")
    parser.add_argument("--force", action="store_true", help="Overwrite an existing triple.")
    parser.add_argument("--only", default="", help="Regex: keep only matching operation keys/paths.")
    args = parser.parse_args(argv)

    try:
        raw = _load_source(args.spec)
    except Exception as exc:
        print(f"LOAD FAILED: {exc}")
        return 1
    if args.only:
        import re

        try:
            re.compile(args.only, re.IGNORECASE)
        except re.error as exc:
            print(f"BAD FILTER: {exc}")
            return 1
    if args.only:
        import re

        try:
            re.compile(args.only, re.IGNORECASE)
        except re.error as exc:
            print(f"BAD FILTER: {exc}")
            return 1
    try:
        api = parse_spec(raw, include=args.only or None)
    except Exception as exc:
        print(f"PARSE FAILED: {exc}")
        return 1
    override = (args.base_url or "").strip().rstrip("/")
    if override:
        if not override.startswith("http"):
            print("BAD FLAG: --base-url must start with http(s).")
            return 1
        api.base_url = override
    if not api.base_url:
        print("PARSE FAILED: no server URL (servers[] or host/basePath); pass --base-url.")
        return 1
    if not api.operations:
        print("PARSE FAILED: no operations found.")
        return 1

    key = connector_key_for(args.name)
    if args.only and not api.operations:
        print("FILTER FAILED: --only matched no operations.")
        return 1
    display = args.title.strip() or api.title
    files = emit_connector_files(key, display, api, args.category)
    for source in files.values():
        try:
            compile(source, f"<gen_{key}>", "exec")
        except SyntaxError as exc:
            print(f"EMIT FAILED: generated code does not compile: {exc}")
            return 1

    out_dir = Path(args.out)
    if not args.dry_run:
        existing = [p for p in files if (out_dir / p).exists()]
        if existing and not args.force:
            print(f"EXISTS (use --force): {', '.join(existing)}")
            return 1

    probe_dir = Path(tempfile.mkdtemp(prefix="openapi_probe_"))
    try:
        for name, source in files.items():
            (probe_dir / name).write_text(source, encoding="utf-8")
        pairs = discover_generated(str(probe_dir))
        if len(pairs) != 1:
            print("VALIDATE FAILED: discovery did not yield exactly one pair.")
            return 1
        try:
            validate_definition(pairs[0][1])
        except Exception as exc:
            print(f"VALIDATE FAILED: {exc}")
            return 1
    finally:
        import shutil

        shutil.rmtree(probe_dir, ignore_errors=True)

    print(f"OK: {display} [{key}] — {len(api.operations)} ops, auth={api.auth.kind}, base={api.base_url}")
    if args.dry_run:
        print("dry-run: nothing written")
        return 0
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, source in files.items():
        (out_dir / name).write_text(source, encoding="utf-8")
    print(f"wrote {len(files)} files to {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
