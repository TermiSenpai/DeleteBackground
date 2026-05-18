"""Tests for :mod:`app.core.file_manager`."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.core.exceptions import FolderNotFoundError
from app.core.file_manager import (
    SUPPORTED_EXTENSIONS,
    atomic_write_bytes,
    ensure_directory,
    ensure_output_directory,
    is_already_processed,
    iter_images,
    output_path_for,
)


class TestEnsureDirectory:
    def test_returns_resolved_path_when_dir_exists(self, tmp_path: Path) -> None:
        result = ensure_directory(tmp_path)
        assert result == tmp_path.resolve()

    def test_raises_when_missing(self, tmp_path: Path) -> None:
        with pytest.raises(FolderNotFoundError):
            ensure_directory(tmp_path / "missing")

    def test_raises_when_path_is_file(self, tmp_path: Path) -> None:
        file = tmp_path / "f.txt"
        file.write_text("hi")
        with pytest.raises(FolderNotFoundError):
            ensure_directory(file)


class TestEnsureOutputDirectory:
    def test_creates_directory_when_missing(self, tmp_path: Path) -> None:
        target = tmp_path / "nested" / "out"
        result = ensure_output_directory(target)
        assert result.exists()
        assert result.is_dir()

    def test_existing_directory_is_returned(self, tmp_path: Path) -> None:
        assert ensure_output_directory(tmp_path) == tmp_path.resolve()


class TestIterImages:
    def test_supported_extensions_are_picked_up(
        self, populated_input_folder: Path
    ) -> None:
        names = [p.name for p in iter_images(populated_input_folder, recursive=False)]
        assert names == ["a.png", "b.jpg", "c.webp"]

    def test_extensions_constant_matches_expectations(self) -> None:
        # If you add a new format, update the schema/help too.
        assert ".png" in SUPPORTED_EXTENSIONS
        assert ".txt" not in SUPPORTED_EXTENSIONS

    def test_non_recursive_skips_subdirs(self, populated_input_folder: Path) -> None:
        sub = populated_input_folder / "deep"
        sub.mkdir()
        (sub / "ignored.png").write_bytes(b"")
        names = [p.name for p in iter_images(populated_input_folder, recursive=False)]
        assert "ignored.png" not in names

    def test_recursive_descends_into_subdirs(
        self, populated_input_folder: Path
    ) -> None:
        sub = populated_input_folder / "deep"
        sub.mkdir()
        (sub / "z.png").write_bytes(b"")
        names = [p.name for p in iter_images(populated_input_folder, recursive=True)]
        assert "z.png" in names

    def test_case_insensitive_extensions(self, input_folder: Path) -> None:
        (input_folder / "shout.PNG").write_bytes(b"")
        (input_folder / "SHOUT.JpEg").write_bytes(b"")
        names = sorted(p.name for p in iter_images(input_folder, recursive=False))
        assert names == ["SHOUT.JpEg", "shout.PNG"]


class TestOutputPathFor:
    def test_extension_is_normalised_to_png(self, tmp_path: Path) -> None:
        input_root = tmp_path / "in"
        output_root = tmp_path / "out"
        result = output_path_for(
            input_file=input_root / "photo.jpg",
            input_root=input_root,
            output_root=output_root,
        )
        assert result == output_root / "photo.png"

    def test_subdirectory_layout_is_preserved(self, tmp_path: Path) -> None:
        input_root = tmp_path / "in"
        output_root = tmp_path / "out"
        result = output_path_for(
            input_file=input_root / "people" / "alice.jpg",
            input_root=input_root,
            output_root=output_root,
        )
        assert result == output_root / "people" / "alice.png"

    def test_file_outside_root_falls_back_to_name(self, tmp_path: Path) -> None:
        input_root = tmp_path / "in"
        output_root = tmp_path / "out"
        outside = tmp_path / "elsewhere" / "stray.bmp"
        result = output_path_for(
            input_file=outside, input_root=input_root, output_root=output_root
        )
        assert result == output_root / "stray.png"


class TestIsAlreadyProcessed:
    def test_false_when_output_missing(self, tmp_path: Path) -> None:
        inp = tmp_path / "i.png"
        inp.write_bytes(b"x")
        assert is_already_processed(inp, tmp_path / "missing.png") is False

    def test_true_when_output_is_newer(self, tmp_path: Path) -> None:
        inp = tmp_path / "i.png"
        out = tmp_path / "o.png"
        inp.write_bytes(b"x")
        out.write_bytes(b"y")
        # Force output mtime to be clearly newer.
        os.utime(out, (inp.stat().st_atime, inp.stat().st_mtime + 5))
        assert is_already_processed(inp, out) is True

    def test_false_when_input_is_newer(self, tmp_path: Path) -> None:
        inp = tmp_path / "i.png"
        out = tmp_path / "o.png"
        out.write_bytes(b"old")
        inp.write_bytes(b"new")
        os.utime(inp, (out.stat().st_atime, out.stat().st_mtime + 5))
        assert is_already_processed(inp, out) is False


class TestAtomicWriteBytes:
    def test_writes_full_content(self, tmp_path: Path) -> None:
        target = tmp_path / "deep" / "out.png"
        atomic_write_bytes(target, b"hello")
        assert target.read_bytes() == b"hello"

    def test_no_temp_file_remains_on_success(self, tmp_path: Path) -> None:
        target = tmp_path / "out.png"
        atomic_write_bytes(target, b"hello")
        assert not target.with_suffix(target.suffix + ".tmp").exists()

    def test_overwrites_existing_file(self, tmp_path: Path) -> None:
        target = tmp_path / "out.png"
        target.write_bytes(b"old")
        atomic_write_bytes(target, b"new")
        assert target.read_bytes() == b"new"
