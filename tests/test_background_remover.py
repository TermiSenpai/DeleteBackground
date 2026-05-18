"""Tests for :mod:`app.core.background_remover`.

The real rembg/ONNX session is never built. The :func:`fake_rembg` fixture
patches the lazy imports inside the module with a deterministic stand-in.
"""

from __future__ import annotations

import io
from typing import Any

import pytest
from PIL import Image

from app.core import background_remover as br
from app.core.background_remover import (
    BackgroundRemover,
    RemovalOptions,
    _downscale_to_max_side,
    _is_allocation_error,
)
from app.core.exceptions import ModelLoadError
from tests.conftest import make_solid_png


class TestRemovalOptionsDefaults:
    def test_defaults_match_user_preferences_defaults(self) -> None:
        opts = RemovalOptions()
        assert opts.alpha_matting is False
        assert opts.background_color is None
        assert opts.png_compression == 1


class TestSessionCache:
    def test_unknown_model_raises(self, fake_rembg: dict[str, Any]) -> None:
        remover = BackgroundRemover()
        with pytest.raises(ModelLoadError):
            remover.warmup("nope-model")

    def test_session_is_cached_across_calls(
        self, fake_rembg: dict[str, Any]
    ) -> None:
        remover = BackgroundRemover()
        remover.warmup("u2netp")
        remover.warmup("u2netp")
        remover.warmup("u2netp")
        assert fake_rembg["new_session_calls"] == 1

    def test_distinct_models_get_distinct_sessions(
        self, fake_rembg: dict[str, Any]
    ) -> None:
        remover = BackgroundRemover()
        remover.warmup("u2netp")
        remover.warmup("silueta")
        assert fake_rembg["new_session_calls"] == 2

    def test_new_session_error_is_wrapped(
        self, monkeypatch: pytest.MonkeyPatch, fake_rembg: dict[str, Any]
    ) -> None:
        def broken_factory(*_: Any, **__: Any) -> Any:
            raise RuntimeError("ONNX exploded")

        monkeypatch.setattr(br, "_rembg_new_session", broken_factory)
        remover = BackgroundRemover()
        with pytest.raises(ModelLoadError, match="ONNX exploded"):
            remover.warmup("u2netp")


class TestProcessBytes:
    def test_returns_transparent_png(
        self, fake_rembg: dict[str, Any]
    ) -> None:
        remover = BackgroundRemover()
        png_in = make_solid_png(size=(8, 8), color=(120, 200, 50, 255))
        png_out = remover.process_bytes(
            data=png_in, model_name="u2netp", options=RemovalOptions()
        )
        with Image.open(io.BytesIO(png_out)) as out:
            out.load()
            assert out.mode == "RGBA"
            # Every alpha pixel should be zero — the fake remover wipes alpha.
            assert all(pixel[3] == 0 for pixel in out.getdata())

    def test_solid_bgcolor_returns_rgb(
        self, fake_rembg: dict[str, Any]
    ) -> None:
        remover = BackgroundRemover()
        png_in = make_solid_png()
        out = remover.process_bytes(
            data=png_in,
            model_name="u2netp",
            options=RemovalOptions(background_color=(0, 0, 0, 255)),
        )
        with Image.open(io.BytesIO(out)) as image:
            image.load()
            assert image.mode == "RGB"

    def test_oom_triggers_downscaled_retry(
        self,
        monkeypatch: pytest.MonkeyPatch,
        fake_rembg: dict[str, Any],
    ) -> None:
        attempts: list[int] = []

        def flaky_remove(source: Any, *, session: Any, **_: Any) -> Image.Image:
            attempts.append(1)
            if len(attempts) == 1:
                raise RuntimeError("bad allocation: not enough memory")
            # Fall through to the same behaviour the fixture installed.
            from tests.conftest import _fake_remove

            return _fake_remove(source, session=session)

        monkeypatch.setattr(br, "_rembg_remove", flaky_remove)
        remover = BackgroundRemover()
        png_in = make_solid_png(size=(16, 16))
        out = remover.process_bytes(
            data=png_in, model_name="u2netp", options=RemovalOptions()
        )
        assert len(attempts) == 2  # one fail, one success on the smaller image
        with Image.open(io.BytesIO(out)) as image:
            image.load()
            assert image.mode == "RGBA"

    def test_non_oom_error_is_not_retried(
        self, monkeypatch: pytest.MonkeyPatch, fake_rembg: dict[str, Any]
    ) -> None:
        attempts: list[int] = []

        def boom(source: Any, *, session: Any, **_: Any) -> Image.Image:
            attempts.append(1)
            raise RuntimeError("unrelated failure")

        monkeypatch.setattr(br, "_rembg_remove", boom)
        remover = BackgroundRemover()
        with pytest.raises(RuntimeError, match="unrelated"):
            remover.process_bytes(
                data=make_solid_png(),
                model_name="u2netp",
                options=RemovalOptions(),
            )
        assert len(attempts) == 1


class TestProcessFile:
    def test_reads_file_and_returns_png(
        self, fake_rembg: dict[str, Any], tmp_path: Any
    ) -> None:
        path = tmp_path / "image.png"
        path.write_bytes(make_solid_png())
        remover = BackgroundRemover()
        out = remover.process_file(
            input_path=path,
            model_name="u2netp",
            options=RemovalOptions(),
        )
        assert out.startswith(b"\x89PNG\r\n\x1a\n")


class TestHelpers:
    @pytest.mark.parametrize(
        "exc, expected",
        [
            (RuntimeError("bad allocation"), True),
            (RuntimeError("OUT OF MEMORY"), True),
            (MemoryError("no ram"), True),
            (ValueError("bad pixel"), False),
        ],
    )
    def test_is_allocation_error(self, exc: BaseException, expected: bool) -> None:
        assert _is_allocation_error(exc) is expected

    def test_downscale_keeps_small_images(self) -> None:
        image = Image.new("RGBA", (100, 50), (255, 255, 255, 255))
        shrunk = _downscale_to_max_side(image, 200)
        assert shrunk.size == (100, 50)

    def test_downscale_preserves_aspect_ratio(self) -> None:
        image = Image.new("RGBA", (4000, 2000), (255, 255, 255, 255))
        shrunk = _downscale_to_max_side(image, 1000)
        assert max(shrunk.size) == 1000
        assert shrunk.size == (1000, 500)
