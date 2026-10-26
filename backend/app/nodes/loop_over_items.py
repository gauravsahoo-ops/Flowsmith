"""Loop Over Items — visual alias for Loop."""
from __future__ import annotations

# Compatibility re-export without an eager import: importing app.nodes.loop
# from here creates a cycle because the registry imports this module while
# loading app.nodes.loop.


def __getattr__(name: str):
    if name == "LoopOverItemsNode":
        from app.nodes.loop import LoopOverItemsNode

        return LoopOverItemsNode
    raise AttributeError(name)
