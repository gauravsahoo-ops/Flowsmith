#!/usr/bin/env python
"""Disaster-recovery drill CLI (Phase 33).

Runs a real backup -> damage -> restore -> verify cycle against
throwaway databases and prints an RTO/RPO report:

    python -m scripts.dr_drill

Exits non-zero when any recovery check fails. Never touches the
configured application database (scratch DBs only).
"""

from __future__ import annotations

import json
import sys


def main() -> int:
    sys.path.insert(0, ".")
    from app.dr import run_drill

    report = run_drill()
    print(json.dumps(report, indent=2))
    if not report.get("ok"):
        print("DRILL FAILED — see checks above.", file=sys.stderr)
        return 1
    print(
        f"\nDR DRILL PASSED — RTO (measured): "
        f"{report['rto_seconds']['total_measured']}s total "
        f"(dump {report['rto_seconds']['dump']}s / "
        f"restore {report['rto_seconds']['restore']}s)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
