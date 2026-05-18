"""Tests for the progress WebSocket exposed at ``/ws/progress``."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from app.config import UserPreferences


def _save_prefs(client: TestClient, **fields: Any) -> None:
    resp = client.put("/api/preferences", json=UserPreferences(**fields).model_dump())
    assert resp.status_code == 200


class TestProgressWebSocket:
    def test_initial_snapshot_is_sent_on_connect(
        self, client: TestClient
    ) -> None:
        with client.websocket_connect("/ws/progress") as ws:
            first = ws.receive_json()
            assert first["type"] == "status"
            assert first["status"]["state"] == "idle"

    def test_receives_done_event_for_a_run(
        self,
        client: TestClient,
        populated_input_folder: Path,
        output_folder: Path,
    ) -> None:
        _save_prefs(
            client,
            input_folder=str(populated_input_folder),
            output_folder=str(output_folder),
            model_name="u2netp",
        )
        with client.websocket_connect("/ws/progress") as ws:
            # Drain the initial snapshot.
            ws.receive_json()
            resp = client.post("/api/job", json={"force": False})
            assert resp.status_code == 202

            deadline = time.time() + 5.0
            saw_done = False
            states_seen: list[str] = []
            while time.time() < deadline:
                event = ws.receive_json()
                states_seen.append(event["type"])
                if event["type"] == "done":
                    saw_done = True
                    assert event["status"]["state"] == "completed"
                    assert event["status"]["processed"] == 3
                    break
            assert saw_done, f"never saw a done event; got {states_seen}"
