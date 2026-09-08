"""In-process background runner (single-worker v1 of spec 13).

Executions run on a dedicated event loop in a daemon thread, so they
survive request completion, are never cancelled by the API framework
(TestClient included), and can be cancelled explicitly via the cancel
endpoint. A real queue lands with M7 triggers.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable, Coroutine
from typing import Any, TypeVar

T = TypeVar("T")

CoroFactory = Callable[[], Coroutine[Any, Any, T]]


class BackgroundRunner:
    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._http_client: Any | None = None
        self._shutting_down = False

    def _ensure_started(self) -> asyncio.AbstractEventLoop:
        with self._lock:
            if self._loop is not None:
                return self._loop
            self._shutting_down = False
            loop = asyncio.new_event_loop()

            def _run() -> None:
                asyncio.set_event_loop(loop)
                loop.run_forever()

            self._thread = threading.Thread(target=_run, name="background-runner", daemon=True)
            self._thread.start()
            self._loop = loop
            return loop

    def submit(self, factory: CoroFactory) -> asyncio.Task:
        """Run `factory()` on the worker loop. The coroutine is created
        there, so asyncio primitives inside bind to the worker loop."""
        if self._shutting_down:
            raise RuntimeError("runner is shutting down")
        loop = self._ensure_started()
        ready = threading.Event()
        task: asyncio.Task | None = None

        def _start() -> None:
            nonlocal task
            task = loop.create_task(factory())
            ready.set()

        loop.call_soon_threadsafe(_start)
        ready.wait(10)
        assert task is not None
        return task

    def shutdown(self, timeout_s: float = 5.0) -> None:
        """Gracefully stop the worker loop: cancel pending tasks, close the
        HTTP client, and stop the loop."""
        with self._lock:
            if self._loop is None or self._shutting_down:
                return
            self._shutting_down = True
            loop = self._loop

        async def _cleanup() -> None:
            # Cancel all pending tasks
            for task in asyncio.all_tasks(loop):
                if not task.done():
                    task.cancel()
            # Wait for cancellations to propagate
            await asyncio.gather(*asyncio.all_tasks(loop), return_exceptions=True)
            # Close the shared HTTP client
            if self._http_client is not None:
                await self._http_client.aclose()
                self._http_client = None

        future = asyncio.run_coroutine_threadsafe(_cleanup(), loop)
        try:
            future.result(timeout=timeout_s)
        except Exception:
            pass
        loop.call_soon_threadsafe(loop.stop)
        if self._thread is not None:
            self._thread.join(timeout=timeout_s)
        with self._lock:
            self._loop = None
            self._thread = None

    def on_loop(self, fn: Callable[[], None]) -> None:
        """Run a sync callback on the worker loop (fire and forget)."""
        self._ensure_started().call_soon_threadsafe(fn)

    @property
    def loop(self) -> asyncio.AbstractEventLoop | None:
        """The worker loop, if the runner has been started."""
        return self._loop

    def get_http_client(self) -> Any:
        """Shared httpx client for executions. Built once (creating an
        AsyncClient per execution is expensive: it loads the SSL context,
        which blocks the worker loop for seconds)."""
        with self._lock:
            if self._http_client is None:
                import httpx

                self._http_client = httpx.AsyncClient(timeout=httpx.Timeout(30.0))
            return self._http_client


runner = BackgroundRunner()