"""Batch job orchestration.

Owns the lifecycle of a single in-process job: discovery, work distribution
across a thread pool, progress accounting, cancellation, and broadcasting
progress events to subscribers.

Only one job may be active at a time — this matches the single-user nature
of a local desktop-style web app and keeps GPU/CPU utilisation predictable.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Final

from app.config import UserPreferences, settings
from app.core.background_remover import BackgroundRemover, RemovalOptions
from app.core.exceptions import (
    FolderNotFoundError,
    JobAlreadyRunningError,
    JobNotRunningError,
)
from app.core.file_manager import (
    atomic_write_bytes,
    ensure_directory,
    ensure_output_directory,
    is_already_processed,
    iter_images,
    output_path_for,
)
from app.models.schemas import JobStatus, ProgressEvent

logger = logging.getLogger(__name__)

# Throttle outbound progress messages so the WebSocket isn't flooded.
_PROGRESS_MIN_INTERVAL: Final[float] = 0.1  # seconds

# Models whose ONNX session is memory-bound rather than CPU-bound. Running
# more than one inference at a time multiplies peak RAM with no throughput
# gain (the session is already internally multi-threaded), and on a 16 GB
# machine the OS quickly swaps and the display compositor stalls.
_MEMORY_BOUND_MODEL_PREFIXES: Final[tuple[str, ...]] = ("birefnet",)


def _effective_max_workers(prefs: UserPreferences) -> int:
    """Cap worker count for memory-heavy configurations.

    Alpha matting allocates ~1.8 GB per image for a 1024² input, and
    BiRefNet sessions hold ~1.5 GB resident during inference. Either alone
    plus a 4-worker pool exhausts a 16 GB system.
    """
    configured = settings.max_workers
    if prefs.alpha_matting:
        return 1
    if any(prefs.model_name.startswith(p) for p in _MEMORY_BOUND_MODEL_PREFIXES):
        return 1
    return configured


def _is_out_of_memory(exc: BaseException) -> bool:
    """Return True for OS- or ONNX-level allocation failures."""
    if isinstance(exc, MemoryError):
        return True
    # ONNX Runtime surfaces ``std::bad_alloc`` as a RuntimeException whose
    # message contains "bad allocation". numpy raises its own subclass of
    # MemoryError (_ArrayMemoryError) which the isinstance check above
    # already covers.
    return "bad allocation" in str(exc).lower()


ProgressSink = Callable[[ProgressEvent], Awaitable[None]]


@dataclass
class _Counters:
    total: int = 0
    processed: int = 0
    skipped: int = 0
    failed: int = 0


def _hex_to_rgba(color: str) -> tuple[int, int, int, int] | None:
    """Convert ``#RRGGBB`` or ``#RRGGBBAA`` to an RGBA tuple, or None."""
    if not color:
        return None
    raw = color.lstrip("#")
    if len(raw) == 6:
        r, g, b = (int(raw[i : i + 2], 16) for i in (0, 2, 4))
        return (r, g, b, 255)
    if len(raw) == 8:
        r, g, b, a = (int(raw[i : i + 2], 16) for i in (0, 2, 4, 6))
        return (r, g, b, a)
    return None


def _build_options(prefs: UserPreferences) -> RemovalOptions:
    return RemovalOptions(
        alpha_matting=prefs.alpha_matting,
        alpha_matting_foreground_threshold=prefs.alpha_matting_foreground_threshold,
        alpha_matting_background_threshold=prefs.alpha_matting_background_threshold,
        alpha_matting_erode_size=prefs.alpha_matting_erode_size,
        background_color=_hex_to_rgba(prefs.background_color),
        png_compression=prefs.png_compression,
    )


class BatchProcessor:
    """Drive a single batch job and expose its progress."""

    def __init__(self, remover: BackgroundRemover) -> None:
        self._remover = remover
        self._lock = RLock()
        self._task: asyncio.Task[None] | None = None
        self._cancel_requested: bool = False
        self._counters = _Counters()
        self._status: JobStatus = JobStatus(
            state="idle", total=0, processed=0, skipped=0, failed=0
        )
        self._subscribers: set[ProgressSink] = set()
        self._last_emit: float = 0.0
        self._started_at: float | None = None
        # Set by a worker when it hits an OOM that means continuing is
        # pointless (and dangerous: more inferences will starve the OS).
        self._oom_aborted: str | None = None

    # ------------------------------------------------------------------
    # Subscription management
    # ------------------------------------------------------------------

    def subscribe(self, sink: ProgressSink) -> None:
        """Register ``sink`` to receive progress events."""
        with self._lock:
            self._subscribers.add(sink)

    def unsubscribe(self, sink: ProgressSink) -> None:
        with self._lock:
            self._subscribers.discard(sink)

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    @property
    def status(self) -> JobStatus:
        with self._lock:
            return self._status.model_copy()

    @property
    def is_running(self) -> bool:
        with self._lock:
            return self._status.state in ("running", "cancelling")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def request_cancel(self) -> None:
        """Ask the running job to stop at the next image boundary."""
        with self._lock:
            if not self.is_running:
                raise JobNotRunningError("No job is currently running.")
            self._cancel_requested = True
            self._status = self._status.model_copy(update={"state": "cancelling"})

    async def start(self, *, prefs: UserPreferences, force: bool) -> JobStatus:
        """Kick off a new job. Returns the initial status snapshot."""
        with self._lock:
            if self.is_running:
                raise JobAlreadyRunningError("A job is already in progress.")
            self._cancel_requested = False
            self._oom_aborted = None
            self._counters = _Counters()
            self._started_at = time.monotonic()
            self._status = JobStatus(
                state="running",
                total=0,
                processed=0,
                skipped=0,
                failed=0,
                started_at=time.time(),
            )

        # Validate folders before spawning the task so the caller gets a
        # synchronous error.
        input_root = ensure_directory(Path(prefs.input_folder))
        output_root = ensure_output_directory(Path(prefs.output_folder))

        self._task = asyncio.create_task(
            self._run(prefs=prefs, force=force, input_root=input_root, output_root=output_root)
        )
        await self._broadcast(ProgressEvent(type="status", status=self.status))
        return self.status

    # ------------------------------------------------------------------
    # Core run loop
    # ------------------------------------------------------------------

    async def _run(
        self,
        *,
        prefs: UserPreferences,
        force: bool,
        input_root: Path,
        output_root: Path,
    ) -> None:
        options = _build_options(prefs)
        loop = asyncio.get_running_loop()

        files = list(iter_images(input_root, prefs.recursive))
        with self._lock:
            self._counters.total = len(files)
            self._status = self._status.model_copy(update={"total": len(files)})

        if not files:
            await self._finish(state="completed", message="No images found.")
            return

        # Warm up the model in the worker pool so first-image latency is fair.
        try:
            await asyncio.to_thread(self._remover.warmup, prefs.model_name)
        except Exception as exc:
            logger.exception("Model warmup failed.")
            await self._finish(state="failed", message=str(exc))
            return

        max_workers = _effective_max_workers(prefs)
        if max_workers != settings.max_workers:
            logger.info(
                "Capping workers to %d for memory-heavy config "
                "(model=%s, alpha_matting=%s).",
                max_workers,
                prefs.model_name,
                prefs.alpha_matting,
            )
        executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="dbg-worker",
        )

        try:
            pending: set[asyncio.Task[None]] = set()
            try:
                for file in files:
                    if self._cancel_requested or self._oom_aborted is not None:
                        break
                    # Cap in-flight tasks to keep memory bounded.
                    if len(pending) >= max_workers:
                        done, pending = await asyncio.wait(
                            pending, return_when=asyncio.FIRST_COMPLETED
                        )
                        for d in done:
                            # Surface unexpected exceptions.
                            exc = d.exception()
                            if exc is not None:
                                logger.error("Worker task failed: %s", exc)
                    task = loop.create_task(
                        self._process_one(
                            executor=executor,
                            file=file,
                            input_root=input_root,
                            output_root=output_root,
                            prefs=prefs,
                            options=options,
                            force=force,
                        )
                    )
                    pending.add(task)
                if pending:
                    await asyncio.gather(*pending, return_exceptions=True)
            finally:
                # Drain any task that survived a cancel break.
                for t in pending:
                    if not t.done():
                        t.cancel()
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

        if self._oom_aborted is not None:
            await self._finish(state="failed", message=self._oom_aborted)
            return
        state = "cancelled" if self._cancel_requested else "completed"
        await self._finish(state=state)

    async def _process_one(
        self,
        *,
        executor: ThreadPoolExecutor,
        file: Path,
        input_root: Path,
        output_root: Path,
        prefs: UserPreferences,
        options: RemovalOptions,
        force: bool,
    ) -> None:
        if self._cancel_requested or self._oom_aborted is not None:
            return

        destination = output_path_for(
            input_file=file, input_root=input_root, output_root=output_root
        )
        try:
            output_relative = destination.relative_to(output_root).as_posix()
        except ValueError:
            output_relative = destination.name

        if not force and prefs.skip_existing and is_already_processed(file, destination):
            with self._lock:
                self._counters.skipped += 1
                self._refresh_status(current=file.name, output_relative=output_relative)
            await self._maybe_broadcast()
            return

        loop = asyncio.get_running_loop()
        try:
            png_bytes = await loop.run_in_executor(
                executor,
                lambda: self._remover.process_file(
                    input_path=file,
                    model_name=prefs.model_name,
                    options=options,
                ),
            )
            await asyncio.to_thread(atomic_write_bytes, destination, png_bytes)
            with self._lock:
                self._counters.processed += 1
                self._refresh_status(current=file.name, output_relative=output_relative)
        except Exception as exc:
            logger.exception("Failed to process %s", file)
            with self._lock:
                self._counters.failed += 1
                if _is_out_of_memory(exc) and self._oom_aborted is None:
                    self._oom_aborted = (
                        f"Out of memory while processing {file.name}. "
                        "Try a lighter model (e.g. isnet-general-use or "
                        "u2netp), disable alpha matting, or close other "
                        "applications to free RAM."
                    )
                    self._status = self._status.model_copy(
                        update={"last_error": self._oom_aborted}
                    )
                else:
                    self._status = self._status.model_copy(
                        update={"last_error": f"{file.name}: {exc}"}
                    )
                self._refresh_status(current=file.name, output_relative=output_relative)

        await self._maybe_broadcast()

    # ------------------------------------------------------------------
    # Status helpers
    # ------------------------------------------------------------------

    def _refresh_status(
        self, *, current: str | None, output_relative: str | None = None
    ) -> None:
        elapsed = (
            time.monotonic() - self._started_at if self._started_at is not None else None
        )
        avg = (
            elapsed / self._counters.processed
            if elapsed and self._counters.processed
            else None
        )
        self._status = self._status.model_copy(
            update={
                "processed": self._counters.processed,
                "skipped": self._counters.skipped,
                "failed": self._counters.failed,
                "current_file": current,
                "current_output_relative": output_relative,
                "duration_seconds": elapsed,
                "average_seconds_per_image": avg,
            }
        )

    async def _finish(self, *, state: str, message: str | None = None) -> None:
        with self._lock:
            elapsed = (
                time.monotonic() - self._started_at
                if self._started_at is not None
                else None
            )
            self._status = self._status.model_copy(
                update={
                    "state": state,
                    "finished_at": time.time(),
                    "duration_seconds": elapsed,
                    "current_file": None,
                    "current_output_relative": None,
                }
            )
            self._cancel_requested = False
            self._task = None
            self._started_at = None
        await self._broadcast(
            ProgressEvent(type="done", status=self.status, message=message)
        )

    async def _maybe_broadcast(self) -> None:
        now = time.monotonic()
        if now - self._last_emit < _PROGRESS_MIN_INTERVAL:
            return
        self._last_emit = now
        await self._broadcast(ProgressEvent(type="item", status=self.status))

    async def _broadcast(self, event: ProgressEvent) -> None:
        # Copy under lock to avoid mutation during iteration.
        with self._lock:
            sinks = list(self._subscribers)
        for sink in sinks:
            try:
                await sink(event)
            except Exception as exc:
                logger.warning("Progress sink raised %s; dropping.", exc)
                self.unsubscribe(sink)
