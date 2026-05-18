"""Filesystem helpers for input discovery and atomic output writes."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from pathlib import Path

from app.core.exceptions import FolderNotFoundError

logger = logging.getLogger(__name__)

# Image extensions supported by Pillow that make sense as input. JPEG, WebP,
# BMP and TIFF do not carry transparency natively, but they are valid inputs;
# the output is always PNG with alpha.
SUPPORTED_EXTENSIONS: frozenset[str] = frozenset(
    {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}
)


def ensure_directory(path: Path) -> Path:
    """Resolve ``path`` and ensure it exists as a directory.

    Args:
        path: The directory path to validate.

    Returns:
        The resolved absolute path.

    Raises:
        FolderNotFoundError: If the path does not exist or is not a directory.
    """
    resolved = path.expanduser().resolve()
    if not resolved.exists():
        raise FolderNotFoundError(f"Folder does not exist: {resolved}")
    if not resolved.is_dir():
        raise FolderNotFoundError(f"Path is not a directory: {resolved}")
    return resolved


def ensure_output_directory(path: Path) -> Path:
    """Resolve ``path`` and create it if missing.

    Args:
        path: Desired output directory.

    Returns:
        The resolved absolute path, guaranteed to exist.
    """
    resolved = path.expanduser().resolve()
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def iter_images(folder: Path, recursive: bool) -> Iterator[Path]:
    """Yield image files in ``folder`` in stable lexicographic order.

    Args:
        folder: Resolved directory to scan.
        recursive: If True, descend into subdirectories.

    Yields:
        Absolute paths to image files with supported extensions.
    """
    pattern = "**/*" if recursive else "*"
    for entry in sorted(folder.glob(pattern)):
        if not entry.is_file():
            continue
        if entry.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        yield entry


def output_path_for(
    *, input_file: Path, input_root: Path, output_root: Path
) -> Path:
    """Compute the destination path for ``input_file`` mirroring its layout.

    Output is always a ``.png`` (transparent format). Subdirectory structure
    relative to ``input_root`` is preserved under ``output_root``.

    Args:
        input_file: Resolved path of the source image.
        input_root: Resolved root of the input scan.
        output_root: Resolved root where outputs will be written.

    Returns:
        The resolved output path. Parent directories are not yet created.
    """
    try:
        relative = input_file.relative_to(input_root)
    except ValueError:
        # File lies outside the root — fall back to its bare name.
        relative = Path(input_file.name)
    return (output_root / relative).with_suffix(".png")


def is_already_processed(input_file: Path, output_file: Path) -> bool:
    """Return True if ``output_file`` exists and is at least as new as input."""
    if not output_file.exists():
        return False
    try:
        return output_file.stat().st_mtime >= input_file.stat().st_mtime
    except OSError:
        return False


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Write ``data`` to ``path`` via a temporary file + rename.

    Guarantees readers never see a half-written file.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_bytes(data)
        tmp.replace(path)
    except OSError:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError as cleanup_exc:
                logger.warning("Failed to clean up temp file %s: %s", tmp, cleanup_exc)
        raise
