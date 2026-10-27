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


class _DbEventSink:
    """Durable event sink that reuses one session for an execution.

    Opening a fresh session/connection for every streamed event dominated
    the external-worker hot path. The sink initializes the sequence once,
    reuses the session, and the worker closes it after ``run_job``.
    """

    def __init__(self, execution_id: str) -> None:
        from app.db import get_session
        from app.models import ExecutionEvent

        self.execution_id = execution_id
        self._execution_event = ExecutionEvent
        self.db = get_session()
        self._pending: list[Any] = []
        self._last_flush = time.monotonic()
        self._flush_interval_s = 0.1
        self._batch_size = 50
        try:
            last = (
                self.db.query(ExecutionEvent)
                .where(ExecutionEvent.execution_id == execution_id)
                .order_by(ExecutionEvent.seq.desc())
                .first()
            )
            self.seq = last.seq if last is not None else 0
        except Exception:
            logger.exception("failed to initialize event sink for %s", execution_id)
            self.seq = 0

    def _flush(self) -> None:
        if not self._pending:
            self._last_flush = time.monotonic()
            return
        try:
            self.db.add_all(self._pending)
            self.db.commit()
            self._pending.clear()
        except Exception:
            self.db.rollback()
            self._pending.clear()
            logger.exception("failed to persist batched events for %s", self.execution_id)
        finally:
            self._last_flush = time.monotonic()

    def __call__(self, event: dict[str, Any]) -> None:
        self.seq += 1
        self._pending.append(self._execution_event(
            execution_id=self.execution_id,
            seq=self.seq,
            event=event.get("event", ""),
            node_id=event.get("node_id"),
            status=event.get("status"),
            error=event.get("error"),
        ))
        if (
            len(self._pending) >= self._batch_size
            or time.monotonic() - self._last_flush >= self._flush_interval_s
        ):
            self._flush()

    def close(self) -> None:
        self._flush()
        self.db.close()


def _event_sink_to_db(execution_id: str) -> _DbEventSink:
    """Persist events durably (external workers, spec 37)."""
    return _DbEventSink(execution_id)


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
            close_sink = getattr(sink, "close", None)
            if callable(close_sink):
                close_sink()

        # A waiting_approval execution's job is done: the row stays open
        # until resume/cancel (spec 25.3: executions are authoritative).
        self.queue.complete(
            job.id,
            DONE if status in ("success", "cancelled", "timeout", "waiting_approval", "waiting_auth") else FAILED,
        )
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
        try:
            hb.write_text(str(os.getpid()))
        except Exception:
            pass
        last_hb_write = time.monotonic()
        while not self._stop.is_set():
            had_job = False
            try:
                now = time.monotonic()
                if now - last_hb_write >= 15.0:
                    hb.write_text(str(os.getpid()))
                    last_hb_write = now
                had_job = await self.consume_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("worker iteration failed")
            if not had_job and not self._stop.is_set():
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
    # External workers must enforce the same production config gates as
    # the API process (JWT secret, encryption key, DB, CORS).
    from app.config import validate_production_settings

    validate_production_settings()
    # Connector-only node types must resolve in external workers too.
    from app.connectors import register_builtin_connectors

    register_builtin_connectors()

    # In production and staging, ensure schema migrations have reached expected head
    # before claiming jobs from the queue to avoid races against in-flight DDL.
    from app.config import get_settings
    settings = get_settings()
    if settings.app_env in ("production", "staging"):
        from app.db import (
            get_engine,
            verify_schema_state,
            _run_alembic_upgrade,
            _migrate_missing_columns,
            _migrate_missing_indexes,
        )
        eng = get_engine()
        deadline = time.monotonic() + 30.0
        while time.monotonic() < deadline:
            try:
                state = verify_schema_state(eng)
                if state.get("ok"):
                    logger.info("worker: database schema verified at head revision %s", state.get("current_revision"))
                    _migrate_missing_columns()
                    _migrate_missing_indexes()
                    break
                logger.info(
                    "worker: database schema not at head yet (current=%s, expected=%s); waiting for migrations...",
                    state.get("current_revision"),
                    state.get("expected_revision"),
                )
            except Exception as exc:
                logger.warning("worker: error checking schema state: %s; waiting...", exc)
            time.sleep(2)
        else:
            state = verify_schema_state(eng)
            # Self-healing fallback: if app container did not complete migrations within 30s,
            # execute serialized Alembic upgrade under PostgreSQL advisory lock.
            run_migrations = getattr(settings, "run_migrations_on_startup", True)
            if not state.get("ok") and run_migrations:
                logger.warning(
                    "worker: database schema not at head after 30s wait (current=%s, expected=%s); "
                    "running serialized Alembic migration under PostgreSQL advisory lock...",
                    state.get("current_revision"),
                    state.get("expected_revision"),
                )
                try:
                    _run_alembic_upgrade()
                    _migrate_missing_columns()
                    _migrate_missing_indexes()
                    state = verify_schema_state(eng)
                    if state.get("ok"):
                        logger.info("worker: database schema successfully migrated to head revision %s", state.get("current_revision"))
                except Exception as mexc:
                    logger.exception("worker: migration attempt failed: %s", mexc)

            if not state.get("ok"):
                logger.error("worker: startup aborted — database schema is not at expected head: %s", state)
                sys.exit(1)
    else:
        from app.db import _migrate_missing_columns, _migrate_missing_indexes
        _migrate_missing_columns()
        _migrate_missing_indexes()

    # Packs are stored in PostgreSQL; materialize them only after the schema
    # is confirmed current so a fresh worker does not query missing tables.
    try:
        from app.services.connector_pack_runtime import load_installed_packs

        load_installed_packs()
    except Exception:
        logger.exception("worker: installed connector packs could not be loaded")

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

    async def _run_worker() -> None:
        from app.services.connector_pack_reconciler import pack_reconciler

        await pack_reconciler.ensure_started()
        try:
            await worker.run_forever()
        finally:
            await pack_reconciler.stop()

    try:
        loop.run_until_complete(_run_worker())
    except KeyboardInterrupt:
        pass
    finally:
        loop.close()


if __name__ == "__main__":
    sys.exit(main())
