"""import_openapi CLI tests (Phase 1): tmp spec files, tmp out dirs."""

from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND / "scripts"))

from import_openapi import main

SPEC = {
    "openapi": "3.0.0",
    "info": {"title": "Widget API"},
    "servers": [{"url": "https://api.widgets.com/v2"}],
    "paths": {"/widgets": {"get": {"operationId": "listWidgets"}}},
}


def _spec_file(tmp_path):
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps(SPEC), encoding="utf-8")
    return str(spec)


def test_dry_run_validates_only(tmp_path):
    out = tmp_path / "out"
    rc = main(["--spec", _spec_file(tmp_path), "--name", "widgets", "--out", str(out), "--dry-run"])
    assert rc == 0
    assert not out.exists()


def test_write_then_refuse_then_force(tmp_path):
    out = tmp_path / "out"
    spec = _spec_file(tmp_path)
    assert main(["--spec", spec, "--name", "widgets", "--out", str(out)]) == 0
    assert len(list(out.glob("gen_*.py"))) == 3
    assert main(["--spec", spec, "--name", "widgets", "--out", str(out)]) == 1
    assert main(["--spec", spec, "--name", "widgets", "--out", str(out), "--force"]) == 0


def test_missing_file_fails(tmp_path):
    assert main(["--spec", str(tmp_path / "nope.json"), "--name", "x"]) == 1


def test_spec_without_servers_fails(tmp_path):
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps({"info": {"title": "T"}, "paths": {"/a": {"get": {}}}}), encoding="utf-8")
    assert main(["--spec", str(spec), "--name", "x", "--dry-run"]) == 1


def test_written_triple_discovers(tmp_path):
    from app.connectors.openapi_emit import discover_generated

    out = tmp_path / "out"
    assert main(["--spec", _spec_file(tmp_path), "--name", "widgets", "--out", str(out)]) == 0
    pairs = discover_generated(str(out))
    assert len(pairs) == 1
    assert pairs[0][0].connector_id == "widgets"
