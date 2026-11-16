"""Process-local cancellation ownership.

Cancellation is cooperative and durable (spec 36): the cancel endpoint
marks the execution ``cancelling`` in the database; the process running
the job polls that flag and flips an in-process event the engine checks
between nodes. The registry here is process-local by design — it only
holds executions running in *this* process, so ``signal`` returning
``False`` is the external-worker case, which the DB poll covers. The
poll also keeps queue workers cancellable across processes and restarts.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable

logger = logging.getLogger("orchestration.cancellation")

CANCEL_POLL_S = 0.25

_ACTIVE_CANCEL_EVENTS: dict[str, asyncio.Event] = {}


def register(execution_id: str) -> asyncio.Event:
    """Start tracking *execution_id* in this process; return its cancel event."""
    cancel_event = asyncio.Event()
    _ACTIVE_CANCEL_EVENTS[execution_id] = cancel_event
    return cancel_event


def unregister(execution_id: str) -> None:
    """Stop tracking *execution_id*; safe to call for an unknown id."""
    _ACTIVE_CANCEL_EVENTS.pop(execution_id, None)


def signal(execution_id: str) -> bool:
    """Instantly flip the cancel event if this execution is running in the current process."""
    evt = _ACTIVE_CANCEL_EVENTS.get(execution_id)
    if evt is not None:
        evt.set()
        return True
    return False


async def watch_durable_cancel(
    execution_id: str,
    cancel_event: asyncio.Event,
    *,
    session_factory: Callable[[], Any] | None = None,
    poll_s: float = CANCEL_POLL_S,
) -> None:
    """Poll the DB for the durable cancel flag; flip the local event.

    Queries only Execution.status and releases the connection back to the pool
    between polling ticks so concurrent executions never exhaust connection limits.
    """
    from sqlalchemy import select

    from app.models import Execution

    if session_factory is None:
        from app.db import get_session

        session_factory = get_session

    while not cancel_event.is_set():
        try:
            with session_factory() as db:
                status = db.scalar(
                    select(Execution.status).where(Execution.id == execution_id)
                )
                if status in ("cancelling", "cancelled"):
                    cancel_event.set()
                    break
        except Exception:
            logger.exception("cancel watch failed for %s", execution_id)
            break
        try:
            await asyncio.wait_for(cancel_event.wait(), timeout=poll_s)
        except asyncio.TimeoutError:
            pass
