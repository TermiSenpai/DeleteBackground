"""Tests for :mod:`app.core.batch_processor`.

These tests drive the real ``BatchProcessor`` against the lightweight
``_RecordingRemover`` from :mod:`tests.conftest`. ``asyncio`` is exercised via
``pytest-asyncio`` so the lifecycle (start → process → finish) is observed
end-to-end without the real ONNX session.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from PIL import Image

from app.config import UserPreferences
from app.core.batch_processor import (
    BatchProcessor,
    _build_options,
    _effective_max_workers,
    _hex_to_rgba,
)
from app.core.exceptions import JobAlreadyRunningError, JobNotRunningError
from app.models.schemas import ProgressEvent
from tests.conftest import _RecordingRemover, make_solid_png


def _prefs_for(input_folder: Path, output_folder: Path, **overrides: object) -> UserPreferences:
    base = {
        "input_folder": str(input_folder),
        "output_folder": str(output_folder),
        "model_name": "u2netp",
    }
    base.update(overrides)
    return UserPreferences(**base)  # type: ignore[arg-type]


async def _wait_for_done(events: list[ProgressEvent], timeout: float = 5.0) -> None:
    """Wait until a ``done`` event is captured by the subscribed sink."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if any(e.type == "done" for e in events):
            return
        await asyncio.sleep(0.02)
    raise AssertionError(f"Job never finished. Captured: {[e.type for e in events]}")


@pytest.fixture
def collected_events() -> list[ProgressEvent]:
    return []


@pytest.fixture
def processor_with_sink(
    fake_remover: _RecordingRemover,
    collected_events: list[ProgressEvent],
) -> BatchProcessor:
    p = BatchProcessor(fake_remover)  # type: ignore[arg-type]

    async def sink(event: ProgressEvent) -> None:
        collected_events.append(event)

    p.subscribe(sink)
    return p


class TestHelpers:
    @pytest.mark.parametrize(
        "color, expected",
        [
            ("", None),
            ("#ff0000", (255, 0, 0, 255)),
            ("#00FF0080", (0, 255, 0, 128)),
            ("not-hex", None),
        ],
    )
    def test_hex_to_rgba(
        self, color: str, expected: tuple[int, int, int, int] | None
    ) -> None:
        assert _hex_to_rgba(color) == expected

    def test_build_options_uses_preference_values(self) -> None:
        prefs = UserPreferences(
            png_compression=6,
            alpha_matting=True,
            background_color="#112233",
        )
        opts = _build_options(prefs)
        assert opts.png_compression == 6
        assert opts.alpha_matting is True
        assert opts.background_color == (17, 34, 51, 255)

    def test_effective_max_workers_caps_for_alpha_matting(self) -> None:
        prefs = UserPreferences(alpha_matting=True)
        assert _effective_max_workers(prefs) == 1

    def test_effective_max_workers_caps_for_birefnet(self) -> None:
        prefs = UserPreferences(model_name="birefnet-general")
        assert _effective_max_workers(prefs) == 1


class TestJobLifecycle:
    pytestmark = pytest.mark.asyncio

    async def test_empty_folder_completes_immediately(
        self,
        processor_with_sink: BatchProcessor,
        collected_events: list[ProgressEvent],
        input_folder: Path,
        output_folder: Path,
    ) -> None:
        prefs = _prefs_for(input_folder, output_folder)
        await processor_with_sink.start(prefs=prefs, force=False)
        await _wait_for_done(collected_events)
        assert processor_with_sink.status.state == "completed"
        assert processor_with_sink.status.total == 0

    async def test_full_batch_writes_outputs(
        self,
        processor_with_sink: BatchProcessor,
        collected_events: list[ProgressEvent],
        populated_input_folder: Path,
        output_folder: Path,
        fake_remover: _RecordingRemover,
    ) -> None:
        prefs = _prefs_for(populated_input_folder, output_folder)
        await processor_with_sink.start(prefs=prefs, force=False)
        await _wait_for_done(collected_events)

        status = processor_with_sink.status
        assert status.state == "completed"
        assert status.processed == 3
        assert status.failed == 0
        assert fake_remover.warmup_calls == ["u2netp"]
        produced = sorted(p.name for p in output_folder.glob("*.png"))
        assert produced == ["a.png", "b.png", "c.png"]
        # All outputs should be openable PNGs with transparency.
        for png in output_folder.glob("*.png"):
            with Image.open(png) as image:
                image.load()
                assert image.mode == "RGBA"

    async def test_skip_existing_avoids_reprocessing(
        self,
        processor_with_sink: BatchProcessor,
        collected_events: list[ProgressEvent],
        populated_input_folder: Path,
        output_folder: Path,
        fake_remover: _RecordingRemover,
    ) -> None:
        prefs = _prefs_for(populated_input_folder, output_folder)
        # Pre-create outputs that are newer than inputs.
        for name in ("a.png", "b.png", "c.png"):
            (output_folder / name).write_bytes(make_solid_png())
            import os
            inp = populated_input_folder / name.replace(".png", "")
            # Match by stem to the original file.
            candidates = list(populated_input_folder.glob(f"{name.split('.')[0]}.*"))
            if candidates:
                os.utime(
                    output_folder / name,
                    (candidates[0].stat().st_atime, candidates[0].stat().st_mtime + 5),
                )
        await processor_with_sink.start(prefs=prefs, force=False)
        await _wait_for_done(collected_events)
        status = processor_with_sink.status
        assert status.processed == 0
        assert status.skipped == 3
        assert fake_remover.process_calls == []

    async def test_force_overrides_skip(
        self,
        processor_with_sink: BatchProcessor,
        collected_events: list[ProgressEvent],
        populated_input_folder: Path,
        output_folder: Path,
        fake_remover: _RecordingRemover,
    ) -> None:
        prefs = _prefs_for(populated_input_folder, output_folder)
        for name in ("a.png", "b.png", "c.png"):
            (output_folder / name).write_bytes(make_solid_png())
        await processor_with_sink.start(prefs=prefs, force=True)
        await _wait_for_done(collected_events)
        assert processor_with_sink.status.processed == 3
        assert processor_with_sink.status.skipped == 0
        assert len(fake_remover.process_calls) == 3

    async def test_starting_twice_raises(
        self,
        processor_with_sink: BatchProcessor,
        collected_events: list[ProgressEvent],
        populated_input_folder: Path,
        output_folder: Path,
    ) -> None:
        prefs = _prefs_for(populated_input_folder, output_folder)
        await processor_with_sink.start(prefs=prefs, force=False)
        try:
            with pytest.raises(JobAlreadyRunningError):
                await processor_with_sink.start(prefs=prefs, force=False)
        finally:
            await _wait_for_done(collected_events)

    async def test_cancel_when_idle_raises(
        self, processor_with_sink: BatchProcessor
    ) -> None:
        with pytest.raises(JobNotRunningError):
            processor_with_sink.request_cancel()

    async def test_failed_image_does_not_abort_batch(
        self,
        processor_with_sink: BatchProcessor,
        collected_events: list[ProgressEvent],
        populated_input_folder: Path,
        output_folder: Path,
        fake_remover: _RecordingRemover,
    ) -> None:
        original = fake_remover.process_file

        def flaky(*, input_path: Path, model_name: str, options: object) -> bytes:
            if input_path.name == "b.jpg":
                raise ValueError("simulated decode failure")
            return original(
                input_path=input_path, model_name=model_name, options=options
            )

        fake_remover.process_file = flaky  # type: ignore[assignment,method-assign]

        prefs = _prefs_for(populated_input_folder, output_folder)
        await processor_with_sink.start(prefs=prefs, force=False)
        await _wait_for_done(collected_events)

        status = processor_with_sink.status
        assert status.state == "completed"
        assert status.processed == 2
        assert status.failed == 1
        assert "b.jpg" in (status.last_error or "")
