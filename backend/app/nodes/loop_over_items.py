"""Loop Over Items — visual alias for Loop (n8n parity).

Provides the exact node_type string expected from n8n references while
reusing Loop's per-item split behavior. See `loop.py`.
"""

from __future__ import annotations

from app.nodes.loop import LoopNode
from app.nodes.registry import register


@register
class LoopOverItemsNode(LoopNode):
    node_type = "loop_over_items"
    display_name = "Loop Over Items"
    description = "Split data into batches and iterate over each batch"
    icon = "loop_over_items"

