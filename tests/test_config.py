"""Tests for :mod:`app.config` — preferences validation and persistence."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import (
    SUPPORTED_MODELS,
    PreferencesStore,
    Settings,
    UserPreferences,
)


class TestUserPreferences:
    def test_defaults_round_trip(self) -> None:
        prefs = UserPreferences()
        clone = UserPreferences.model_validate_json(prefs.model_dump_json())
        assert clone == prefs

    def test_default_model_is_supported(self) -> None:
        assert UserPreferences().model_name in SUPPORTED_MODELS

    @pytest.mark.parametrize("color", ["", "#ff00ff", "#FF00FF", "#00112233"])
    def test_background_color_accepts_valid_values(self, color: str) -> None:
        prefs = UserPreferences(background_color=color)
        assert prefs.background_color == color.lower()

    @pytest.mark.parametrize(
        "color",
        [
            "red",          # no hash
            "#abc",         # too short
            "#abcdefg",     # bad length
            "#zzzzzz",      # non-hex
            "#abcdefab12",  # too long
        ],
    )
    def test_background_color_rejects_invalid_values(self, color: str) -> None:
        with pytest.raises(ValidationError):
            UserPreferences(background_color=color)

    @pytest.mark.parametrize("level", [-1, 10, 99])
    def test_png_compression_out_of_range(self, level: int) -> None:
        with pytest.raises(ValidationError):
            UserPreferences(png_compression=level)

    @pytest.mark.parametrize("threshold", [-1, 256])
    def test_alpha_matting_thresholds_clamped_to_byte_range(
        self, threshold: int
    ) -> None:
        with pytest.raises(ValidationError):
            UserPreferences(alpha_matting_foreground_threshold=threshold)
        with pytest.raises(ValidationError):
            UserPreferences(alpha_matting_background_threshold=threshold)


class TestSettings:
    def test_defaults(self) -> None:
        s = Settings()
        assert s.host == "127.0.0.1"
        assert s.port == 8765
        assert 1 <= s.max_workers <= 16

    def test_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DBG_HOST", "0.0.0.0")
        monkeypatch.setenv("DBG_PORT", "9000")
        monkeypatch.setenv("DBG_MAX_WORKERS", "2")
        s = Settings()
        assert s.host == "0.0.0.0"
        assert s.port == 9000
        assert s.max_workers == 2

    def test_max_workers_bounded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DBG_MAX_WORKERS", "99")
        with pytest.raises(ValidationError):
            Settings()


class TestPreferencesStore:
    def test_returns_defaults_when_file_missing(self, tmp_path: Path) -> None:
        store = PreferencesStore(tmp_path / "nope.json")
        assert store.load() == UserPreferences()

    def test_save_then_load_round_trip(self, tmp_path: Path) -> None:
        path = tmp_path / "prefs.json"
        store = PreferencesStore(path)
        prefs = UserPreferences(
            input_folder=str(tmp_path / "in"),
            output_folder=str(tmp_path / "out"),
            model_name="u2netp",
            recursive=True,
        )
        store.save(prefs)
        # Fresh store reads what was written.
        assert PreferencesStore(path).load() == prefs

    def test_save_is_atomic_on_disk(self, tmp_path: Path) -> None:
        path = tmp_path / "prefs.json"
        store = PreferencesStore(path)
        store.save(UserPreferences(model_name="u2netp"))
        # No leftover temp file.
        assert path.with_suffix(".tmp").exists() is False
        # Content is valid JSON.
        json.loads(path.read_text(encoding="utf-8"))

    def test_corrupt_file_falls_back_to_defaults(self, tmp_path: Path) -> None:
        path = tmp_path / "prefs.json"
        path.write_text("{not valid json", encoding="utf-8")
        store = PreferencesStore(path)
        assert store.load() == UserPreferences()

    def test_load_caches_result(self, tmp_path: Path) -> None:
        path = tmp_path / "prefs.json"
        path.write_text(UserPreferences(model_name="u2netp").model_dump_json())
        store = PreferencesStore(path)
        first = store.load()
        # Mutate the file out from under the store; cached value wins.
        path.write_text(UserPreferences(model_name="silueta").model_dump_json())
        assert store.load() is first
