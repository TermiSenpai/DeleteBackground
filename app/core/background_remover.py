"""Thin wrapper around ``rembg`` that caches one session per model.

The session encapsulates a loaded ONNX model. Building it is expensive
(weights download on first use, then a few hundred ms to instantiate), so
we keep one per model name in a process-wide cache guarded by a lock.

Inference itself releases the GIL inside ONNX Runtime, so multiple worker
threads can call :meth:`BackgroundRemover.process_bytes` concurrently.
"""

from __future__ import annotations

import io
import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from PIL import Image

from app.config import SUPPORTED_MODELS
from app.core.exceptions import ModelLoadError

logger = logging.getLogger(__name__)

# Substrings observed in ONNX Runtime error messages when the model fails to
# allocate a tensor. Used to recognise memory pressure and trigger the
# downscale retry below.
_OOM_MARKERS: Final[tuple[str, ...]] = (
    "bad allocation",
    "bad_alloc",
    "out of memory",
    "failed to allocate",
    "cudaerrormemoryallocation",
)

# Fallback max side (in pixels) used when retrying an image that exhausted
# memory at native resolution. Picked to keep BiRefNet's peak working set
# under ~3 GB while still preserving good edge quality on portraits.
_OOM_RETRY_MAX_SIDE: Final[int] = 2048

# Imported lazily inside ``_load_session`` so that importing this module does
# not pay the rembg import cost (which itself pulls in numpy + onnxruntime).
_rembg_remove: Any = None
_rembg_new_session: Any = None


def _import_rembg() -> None:
    """Import rembg on first use and bind module-level callables."""
    global _rembg_remove, _rembg_new_session
    if _rembg_remove is not None:
        return
    try:
        from rembg import new_session, remove
    except ImportError as exc:  # pragma: no cover - install-time error
        raise ModelLoadError(
            "rembg is not installed. Run `pip install -r requirements.txt`."
        ) from exc
    _rembg_remove = remove
    _rembg_new_session = new_session


@dataclass(frozen=True)
class RemovalOptions:
    """Per-call options forwarded to ``rembg.remove``."""

    alpha_matting: bool = False
    alpha_matting_foreground_threshold: int = 240
    alpha_matting_background_threshold: int = 10
    alpha_matting_erode_size: int = 10
    background_color: tuple[int, int, int, int] | None = None
    png_compression: int = 1


class BackgroundRemover:
    """Process-wide manager that owns one ONNX session per model name."""

    def __init__(self) -> None:
        self._sessions: dict[str, Any] = {}
        self._lock = threading.RLock()

    def warmup(self, model_name: str) -> None:
        """Eagerly build the session for ``model_name``.

        Useful at startup so the first user request does not pay the cost.
        """
        self._get_session(model_name)

    def _get_session(self, model_name: str) -> Any:
        if model_name not in SUPPORTED_MODELS:
            raise ModelLoadError(f"Unsupported model: {model_name}")
        with self._lock:
            session = self._sessions.get(model_name)
            if session is not None:
                return session
            _import_rembg()
            logger.info("Loading segmentation model %r…", model_name)
            try:
                session = _rembg_new_session(model_name)
            except Exception as exc:
                raise ModelLoadError(
                    f"Failed to load model {model_name!r}: {exc}"
                ) from exc
            self._sessions[model_name] = session
            logger.info("Model %r ready.", model_name)
            return session

    def process_file(
        self,
        *,
        input_path: Path,
        model_name: str,
        options: RemovalOptions,
    ) -> bytes:
        """Run background removal on ``input_path`` and return PNG bytes.

        The input is read from disk in this call; the output is *not* written
        — callers persist it themselves (see :func:`atomic_write_bytes`). This
        keeps I/O policy out of the inference layer.

        Args:
            input_path: Source image on disk.
            model_name: rembg model identifier.
            options: Inference and encoding options.

        Returns:
            Encoded PNG bytes with an alpha channel.

        Raises:
            ModelLoadError: If the session cannot be built.
            OSError: If the file cannot be read.
            ValueError: If the file is not a decodable image.
        """
        raw = input_path.read_bytes()
        return self.process_bytes(
            data=raw,
            model_name=model_name,
            options=options,
        )

    def process_bytes(
        self,
        *,
        data: bytes,
        model_name: str,
        options: RemovalOptions,
    ) -> bytes:
        """Same as :meth:`process_file` but takes raw input bytes."""
        session = self._get_session(model_name)
        _import_rembg()

        try:
            return self._infer_and_encode(
                source=data, session=session, options=options
            )
        except Exception as exc:
            if not _is_allocation_error(exc):
                raise
            logger.warning(
                "Allocation failure on %s; retrying at max side %d px.",
                model_name,
                _OOM_RETRY_MAX_SIDE,
            )

        # Retry: load the source, shrink to a bounded size, hand a PIL image
        # back to rembg. rembg accepts ``PIL.Image`` directly, which avoids a
        # second decode.
        with Image.open(io.BytesIO(data)) as raw_image:
            raw_image.load()
            shrunk = _downscale_to_max_side(raw_image, _OOM_RETRY_MAX_SIDE)
            return self._infer_and_encode(
                source=shrunk, session=session, options=options
            )

    @staticmethod
    def _infer_and_encode(
        *,
        source: bytes | Image.Image,
        session: Any,
        options: RemovalOptions,
    ) -> bytes:
        """Run rembg and re-encode the PNG with the configured compression."""
        # rembg returns PNG bytes when given bytes; we re-encode to control
        # the compression level (rembg defaults to 6, which is slow for big
        # batches).
        result = _rembg_remove(
            source,
            session=session,
            alpha_matting=options.alpha_matting,
            alpha_matting_foreground_threshold=options.alpha_matting_foreground_threshold,
            alpha_matting_background_threshold=options.alpha_matting_background_threshold,
            alpha_matting_erode_size=options.alpha_matting_erode_size,
            bgcolor=options.background_color,
        )

        # rembg returns ``bytes`` for byte input and a ``PIL.Image`` for image
        # input. Normalise both into a PIL image so the re-encode is uniform.
        if isinstance(result, (bytes, bytearray)):
            image_ctx = Image.open(io.BytesIO(result))
        else:
            image_ctx = result

        with image_ctx as image:
            image.load()
            mode = "RGBA" if options.background_color is None else "RGB"
            if image.mode != mode:
                image = image.convert(mode)
            buffer = io.BytesIO()
            image.save(
                buffer,
                format="PNG",
                optimize=False,
                compress_level=options.png_compression,
            )
            return buffer.getvalue()


def _is_allocation_error(exc: BaseException) -> bool:
    """Return True when ``exc`` looks like an ONNX Runtime allocation failure."""
    message = str(exc).lower()
    if any(marker in message for marker in _OOM_MARKERS):
        return True
    if isinstance(exc, MemoryError):
        return True
    return False


def _downscale_to_max_side(image: Image.Image, max_side: int) -> Image.Image:
    """Return a copy of ``image`` whose longest side is at most ``max_side``.

    Aspect ratio is preserved. Images already within the bound are copied
    unchanged so the caller can always close the original.
    """
    longest = max(image.width, image.height)
    if longest <= max_side:
        return image.copy()
    scale = max_side / longest
    new_size = (max(1, int(image.width * scale)), max(1, int(image.height * scale)))
    return image.resize(new_size, Image.LANCZOS)
