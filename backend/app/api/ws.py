"""WebSocket live execution stream (spec 10).

Auth via ?token= query param (browsers can't set WS headers). Events
come from one of two sources (Phase 15): the in-process bus when the
execution runs on the embedded consumer, or the durable
``execution_events`` rows when an external worker ran it. The handler
drains both (only one is ever active per execution) every 50ms,
closing after a terminal event with the persisted execution status as
fallback.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import jwt as pyjwt
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.common import TERMINAL_STATUSES
from app.db import get_db
from app.eventbus import bus
from app.models import Execution, ExecutionEvent, User
from app.security.jwt import decode_token

router = APIRouter(tags=["ws"])
logger = logging.getLogger("api.ws")

DRAIN_INTERVAL_S = 0.05
TERMINAL_STATUS = {
    "execution.completed": "success",
    "execution.failed": "failed",
    "execution.cancelled": "cancelled",
    "execution.timeout": "timeout",
}


def _auth_user(token: str | None, db: Session) -> User | None:
    if not token:
        return None
    try:
        payload = decode_token(token)
        return db.get(User, int(payload["sub"]))
    except (pyjwt.InvalidTokenError, KeyError, ValueError):
        return None


def _drain_db_events(db: Session, execution_id: str, after_seq: int) -> tuple[list[dict[str, Any]], int]:
    """Durable events written by external workers (spec 37)."""
    rows = db.scalars(
        select(ExecutionEvent)
        .where(ExecutionEvent.execution_id == execution_id, ExecutionEvent.seq > after_seq)
        .order_by(ExecutionEvent.seq)
        .limit(500)
    ).all()
    events = [
        {
            "seq": row.seq,
            "execution_id": execution_id,
            "event": row.event,
            "node_id": row.node_id,
            "status": row.status,
            "error": row.error,
            **({"timestamp": row.timestamp.isoformat() if row.timestamp else None}),
        }
        for row in rows
    ]
    return events, events[-1]["seq"] if events else after_seq


@router.websocket("/api/ws/executions/{execution_id}")
async def ws_execution_stream(
    execution_id: str,
    websocket: WebSocket,
    token: str | None = None,
    db: Session = Depends(get_db),
) -> None:
    user = _auth_user(token, db)
    db.rollback()
    if user is None:
        await websocket.close(code=4401)
        return

    rec = db.get(Execution, execution_id)
    db.rollback()
    if rec is None or rec.user_id != user.id:
        await websocket.close(code=4404)
        return

    await websocket.accept()

    # Drain both event sources: the in-process bus (embedded consumer,
    # dev default) and the durable events table (external workers).
    # Only one is ever active per execution, so the two
    # watermarks never conflict.
    bus_after = 0  # watermark: in-process bus
    db_after = 0   # watermark: durable events
    last_error: dict | None = None
    last_auth_check = asyncio.get_event_loop().time()
    try:
        while True:
            # Re-validate user every 60 seconds (WebSocket re-validation)
            now = asyncio.get_event_loop().time()
            if now - last_auth_check >= 60:
                user = db.get(User, user.id)
                db.rollback()
                if user is None or not user.active:
                    await websocket.send_json({"type": "error", "error": "Session invalidated."})
                    break
                last_auth_check = now
            events: list[dict[str, Any]] = bus.drain(execution_id, bus_after)
            db_events, db_after = _drain_db_events(db, execution_id, db_after)
            db.rollback()
            if events:
                bus_after = events[-1]["seq"]
            events.extend(db_events)
            events.sort(key=lambda ev: ev.get("seq", 0))

            terminal_sent = False
            for ev in events:
                await websocket.send_json(ev)
                if ev.get("event") == "node.failed":
                    last_error = ev.get("error")
                status = TERMINAL_STATUS.get(ev.get("event", ""))
                if status is not None:
                    # The event fires before the DB commit, so derive the
                    # status from the event; pick the error from the DB when
                    # it has already been persisted.
                    rec = db.get(Execution, execution_id)
                    error = rec.error if rec is not None and rec.error is not None else last_error
                    db.rollback()
                    # Small delay to allow the worker's DB commit (trace,
                    # node_statuses, results) to propagate before the
                    # client fetches the full execution payload.
                    await asyncio.sleep(0.3)
                    terminal: dict[str, Any] = {
                        "type": "execution.terminal",
                        "status": status,
                        "error": error,
                    }
                    await websocket.send_json(terminal)
                    terminal_sent = True
                    break

            if terminal_sent:
                break

            rec = db.get(Execution, execution_id)
            status = rec.status if rec is not None else None
            error = rec.error if rec is not None else None
            db.rollback()
            if status in TERMINAL_STATUSES:
                for ev in bus.drain(execution_id, bus_after):
                    bus_after = ev["seq"]
                    await websocket.send_json(ev)
                await websocket.send_json(
                    {"type": "execution.terminal", "status": status, "error": error}
                )
                break

            await asyncio.sleep(DRAIN_INTERVAL_S)
    except WebSocketDisconnect:
        pass
    finally:
        await websocket.close()
