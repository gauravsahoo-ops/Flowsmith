"""Background relay that drains the transactional outbox.

Each pass opens a short-lived database session, publishes one batch, and
closes the session. The relay therefore never holds a connection or a
transaction between intervals.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

from sqlalchemy.orm import Session

from app.db import get_session
from app.platform.outbox import Publisher, relay_once

logger = logging.getLogger("platform.outbox_relay")

DEFAULT_RELAY_INTERVAL_SECONDS = 1.0
DEFAULT_BATCH_SIZE = 100
DEFAULT_MAX_ATTEMPTS = 10


class OutboxRelay:
    """Poll the outbox and publish pending events through ``publisher``."""

    def __init__(
        self,
        publisher: Publisher,
        *,
        interval: float = DEFAULT_RELAY_INTERVAL_SECONDS,
        batch_size: int = DEFAULT_BATCH_SIZE,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        session_factory: Callable[[], Session] | None = None,
    ) -> None:
        if interval <= 0:
            raise ValueError("interval must be positive")
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")
        if max_attempts <= 0:
            raise ValueError("max_attempts must be positive")
        self._publisher = publisher
        self._interval = interval
        self._batch_size = batch_size
        self._max_attempts = max_attempts
        self._session_factory = session_factory
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    @property
    def interval(self) -> float:
        return self._interval

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def run_once(self) -> int:
        """Run one relay pass and return the number of published events.

        Errors propagate to the caller (the loop logs them and retries on the
        next interval); unpublished rows remain available for the next pass.
        """
        db = (
            self._session_factory()
            if self._session_factory is not None
            else get_session()
        )
        try:
            return await relay_once(
                db,
                self._publisher,
                limit=self._batch_size,
                max_attempts=self._max_attempts,
            )
        finally:
            db.close()

    async def start(self) -> None:
        """Start the relay loop; safe to call when already running."""
        if self.running:
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._loop(), name="outbox-relay")
        logger.info("outbox relay started (interval=%.2fs)", self._interval)

    async def stop(self) -> None:
        """Signal the loop to exit and wait for the current pass to finish."""
        self._stop.set()
        task = self._task
        self._task = None
        if task is None:
            return
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("outbox relay stopped with an error")
        finally:
            logger.info("outbox relay stopped")

    async def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                published = await self.run_once()
                if published:
                    logger.debug("outbox relay published %d event(s)", published)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("outbox relay pass failed")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._interval)
            except TimeoutError:
                pass
