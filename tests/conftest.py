"""Shared fixtures for the DeleteBackground test suite.

The whole suite is hermetic: rembg is never imported, no model weights are
downloaded, no network calls are made. The few tests that exercise the
``BackgroundRemover`` class do so against a fake rembg implementation
installed into the module under test via monkeypatching.
"""

from __future__ import annotations

import io
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

# Make ``app`` importable when pytest is invoked from the project root.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Tiny PNG helpers — used by file/processor/integration tests.
# ---------------------------------------------------------------------------


def _encode_png(image: Image.Image) -> bytes:
    """Encode ``image`` as a PNG byte string."""
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def make_solid_png(
    *,
    size: tuple[int, int] = (4, 4),
    color: tuple[int, int, int, int] = (255, 0, 0, 255),
) -> bytes:
    """Return PNG bytes for a solid-color image. Useful as a tiny fixture."""
    image = Image.new("RGBA", size, color)
    return _encode_png(image)


@pytest.fixture
def solid_png_bytes() -> bytes:
    """A 4x4 opaque red PNG, ~70 bytes."""
    return make_solid_png()


@pytest.fixture
def input_folder(tmp_path: Path) -> Path:
    """An empty input directory under ``tmp_path``."""
    folder = tmp_path / "in"
    folder.mkdir()
    return folder


@pytest.fixture
def output_folder(tmp_path: Path) -> Path:
    """An empty output directory under ``tmp_path``."""
    folder = tmp_path / "out"
    folder.mkdir()
    return folder


@pytest.fixture
def populated_input_folder(input_folder: Path) -> Path:
    """Three tiny images plus one non-image file, for discovery tests."""
    (input_folder / "a.png").write_bytes(make_solid_png(color=(255, 0, 0, 255)))
    (input_folder / "b.jpg").write_bytes(make_solid_png(color=(0, 255, 0, 255)))
    (input_folder / "c.webp").write_bytes(make_solid_png(color=(0, 0, 255, 255)))
    (input_folder / "readme.txt").write_text("not an image")
    return input_folder


# ---------------------------------------------------------------------------
# Fake rembg — installed on demand by tests that exercise the remover layer.
# ---------------------------------------------------------------------------


class _FakeSession:
    """Stand-in for a rembg ONNX session."""

    def __init__(self, model_name: str) -> None:
        self.model_name = model_name
        self.calls = 0


def _fake_remove(source: Any, *, session: Any, **_: Any) -> Image.Image:
    """Return a fully transparent copy of the input — enough to round-trip PNG."""
    session.calls += 1
    if isinstance(source, (bytes, bytearray)):
        image = Image.open(io.BytesIO(bytes(source)))
        image.load()
    else:
        image = source
    rgba = image.convert("RGBA") if image.mode != "RGBA" else image.copy()
    # Wipe the alpha so we can tell "background removed" output apart from
    # the input in assertions.
    pixels = rgba.load()
    assert pixels is not None
    for y in range(rgba.height):
        for x in range(rgba.width):
            r, g, b, _ = pixels[x, y]
            pixels[x, y] = (r, g, b, 0)
    return rgba


def _install_fake_rembg(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Patch the lazy rembg import in :mod:`app.core.background_remover`.

    Returns a small dict the caller can inspect to assert how often
    ``new_session`` was invoked.
    """
    from app.core import background_remover as br

    counters = {"new_session_calls": 0}

    def fake_new_session(name: str, *_: Any, **__: Any) -> _FakeSession:
        counters["new_session_calls"] += 1
        return _FakeSession(name)

    monkeypatch.setattr(br, "_rembg_remove", _fake_remove)
    monkeypatch.setattr(br, "_rembg_new_session", fake_new_session)
    # Short-circuit the lazy importer so it does not overwrite our patches.
    monkeypatch.setattr(br, "_import_rembg", lambda: None)
    return counters


@pytest.fixture
def fake_rembg(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Install the fake rembg into the background_remover module."""
    return _install_fake_rembg(monkeypatch)


# ---------------------------------------------------------------------------
# Preferences store isolation.
# ---------------------------------------------------------------------------


@pytest.fixture
def isolated_settings_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Path:
    """Redirect the singleton preferences store to a temporary file.

    Each test that touches preferences must use this fixture so the on-disk
    ``settings.json`` at the project root is never mutated.
    """
    from app import config as app_config

    settings_path = tmp_path / "settings.json"
    fresh_store = app_config.PreferencesStore(settings_path)
    monkeypatch.setattr(app_config, "preferences_store", fresh_store)
    # The routes module imported the original reference — re-bind it too.
    from app.api import routes as api_routes

    monkeypatch.setattr(api_routes, "preferences_store", fresh_store)
    return settings_path


# ---------------------------------------------------------------------------
# FastAPI test client with the real app but a fake remover.
# ---------------------------------------------------------------------------


class _RecordingRemover:
    """Minimal stand-in for ``BackgroundRemover`` used by API/processor tests."""

    def __init__(self) -> None:
        self.warmup_calls: list[str] = []
        self.process_calls: list[Path] = []

    def warmup(self, model_name: str) -> None:
        self.warmup_calls.append(model_name)

    def process_file(self, *, input_path: Path, model_name: str, options: Any) -> bytes:
        self.process_calls.append(input_path)
        with Image.open(input_path) as image:
            image.load()
            transparent = image.convert("RGBA")
            pixels = transparent.load()
            assert pixels is not None
            for y in range(transparent.height):
                for x in range(transparent.width):
                    r, g, b, _ = pixels[x, y]
                    pixels[x, y] = (r, g, b, 0)
            buf = io.BytesIO()
            transparent.save(buf, format="PNG", optimize=False, compress_level=1)
            return buf.getvalue()


@pytest.fixture
def fake_remover() -> _RecordingRemover:
    """A drop-in replacement for the real remover that needs no model."""
    return _RecordingRemover()


@pytest.fixture
def client(
    fake_remover: _RecordingRemover,
    isolated_settings_file: Path,  # noqa: ARG001 — required for isolation
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[Any]:
    """Yield a ``TestClient`` wired to the real FastAPI app with a fake remover."""
    from fastapi.testclient import TestClient

    from app import main as app_main
    from app.core import background_remover as br

    monkeypatch.setattr(br, "BackgroundRemover", lambda: fake_remover)
    monkeypatch.setattr(app_main, "BackgroundRemover", lambda: fake_remover)

    app = app_main.create_app()
    # ``lifespan`` runs inside ``TestClient``; the real BackgroundRemover()
    # call was patched above so no model is loaded.
    with TestClient(app) as test_client:
        yield test_client
