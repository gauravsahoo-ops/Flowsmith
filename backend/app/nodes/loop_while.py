"""Bounded while-loop node (Phase 8).

Runs a bounded iteration loop *inside* a single node. The workflow
graph may contain arbitrary edges (cycles are allowed in the topology);
the engine executes each node at most once per pass, so all iteration
repetition happens here under hard limits:

- ``max_iterations``: hard cap on iterations (1..10_000).
- ``condition`` + ``mode``: termination condition evaluated against the
  current item each iteration.  ``until`` stops when the condition
  becomes true; ``while`` continues only while it stays true.
- ``update``: optional per-iteration item transform. Values may be
  expressions resolved against ``$json`` (the current item) and
  ``$iterations`` (the 1-based iteration counter), e.g.
  ``{{ $json.attempts + 1 }}``.
- ``delay_seconds``: pause between iterations (cancellable in slices).
- ``on_limit``: what happens when ``max_iterations`` is exhausted —
  ``fail`` (default) raises LOOP_LIMIT_EXCEEDED so a non-terminating
  loop can never pass silently; ``complete`` returns the last item with
  ``limit_reached`` metadata.

The engine's per-node timeout wraps the whole loop, and cooperative
cancellation is checked between iterations and during delays.
"""

from __future__ import annotations

import asyncio
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.engine import expressions
from app.engine.errors import NodeCancelledError, NodeExecutionError
from app.engine.node_base import BaseNode, NodeContext, NodeResult
from app.nodes.condition_base import Condition, evaluate as _evaluate_condition
from app.nodes.registry import register


class LoopWhileParams(BaseModel):
    condition: Condition = Field(description="Termination condition evaluated on the current item")
    mode: Literal["until", "while"] = Field(
        default="until",
        description="'until': stop when condition is true. 'while': continue while condition is true.",
    )
    update: dict[str, Any] = Field(
        default_factory=dict,
        description="Fields merged into the item every iteration (supports {{ $json.* }} / {{ $iterations }}).",
    )
    max_iterations: int = Field(default=1000, ge=1, le=10_000, description="Hard cap on iterations")
    delay_seconds: float = Field(default=0.0, ge=0, le=300, description="Pause between iterations")
    on_limit: Literal["fail", "complete"] = Field(
        default="fail",
        description="'fail' errors when the limit is reached; 'complete' returns the last item.",
    )


@register
class LoopWhileNode(BaseNode[LoopWhileParams]):
    node_type = "loop_while"
    display_name = "Loop While"
    version = 1
    description = "Bounded iteration loop with a termination condition, hard limit and per-iteration delay."
    category = "Logic"
    icon = "🔁"
    parameters_schema = LoopWhileParams
    # Condition/update expressions are re-evaluated every iteration, so
    # the engine must NOT bake them into constants up front.
    resolves_own_expressions = True

    async def run(
        self,
        ctx: NodeContext,
        params: LoopWhileParams,
        input_items: list[dict[str, Any]],
    ) -> NodeResult:
        item: dict[str, Any] = dict(input_items[0]) if input_items else {}

        for iteration in range(1, params.max_iterations + 1):
            if ctx.is_cancelled() or (ctx.cancel_event is not None and ctx.cancel_event.is_set()):
                raise NodeCancelledError(ctx.node_id)

            context = self._iteration_context(ctx, item, iteration)
            satisfied = self._satisfied(params, context, item)

            if params.mode == "until" and satisfied:
                return self._done(item, iteration, limit_reached=False)
            if params.mode == "while" and not satisfied:
                return self._done(item, iteration, limit_reached=False)

            ctx.emit_event("loop.iteration", node_id=ctx.node_id, iteration=iteration,
                           max_iterations=params.max_iterations)

            if params.update:
                try:
                    updates = expressions.resolve(params.update, context)
                except Exception as exc:
                    raise NodeExecutionError(
                        f"Loop update failed at iteration {iteration}: {exc}",
                        code="LOOP_UPDATE_ERROR", retryable=False,
                    ) from exc
                item = {**item, **updates}

            await self._delay(ctx, params.delay_seconds)

        # Hard limit exhausted without the condition terminating the loop.
        if params.on_limit == "complete":
            return self._done(item, params.max_iterations, limit_reached=True)
        raise NodeExecutionError(
            f"Loop exceeded max_iterations={params.max_iterations} without satisfying the "
            f"{params.mode} condition.",
            code="LOOP_LIMIT_EXCEEDED", retryable=False,
        )

    def _satisfied(self, params: LoopWhileParams, context: dict[str, Any], item: dict[str, Any]) -> bool:
        """Evaluate the condition on the current item, resolving any
        {{ }} expressions in left/right against the iteration context."""
        raw = params.condition.model_dump()
        raw["left"] = expressions.resolve(raw["left"], context)
        raw["right"] = expressions.resolve(raw["right"], context)
        try:
            condition = Condition.model_validate(raw)
            left_val = condition.left
            # When a key doesn't exist yet, the expression resolver returns
            # the unresolved template string (e.g. "{{ $json.done }}").
            # Treat unresolved templates and None as falsy for boolean conditions.
            is_unresolved = isinstance(left_val, str) and "{{" in left_val and "}}" in left_val
            if left_val is None or is_unresolved:
                if condition.operator in ("is false", "is not true"):
                    return True
                if condition.operator in ("equals", "is equal to", "is true", "is not false"):
                    return False
                if is_unresolved:
                    return False
            return _evaluate_condition(condition, item, convert_types=True)
        except NodeExecutionError:
            raise
        except Exception as exc:
            raise NodeExecutionError(
                f"Could not evaluate loop condition: {exc}",
                code="INVALID_CONDITION", retryable=False,
            ) from exc

    def _iteration_context(
        self, ctx: NodeContext, item: dict[str, Any], iteration: int,
    ) -> dict[str, Any]:
        """Engine context (so $node/$env/$cred stay reachable) overlaid
        with the evolving loop state."""
        base = dict(ctx.expression_context or {})
        base.update({
            "$json": item,
            "$iterations": iteration,
        })
        return base

    async def _delay(self, ctx: NodeContext, seconds: float) -> None:
        """Sleep in small cancellable slices."""
        remaining = seconds
        while remaining > 0:
            if ctx.is_cancelled() or (ctx.cancel_event is not None and ctx.cancel_event.is_set()):
                raise NodeCancelledError(ctx.node_id)
            step = min(0.05, remaining)
            await asyncio.sleep(step)
            remaining -= step

    @staticmethod
    def _done(item: dict[str, Any], iterations: int, *, limit_reached: bool) -> NodeResult:
        return NodeResult(
            output_items=[item],
            metadata={"success": True, "iterations": iterations, "limit_reached": limit_reached},
        )
