"""End-to-end smoke test exercising the full app over the HTTP boundary.

The real ``BackgroundRemover`` is swapped for the lightweight recording
double, so this runs in well under a second without downloading any model
weights. Everything else — preferences persistence, batch orchestration,
filesystem layout, output listing, output streaming — is the production code.
"""

from __future__ import annotations

import time
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import UserPreferences


def _wait_until_done(client: TestClient, timeout: float = 5.0) -> dict[str, object]:
    deadline = time.time() + timeout
    last: dict[str, object] = {}
    while time.time() < deadline:
        last = client.get("/api/job").json()
        if last["state"] in ("completed", "failed", "cancelled"):
            return last
        time.sleep(0.05)
    raise AssertionError(f"Job never finished. Last status: {last}")


class TestEndToEnd:
    def test_run_pipeline_writes_pngs_visible_via_api(
        self,
        client: TestClient,
        populated_input_folder: Path,
        output_folder: Path,
        isolated_settings_file: Path,
    ) -> None:
        # 1. Configure folders via the preferences endpoint.
        prefs = UserPreferences(
            input_folder=str(populated_input_folder),
            output_folder=str(output_folder),
            model_name="u2netp",
        )
        assert (
            client.put("/api/preferences", json=prefs.model_dump()).status_code == 200
        )
        # Round-trip survives even a fresh load — settings.json was written.
        from app.config import PreferencesStore

        on_disk = PreferencesStore(isolated_settings_file).load()
        assert on_disk.input_folder == str(populated_input_folder)

        # 2. Probe the input folder.
        probe = client.post(
            "/api/folder/probe",
            json={"path": str(populated_input_folder), "recursive": False},
        ).json()
        assert probe["image_count"] == 3

        # 3. Kick off the job.
        accepted = client.post("/api/job", json={"force": False})
        assert accepted.status_code == 202

        final = _wait_until_done(client)
        assert final["state"] == "completed"
        assert final["processed"] == 3
        assert final["failed"] == 0

        # 4. The output folder now lists the generated PNGs.
        listing = client.get("/api/output?limit=20").json()
        names = {entry["name"] for entry in listing["files"]}
        assert names == {"a.png", "b.png", "c.png"}

        # 5. Each file is streamable as a real PNG.
        for name in names:
            resp = client.get("/api/output/file", params={"path": name})
            assert resp.status_code == 200
            assert resp.content[:8] == b"\x89PNG\r\n\x1a\n"

    def test_rerun_is_idempotent(
        self,
        client: TestClient,
        populated_input_folder: Path,
        output_folder: Path,
    ) -> None:
        prefs = UserPreferences(
            input_folder=str(populated_input_folder),
            output_folder=str(output_folder),
            model_name="u2netp",
        )
        client.put("/api/preferences", json=prefs.model_dump())

        client.post("/api/job", json={"force": False})
        _wait_until_done(client)
        first_run_mtimes = {
            p.name: p.stat().st_mtime for p in output_folder.glob("*.png")
        }
        assert len(first_run_mtimes) == 3

        # Second run: skip_existing=True (default), no force — outputs untouched.
        client.post("/api/job", json={"force": False})
        final = _wait_until_done(client)
        assert final["processed"] == 0
        assert final["skipped"] == 3
        for png in output_folder.glob("*.png"):
            assert png.stat().st_mtime == first_run_mtimes[png.name]
