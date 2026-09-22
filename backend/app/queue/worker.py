"""Queue workers (Phase 15, spec 13/34/58).

Two consumption modes share one loop body:

- **Embedded consumer** — started lazily inside the API process when
  ``queue_embedded_consumer`` is true (dev default). Events stream over
  the in-process bus, so the WebSocket works exactly as before.
- **External worker** — ``python -m app.queue.worker``: a stateless
  process that claims jobs from the shared queue, executes them and
  persists events durably (``execution_events`` table). Run as many
  replicas as you like (spec 58); the claim is atomic so each job runs
  exactly once (recovered after crashes via the stale heartbeat).

Both publish the same ``QueueWorker.consume_once`` body; the only
difference is the event sink and where the loop lives.
"""

from __future__ import annotations

import asyncio
import logging
import signal
import sys
import time
from typing import Any

from app.config import get_settings
from app.execution_runtime import run_job
from app.models.job import DONE, FAILED
from app.queue import QueueBackend, QueueJob, get_queue
from app.security.jwt import get_worker_id

logger = logging.getLogger("queue.worker")

_consumer_started = False
_consumer_task: Any = None


def _event_sink_to_db(execution_id: str) -> Any:
    """Persist events durably (external workers, spec 37)."""
    from app.db import get_session
    from app.models import ExecutionEvent

    def sink(event: dict[str, Any]) -> None:
        db = get_session()
        try:
            last = (
                db.query(ExecutionEvent)
                .where(ExecutionEvent.execution_id == execution_id)
                .order_by(ExecutionEvent.seq.desc())
                .first()
            )
            seq = (last.seq if last is not None else 0) + 1
            db.add(ExecutionEvent(
                execution_id=execution_id,
                seq=seq,
                event=event.get("event", ""),
                node_id=event.get("node_id"),
                status=event.get("status"),
                error=event.get("error"),
            ))
            db.commit()
        except Exception:
            logger.exception("failed to persist event for %s", execution_id)
        finally:
            db.close()

    return sink


class QueueWorker:
    """A single worker loop: claim -> execute -> complete, with a
    heartbeat task while a job runs and a stale-claim sweep when idle."""

    def __init__(
        self,
        *,
        queue: QueueBackend | None = None,
        event_sink: Any = None,
        poll_interval_s: float | None = None,
        heartbeat_s: float | None = None,
        stale_seconds: float | None = None,
        sweep_s: float | None = None,
        orphan_sweep_s: float | None = None,
    ) -> None:
        settings = get_settings()
        self.queue = queue or get_queue()
        self.event_sink = event_sink
        self.poll_interval_s = poll_interval_s if poll_interval_s is not None else settings.worker_poll_interval_s
        self.heartbeat_s = heartbeat_s if heartbeat_s is not None else settings.worker_heartbeat_s
        self.stale_seconds = stale_seconds if stale_seconds is not None else settings.worker_stale_seconds
        self.sweep_s = sweep_s if sweep_s is not None else settings.worker_stale_sweep_s
        self.orphan_sweep_s = (
            orphan_sweep_s if orphan_sweep_s is not None else settings.orphan_sweep_interval_s
        )
        self._stop = asyncio.Event()
        self._last_sweep = 0.0
        self._last_orphan_sweep = 0.0

    def stop(self) -> None:
        self._stop.set()

    async def recover_stale_once(self, stale_seconds: float | None = None) -> int:
        """One stale-claim recovery sweep; returns the number re-queued."""
        return self.queue.recover_stale(
            stale_seconds if stale_seconds is not None else self.stale_seconds
        )

    async def consume_once(self) -> bool:
        """Claim and run one job (or recover stale claims when idle).
        Returns True when a job was processed."""
        job: QueueJob | None = None
        try:
            job = self.queue.claim()
        except Exception:
            logger.exception("queue claim failed")
            return False

        if job is None:
            if time.monotonic() - self._last_sweep >= self.sweep_s:
                self._last_sweep = time.monotonic()
                try:
                    self.queue.recover_stale(self.stale_seconds)
                except Exception:
                    logger.exception("stale recovery sweep failed")
            # Orphan reconciliation (audit phase 11): executions whose
            # authoritative row says queued but whose transport job is gone
            # (Redis flush / data loss). Runs only while idle; enqueue
            # idempotency keeps concurrent sweeps safe.
            if time.monotonic() - self._last_orphan_sweep >= self.orphan_sweep_s:
                self._last_orphan_sweep = time.monotonic()
                try:
                    from app.config import get_settings as _gs
                    from app.maintenance import recover_orphaned_executions

                    recovered = recover_orphaned_executions(
                        _gs().execution_queued_grace_s
                    )
                    if recovered:
                        logger.info("orphan sweep re-enqueued %d execution(s)", recovered)
                except Exception:
                    logger.exception("orphan reconciliation sweep failed")
            return False

        sink = self.event_sink
        if sink is None:
            sink = _event_sink_to_db(job.execution_id)

        heartbeat = asyncio.create_task(self._heartbeat(job.id))
        try:
            status = await run_job(job, sink)
        except asyncio.CancelledError:
            self.queue.complete(job.id, FAILED, {"code": "WORKER_STOPPED", "message": "Worker stopped."})
            raise
        except Exception as exc:
            logger.exception("job %s crashed in the worker", job.id)
            self.queue.complete(job.id, FAILED, {"code": "WORKER_ERROR", "message": str(exc)})
            return True
        finally:
            heartbeat.cancel()

        # A waiting_approval execution's job is done: the row stays open
        # until resume/cancel (spec 25.3: executions are authoritative).
        self.queue.complete(job.id, DONE if status in ("success", "cancelled", "timeout", "waiting_approval") else FAILED)
        return True

    async def _heartbeat(self, job_id: str) -> None:
        while not self._stop.is_set():
            try:
                self.queue.heartbeat(job_id)
            except Exception:
                logger.exception("heartbeat failed for %s", job_id)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.heartbeat_s)
            except asyncio.TimeoutError:
                pass

    async def run_forever(self) -> None:
        """Main loop for a standalone worker process."""
        import os
        import pathlib
        hb = pathlib.Path(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "tmp"))
        hb.mkdir(parents=True, exist_ok=True)
        hb = hb / "worker_alive"
        hb.write_text(str(os.getpid()))
        while not self._stop.is_set():
            try:
                hb.write_text(str(os.getpid()))
                await self.consume_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("worker iteration failed")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.poll_interval_s)
            except asyncio.TimeoutError:
                pass
        hb.unlink(missing_ok=True)
        logger.info("worker: stopping cleanly")


def ensure_embedded_consumer() -> None:
    """Start the API-process consumer once (spec 13 v1: the API process
    is also a worker unless queue_embedded_consumer is disabled)."""
    global _consumer_started, _consumer_task
    if not get_settings().queue_embedded_consumer:
        return

    from app.runner import runner

    if _consumer_started and _consumer_task is not None and not _consumer_task.done():
        if runner.loop is not None and runner.loop.is_running():
            return
    _consumer_started = True

    from app.eventbus import bus

    worker = QueueWorker(event_sink=lambda ev: bus.publish(ev.get("execution_id", ""), ev))

    async def _loop() -> None:
        global _consumer_started
        try:
            while True:
                try:
                    await worker.consume_once()
                except asyncio.CancelledError:
                    break
                except Exception:
                    logger.exception("embedded consumer iteration failed")
                try:
                    await asyncio.sleep(worker.poll_interval_s)
                except asyncio.CancelledError:
                    break
        finally:
            _consumer_started = False

    def _schedule_consumer() -> None:
        global _consumer_task
        _consumer_task = asyncio.ensure_future(_loop())

    runner.on_loop(_schedule_consumer)


def stop_embedded_consumer() -> None:
    """Cancel the embedded consumer (app shutdown / test isolation).

    Once stopped, the next `ensure_embedded_consumer()` call restarts it.
    """
    global _consumer_started, _consumer_task
    task = _consumer_task
    _consumer_task = None
    _consumer_started = False
    if task is None:
        return
    from app.runner import runner

    loop = runner.loop
    if loop is not None:
        loop.call_soon_threadsafe(task.cancel)


def main() -> None:
    """Entry point: python -m app.queue.worker"""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # Connector-only node types must resolve in external workers too.
    from app.connectors import register_builtin_connectors

    register_builtin_connectors()
    worker = QueueWorker()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    stop_signal = getattr(signal, "SIGTERM", None) or signal.SIGINT

    def _request_stop(*_args: Any) -> None:
        logger.info("worker: shutdown requested")
        loop.call_soon_threadsafe(worker.stop)

    for sig in (signal.SIGINT, stop_signal):
        try:
            signal.signal(sig, _request_stop)
        except (ValueError, OSError):  # non-main thread / unsupported
            pass

    logger.info("worker: starting (queue=%s, worker=%s)", get_queue().name, get_worker_id())
    try:
        loop.run_until_complete(worker.run_forever())
    except KeyboardInterrupt:
        pass
    finally:
        loop.close()


if __name__ == "__main__":
    sys.exit(main())
