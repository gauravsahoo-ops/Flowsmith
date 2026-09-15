"""Fast parallelized test runner for Flowsmith (Phase 41 developer ergonomics).

Executes non-timing unit & API test suites across all CPU cores using
pytest-xdist, completing in seconds rather than ~25 minutes.

Usage:
    python scripts/test_fast.py           # Run non-timing tests with auto-parallelism
    python scripts/test_fast.py --all     # Run full suite with auto-parallelism
    python scripts/test_fast.py api       # Run only API tests in parallel
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"


def main() -> int:
    args = sys.argv[1:]
    run_all = "--all" in args
    filtered_args = [a for a in args if a != "--all"]

    workers = os.environ.get("PYTEST_WORKERS") or str(min(os.cpu_count() or 4, 4))
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        "-n",
        workers,
        "--dist=loadscope",
    ]

    if not run_all:
        cmd.extend(["-m", "not timing"])

    if filtered_args:
        for arg in filtered_args:
            if not arg.startswith("-"):
                if (BACKEND / arg).exists():
                    target = BACKEND / arg
                elif (BACKEND / "tests" / arg).exists():
                    target = BACKEND / "tests" / arg
                else:
                    target = BACKEND / arg
                cmd.append(str(target))
            else:
                cmd.append(arg)
    else:
        cmd.append(str(BACKEND / "tests"))

    print(f"[INFO] Running fast parallel tests: {' '.join(cmd)}")
    env = dict(os.environ)
    env["PYTHONPATH"] = str(BACKEND) + os.pathsep + env.get("PYTHONPATH", "")
    
    proc = subprocess.run(cmd, cwd=str(BACKEND), env=env)
    return proc.returncode


if __name__ == "__main__":
    sys.exit(main())
