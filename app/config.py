"""Application configuration and persisted user settings.

Two layers:
  * ``Settings`` — process-level, immutable, loaded from environment variables.
  * ``UserPreferences`` — runtime-mutable preferences persisted to a JSON
    file. The UI edits these.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from threading import RLock
from typing import Literal

from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent
SETTINGS_FILE: Path = PROJECT_ROOT / "settings.json"

# Supported rembg model identifiers exposed to the UI. Each is a tradeoff
# between speed and quality. ``birefnet-general`` is the current state of
# the art; ``u2netp`` is the smallest/fastest.
SUPPORTED_MODELS: tuple[str, ...] = (
    "birefnet-general",
    "birefnet-general-lite",
    "isnet-general-use",
    "u2net",
    "u2netp",
    "u2net_human_seg",
    "silueta",
)

ModelName = Literal[
    "birefnet-general",
    "birefnet-general-lite",
    "isnet-general-use",
    "u2net",
    "u2netp",
    "u2net_human_seg",
    "silueta",
]


class Settings(BaseSettings):
    """Process-level configuration sourced from environment variables.

    All variables are prefixed with ``DBG_`` (DeleteBackGround).
    """

    model_config = SettingsConfigDict(
        env_prefix="DBG_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    host: str = "127.0.0.1"
    port: int = 8765
    log_level: str = "INFO"
    # Hard cap on concurrent worker threads for inference. The default keeps
    # latency low without thrashing the ONNX session's internal threads.
    max_workers: int = Field(default=min(os.cpu_count() or 2, 4), ge=1, le=16)


class UserPreferences(BaseModel):
    """User-editable preferences persisted to ``settings.json``."""

    input_folder: str = ""
    output_folder: str = ""
    model_name: ModelName = "isnet-general-use"
    # Skip files whose output already exists and is newer than the input.
    skip_existing: bool = True
    # Recurse into subdirectories when scanning the input folder.
    recursive: bool = False
    # PNG compression level (0 = none, 9 = max). Lower is faster, larger.
    png_compression: int = Field(default=1, ge=0, le=9)
    # Apply rembg alpha matting for cleaner edges. Slower but higher quality.
    alpha_matting: bool = False
    alpha_matting_foreground_threshold: int = Field(default=240, ge=0, le=255)
    alpha_matting_background_threshold: int = Field(default=10, ge=0, le=255)
    alpha_matting_erode_size: int = Field(default=10, ge=0, le=40)
    # If set, post-process the cutout against this solid background color.
    # Empty string means "keep transparent".
    background_color: str = ""

    @field_validator("background_color")
    @classmethod
    def _validate_color(cls, value: str) -> str:
        """Accept empty or ``#RRGGBB`` / ``#RRGGBBAA``."""
        if value == "":
            return value
        if not value.startswith("#") or len(value) not in (7, 9):
            raise ValueError("background_color must be empty or #RRGGBB / #RRGGBBAA")
        int(value[1:], 16)  # raises if not hex
        return value.lower()


class PreferencesStore:
    """Thread-safe load/save wrapper for ``UserPreferences``."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = RLock()
        self._cache: UserPreferences | None = None

    def load(self) -> UserPreferences:
        """Return the current preferences, loading from disk on first access."""
        with self._lock:
            if self._cache is not None:
                return self._cache
            if self._path.exists():
                try:
                    raw = json.loads(self._path.read_text(encoding="utf-8"))
                    self._cache = UserPreferences.model_validate(raw)
                except (json.JSONDecodeError, ValueError) as exc:
                    logger.warning(
                        "Corrupt settings file %s (%s); using defaults.",
                        self._path,
                        exc,
                    )
                    self._cache = UserPreferences()
            else:
                self._cache = UserPreferences()
            return self._cache

    def save(self, prefs: UserPreferences) -> UserPreferences:
        """Persist ``prefs`` atomically and update the in-memory cache."""
        with self._lock:
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(
                prefs.model_dump_json(indent=2),
                encoding="utf-8",
            )
            tmp.replace(self._path)
            self._cache = prefs
            return prefs


settings = Settings()
preferences_store = PreferencesStore(SETTINGS_FILE)
