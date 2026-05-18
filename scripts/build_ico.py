"""Generate a multi-resolution Windows ``.ico`` from the project SVG icon.

The resulting ``static/img/favicon.ico`` is bundled as the executable icon by
PyInstaller. Run this script whenever ``static/img/favicon.svg`` changes::

    python scripts/build_ico.py

Requires ``resvg-py`` and ``pillow`` in the active environment.
"""

from __future__ import annotations

import io
import logging
import sys
from pathlib import Path

import resvg_py
from PIL import Image

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
SVG_PATH = ROOT / "static" / "img" / "favicon.svg"
ICO_PATH = ROOT / "static" / "img" / "favicon.ico"
ICO_SIZES: tuple[int, ...] = (16, 32, 48, 64, 128, 256)


def render_svg(svg_path: Path, size: int) -> Image.Image:
    """Rasterize *svg_path* to a square RGBA image of *size* pixels.

    Args:
        svg_path: Source SVG file path.
        size: Output width and height in pixels.

    Returns:
        A Pillow ``Image`` in ``RGBA`` mode at ``size``x``size``.
    """
    data = resvg_py.svg_to_bytes(svg_path=str(svg_path), width=size, height=size)
    return Image.open(io.BytesIO(bytes(data))).convert("RGBA")


def build_ico(svg_path: Path, ico_path: Path, sizes: tuple[int, ...]) -> None:
    """Render *svg_path* at each requested size and write a multi-res ``.ico``.

    Args:
        svg_path: Source SVG file path.
        ico_path: Destination ``.ico`` file path.
        sizes: Square pixel sizes to embed (16, 32, 48, 64, 128, 256 are the
            classic Windows shell sizes).
    """
    frames = [render_svg(svg_path, s) for s in sizes]
    ico_path.parent.mkdir(parents=True, exist_ok=True)
    frames[-1].save(
        ico_path,
        format="ICO",
        sizes=[(s, s) for s in sizes],
        append_images=frames[:-1],
    )


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if not SVG_PATH.is_file():
        logger.error("SVG not found: %s", SVG_PATH)
        return 1
    build_ico(SVG_PATH, ICO_PATH, ICO_SIZES)
    logger.info("Wrote %s with sizes %s", ICO_PATH, ICO_SIZES)
    return 0


if __name__ == "__main__":
    sys.exit(main())
