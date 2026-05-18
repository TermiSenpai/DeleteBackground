"""Tests for the REST endpoints exposed by :mod:`app.api.routes`."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import __version__
from app.config import UserPreferences
from tests.conftest import make_solid_png


def _set_prefs(client: TestClient, **overrides: Any) -> UserPreferences:
    payload = UserPreferences(**overrides).model_dump()
    resp = client.put("/api/preferences", json=payload)
    assert resp.status_code == 200, resp.text
    return UserPreferences.model_validate(resp.json()["preferences"])


class TestStaticEndpoints:
    def test_health(self, client: TestClient) -> None:
        resp = client.get("/api/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body == {"status": "ok", "version": __version__}

    def test_models_lists_supported(self, client: TestClient) -> None:
        resp = client.get("/api/models")
        body = resp.json()
        ids = [m["id"] for m in body["models"]]
        assert body["default"] in ids
        assert "u2netp" in ids

    def test_index_page_renders(self, client: TestClient) -> None:
        resp = client.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]


class TestPreferences:
    def test_defaults_returned_when_no_file(self, client: TestClient) -> None:
        resp = client.get("/api/preferences")
        body = resp.json()
        assert body["preferences"] == UserPreferences().model_dump()

    def test_update_round_trips(
        self, client: TestClient, tmp_path: Path
    ) -> None:
        prefs = _set_prefs(
            client,
            input_folder=str(tmp_path / "in"),
            output_folder=str(tmp_path / "out"),
            model_name="u2netp",
            recursive=True,
        )
        # Read it back.
        read_back = UserPreferences.model_validate(
            client.get("/api/preferences").json()["preferences"]
        )
        assert read_back == prefs

    def test_update_rejects_invalid_color(self, client: TestClient) -> None:
        payload = UserPreferences().model_dump()
        payload["background_color"] = "not-a-color"
        resp = client.put("/api/preferences", json=payload)
        assert resp.status_code == 422


class TestFolderProbe:
    def test_existing_folder_reports_image_count(
        self,
        client: TestClient,
        populated_input_folder: Path,
    ) -> None:
        resp = client.post(
            "/api/folder/probe",
            json={"path": str(populated_input_folder), "recursive": False},
        )
        body = resp.json()
        assert body["exists"] is True
        assert body["is_directory"] is True
        assert body["image_count"] == 3
        assert set(body["sample"]) <= {"a.png", "b.jpg", "c.webp"}

    def test_missing_folder_reports_error(
        self, client: TestClient, tmp_path: Path
    ) -> None:
        resp = client.post(
            "/api/folder/probe",
            json={"path": str(tmp_path / "ghost"), "recursive": False},
        )
        body = resp.json()
        assert body["exists"] is False
        assert body["error"]

    def test_file_path_is_rejected(
        self, client: TestClient, tmp_path: Path
    ) -> None:
        f = tmp_path / "a.txt"
        f.write_text("hi")
        resp = client.post(
            "/api/folder/probe",
            json={"path": str(f), "recursive": False},
        )
        body = resp.json()
        assert body["exists"] is True
        assert body["is_directory"] is False


class TestJobLifecycle:
    def test_start_without_folders_is_rejected(self, client: TestClient) -> None:
        resp = client.post("/api/job", json={"force": False})
        assert resp.status_code == 400

    def test_start_with_missing_input_returns_400(
        self, client: TestClient, tmp_path: Path
    ) -> None:
        _set_prefs(
            client,
            input_folder=str(tmp_path / "missing"),
            output_folder=str(tmp_path / "out"),
        )
        resp = client.post("/api/job", json={"force": False})
        assert resp.status_code == 400

    def test_full_run_writes_outputs(
        self,
        client: TestClient,
        populated_input_folder: Path,
        output_folder: Path,
    ) -> None:
        _set_prefs(
            client,
            input_folder=str(populated_input_folder),
            output_folder=str(output_folder),
            model_name="u2netp",
        )
        resp = client.post("/api/job", json={"force": False})
        assert resp.status_code == 202

        # Poll the job status until it finishes (with a generous timeout).
        deadline = time.time() + 5.0
        last_status = None
        while time.time() < deadline:
            last_status = client.get("/api/job").json()
            if last_status["state"] in ("completed", "failed", "cancelled"):
                break
            time.sleep(0.05)
        assert last_status is not None
        assert last_status["state"] == "completed", last_status
        assert last_status["processed"] == 3
        assert sorted(p.name for p in output_folder.glob("*.png")) == [
            "a.png",
            "b.png",
            "c.png",
        ]

    def test_double_start_returns_conflict(
        self,
        client: TestClient,
        populated_input_folder: Path,
        output_folder: Path,
    ) -> None:
        _set_prefs(
            client,
            input_folder=str(populated_input_folder),
            output_folder=str(output_folder),
        )
        first = client.post("/api/job", json={"force": False})
        assert first.status_code == 202
        try:
            second = client.post("/api/job", json={"force": False})
            # Either we hit the in-flight job (409) or it finished first (202).
            assert second.status_code in (202, 409)
        finally:
            self._drain(client)

    def test_cancel_without_running_job_returns_409(
        self, client: TestClient
    ) -> None:
        resp = client.delete("/api/job")
        assert resp.status_code == 409

    @staticmethod
    def _drain(client: TestClient) -> None:
        deadline = time.time() + 5.0
        while time.time() < deadline:
            state = client.get("/api/job").json()["state"]
            if state in ("idle", "completed", "failed", "cancelled"):
                return
            time.sleep(0.05)


class TestOutputServing:
    def test_list_empty_when_no_pref(self, client: TestClient) -> None:
        body = client.get("/api/output").json()
        assert body["files"] == []
        assert body["total"] == 0
        assert body["folder"] == ""

    def test_list_returns_files(
        self,
        client: TestClient,
        output_folder: Path,
        tmp_path: Path,
    ) -> None:
        _set_prefs(
            client,
            input_folder=str(tmp_path / "in"),
            output_folder=str(output_folder),
        )
        (output_folder / "first.png").write_bytes(make_solid_png())
        (output_folder / "second.png").write_bytes(make_solid_png())
        body = client.get("/api/output?limit=10").json()
        assert body["total"] == 2
        assert {f["name"] for f in body["files"]} == {"first.png", "second.png"}

    def test_fetch_output_rejects_path_escape(
        self,
        client: TestClient,
        output_folder: Path,
        tmp_path: Path,
    ) -> None:
        _set_prefs(
            client,
            input_folder=str(tmp_path / "in"),
            output_folder=str(output_folder),
        )
        (output_folder / "ok.png").write_bytes(make_solid_png())
        resp = client.get("/api/output/file", params={"path": "../escape.png"})
        assert resp.status_code == 400

    def test_fetch_missing_output_returns_404(
        self,
        client: TestClient,
        output_folder: Path,
        tmp_path: Path,
    ) -> None:
        _set_prefs(
            client,
            input_folder=str(tmp_path / "in"),
            output_folder=str(output_folder),
        )
        resp = client.get("/api/output/file", params={"path": "missing.png"})
        assert resp.status_code == 404

    def test_fetch_output_streams_file(
        self,
        client: TestClient,
        output_folder: Path,
        tmp_path: Path,
    ) -> None:
        _set_prefs(
            client,
            input_folder=str(tmp_path / "in"),
            output_folder=str(output_folder),
        )
        png = make_solid_png()
        (output_folder / "ok.png").write_bytes(png)
        resp = client.get("/api/output/file", params={"path": "ok.png"})
        assert resp.status_code == 200
        assert resp.content == png

    def test_fetch_input_rejects_when_unconfigured(
        self, client: TestClient
    ) -> None:
        resp = client.get("/api/input/file", params={"path": "x.png"})
        assert resp.status_code == 404


class TestFolderPicker:
    def test_cancelled_returns_empty_path(
        self,
        client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from app.api import routes as api_routes

        monkeypatch.setattr(
            api_routes, "_pick_folder_native", lambda *_a, **_kw: ""
        )
        resp = client.post(
            "/api/folder/pick",
            json={"initial_dir": "", "title": "Choose folder"},
        )
        body = resp.json()
        assert body == {"path": "", "cancelled": True}

    def test_picker_returns_selected_path(
        self,
        client: TestClient,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from app.api import routes as api_routes

        target = tmp_path / "picked"
        target.mkdir()
        monkeypatch.setattr(
            api_routes, "_pick_folder_native", lambda *_a, **_kw: str(target)
        )
        resp = client.post(
            "/api/folder/pick",
            json={"initial_dir": "", "title": "Choose folder"},
        )
        body = resp.json()
        assert body["cancelled"] is False
        assert Path(body["path"]) == target.resolve()

    def test_picker_os_error_returns_500(
        self,
        client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from app.api import routes as api_routes

        def broken(*_a: Any, **_kw: Any) -> str:
            raise OSError("dialog crashed")

        monkeypatch.setattr(api_routes, "_pick_folder_native", broken)
        resp = client.post(
            "/api/folder/pick",
            json={"initial_dir": "", "title": "Choose folder"},
        )
        assert resp.status_code == 500
        assert "dialog crashed" in resp.json()["detail"]
