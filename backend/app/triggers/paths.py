"""Shared validation and regeneration rules for public trigger paths.

Webhook paths are unauthenticated routing keys.  A weak path is guessable;
a duplicated path lets one workflow's trigger row be replaced by another
workflow.  Keep the rules in one place so the generic, provider, form, chat,
and Salesforce trigger types cannot drift apart.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from app.triggers.registry import WEBHOOK_TRIGGER_TYPES

PATH_TRIGGER_TYPES = frozenset(WEBHOOK_TRIGGER_TYPES | {
    "salesforce_trigger",
    "form_trigger",
    "chat_trigger",
})

PROVIDER_TRIGGER_TYPES = frozenset(WEBHOOK_TRIGGER_TYPES - {"webhook"})

TRIGGER_PATH_RE = re.compile(r"^[A-Za-z0-9/_.\-]{24,255}$")
_SAFE_PREFIX_RE = re.compile(r"[^A-Za-z0-9_.-]")

_PREFIX_BY_TYPE = {
    "form_trigger": "form/",
    "chat_trigger": "chat/",
    "salesforce_trigger": "sf-outbound/",
}


def validate_trigger_path(node_type: str, raw_path: Any) -> str:
    """Return a valid path or raise ``ValueError`` with a safe message."""
    if raw_path is None or str(raw_path).strip() == "":
        return ""
    path = str(raw_path)
    if not TRIGGER_PATH_RE.fullmatch(path):
        raise ValueError(
            f"{node_type} path '{path}' is too weak. It is the only "
            "authentication for an unauthenticated endpoint: use at least "
            "24 characters of [A-Za-z0-9/_.-] (a generated id works well)."
        )
    if node_type in PROVIDER_TRIGGER_TYPES and "/" in path:
        raise ValueError(
            f"{node_type} path must be a single URL segment because provider "
            "callbacks are delivered to /api/webhooks/{path}."
        )
    if any(part in (".", "..") for part in path.split("/")):
        raise ValueError(f"{node_type} path must not contain '.' or '..' segments.")
    return path


def regenerate_trigger_path(node_type: str, raw_path: Any) -> str:
    """Generate a fresh path, preserving a trigger-type namespace prefix."""
    path = str(raw_path or "")
    prefix = _PREFIX_BY_TYPE.get(node_type, "")
    if prefix and path.startswith(prefix):
        path = path[len(prefix):]
    clean = _SAFE_PREFIX_RE.sub("", path)[:12] or "hook"
    return f"{prefix}{clean}-{uuid.uuid4().hex[:24]}"
