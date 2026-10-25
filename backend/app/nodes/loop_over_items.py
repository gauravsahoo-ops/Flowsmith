"""Loop Over Items — visual alias for Loop."""
from __future__ import annotations

# Compatibility re-export: the implementation and registration live in
# app.nodes.loop, but callers historically imported the class from here.
from app.nodes.loop import LoopOverItemsNode

__all__ = ["LoopOverItemsNode"]
