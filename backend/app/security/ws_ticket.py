"""One-time short-lived WebSocket tickets (spec: keep JWTs out of URLs).

Browsers cannot set headers on WebSocket handshakes, so the live
execution stream historically passed the raw bearer token as
``?token=`` — leaking it into access logs, proxies, and Referer
headers. ``POST /api/auth/ws-ticket`` now hands out a signed, purpose-
bound, single-use ticket valid for a few seconds; the socket presents
it via ``?ticket=`` and it dies on first use.

Redis provides cross-worker one-time consumption (NX semantics); an
in-memory bounded map is the single-process fallback (same pattern as
the JWT blacklist).
"""

from __future__ import annotations

import logging
import secrets
import time

import jwt as pyjwt

from app.config import get_settings
from app.security.jwt import _get_jwt_secret

logger = logging.getLogger(__name__)

WS_TICKET_TTL_S = 15  # enough for handshake round-trip, short enough to be useless elsewhere
_WS_TICKET_PURPOSE = "ws"

# jti -> exp (epoch seconds); lazily GC'd, bounded like the JWT blacklist.
_used_tickets: dict[str, float] = {}
_MAX_USED_TICKETS = 10_000


def issue_ws_ticket(user_id: int) -> str:
    """Mint a single-use ticket for *user_id* (valid WS_TICKET_TTL_S seconds)."""
    now = int(time.time())
    payload = {
        "sub": str(user_id),
        "jti": secrets.token_urlsafe(16),
        "purpose": _WS_TICKET_PURPOSE,
        "iat": now,
        "exp": now + WS_TICKET_TTL_S,
    }
    return pyjwt.encode(payload, _get_jwt_secret(), algorithm=get_settings().jwt_algorithm)


def _already_used(jti: str, exp: int) -> bool:
    """Atomically claim *jti*; returns True when it was already consumed."""
    try:
        from app.security.redis_client import get_shared_redis

        r = get_shared_redis()
        if r is not None:
            # SET NX: True only for the first claimer.
            return not bool(r.set(f"ws_ticket_used:{jti}", "1", ex=max(exp - int(time.time()), 1), nx=True))
    except Exception:  # pragma: no cover - redis outages fall back in-memory
        logger.debug("ws_ticket: redis unavailable, using in-memory claim map")

    now = time.time()
    # GC expired entries and cap the map.
    for key in [k for k, exp_ts in _used_tickets.items() if exp_ts <= now]:
        _used_tickets.pop(key, None)
    if len(_used_tickets) >= _MAX_USED_TICKETS:
        _used_tickets.clear()  # bounded: worst case allows a tiny replay window under flood
    if jti in _used_tickets:
        return True
    _used_tickets[jti] = float(exp)
    return False


def consume_ws_ticket(ticket: str) -> int | None:
    """Validate and consume a ticket; returns the user id or None."""
    if not ticket:
        return None
    try:
        payload = pyjwt.decode(
            ticket, _get_jwt_secret(), algorithms=[get_settings().jwt_algorithm]
        )
    except pyjwt.PyJWTError:
        return None
    if payload.get("purpose") != _WS_TICKET_PURPOSE:
        return None
    jti = payload.get("jti")
    exp = payload.get("exp")
    if not isinstance(jti, str) or not isinstance(exp, int):
        return None
    if _already_used(jti, exp):
        return None
    try:
        return int(payload["sub"])
    except (KeyError, TypeError, ValueError):
        return None
