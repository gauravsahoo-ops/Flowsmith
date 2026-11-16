"""Opt-in live vendor acceptance wrappers.

These tests are skipped unless the corresponding credentials file exists.
They are intentionally excluded from the default CI pass (``pytest -m "not
timing"``); run them explicitly with::

    pytest -m live tests/test_live_vendor_smoke.py

The wrapped scripts perform read-only checks against real vendor tenants and
never print credentials. A missing credentials file is a skip, not a pass.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.live

ROOT = Path(__file__).resolve().parents[2]

CASES = [
    pytest.param(
        "hubspot",
        ROOT / "scripts" / "live_hubspot_acceptance.py",
        ROOT / "backend" / ".env.hubspot-live-acceptance",
        id="hubspot",
    ),
    pytest.param(
        "salesforce",
        ROOT / "scripts" / "live_salesforce_acceptance.py",
        ROOT / "backend" / ".env.live-acceptance",
        id="salesforce",
    ),
]


def _env_file_values(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _has_live_credentials(name: str, path: Path) -> bool:
    if not path.exists():
        return False
    values = _env_file_values(path)
    if name == "hubspot":
        return bool(
            values.get("HUBSPOT_ACCEPTANCE_PRIVATE_TOKEN")
            or values.get("HUBSPOT_ACCEPTANCE_REFRESH_TOKEN")
        )
    if name == "salesforce":
        if not values.get("SF_ACCEPTANCE_CLIENT_ID") or not values.get(
            "SF_ACCEPTANCE_CLIENT_SECRET"
        ):
            return False
        return bool(
            values.get("SF_ACCEPTANCE_REFRESH_TOKEN")
            or (
                values.get("SF_ACCEPTANCE_USERNAME")
                and values.get("SF_ACCEPTANCE_PASSWORD")
            )
        )
    return False


@pytest.mark.parametrize("name,script,credentials_file", CASES)
def test_live_vendor_acceptance(name: str, script: Path, credentials_file: Path) -> None:
    if not _has_live_credentials(name, credentials_file):
        pytest.skip(f"{name}: no live credentials configured in {credentials_file.name}")
    if not script.exists():
        pytest.fail(f"{name}: acceptance script missing: {script}")

    completed = subprocess.run(
        [sys.executable, str(script)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    output = (completed.stdout or "")[-4000:]
    error = (completed.stderr or "")[-2000:]
    assert completed.returncode == 0, (
        f"{name} live acceptance failed with exit code {completed.returncode}\n"
        f"stdout:\n{output}\nstderr:\n{error}"
    )
