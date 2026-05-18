"""Tests for the Pydantic API schemas in :mod:`app.models.schemas`."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import SUPPORTED_MODELS
from app.models.schemas import (
    MODEL_CATALOG,
    FolderProbeRequest,
    FolderProbeResponse,
    HealthResponse,
    JobStatus,
    ProgressEvent,
)


class TestModelCatalog:
    def test_ids_cover_supported_models(self) -> None:
        assert {m.id for m in MODEL_CATALOG} == set(SUPPORTED_MODELS)

    def test_quality_tier_is_valid(self) -> None:
        for m in MODEL_CATALOG:
            assert m.quality in {"fast", "balanced", "high", "premium"}


class TestHealthResponse:
    def test_status_is_locked_to_ok(self) -> None:
        with pytest.raises(ValidationError):
            HealthResponse(status="degraded", version="1.0.0")  # type: ignore[arg-type]


class TestFolderProbeRequest:
    def test_empty_path_rejected(self) -> None:
        with pytest.raises(ValidationError):
            FolderProbeRequest(path="")


class TestFolderProbeResponse:
    def test_sample_defaults_to_empty_list(self) -> None:
        response = FolderProbeResponse(
            path="/x", exists=True, is_directory=True, image_count=0
        )
        assert response.sample == []
        assert response.error is None


class TestJobStatus:
    def test_state_must_be_known(self) -> None:
        with pytest.raises(ValidationError):
            JobStatus(
                state="bogus",  # type: ignore[arg-type]
                total=0,
                processed=0,
                skipped=0,
                failed=0,
            )

    def test_model_copy_preserves_required_fields(self) -> None:
        status = JobStatus(
            state="idle", total=0, processed=0, skipped=0, failed=0
        )
        new = status.model_copy(update={"state": "running", "total": 5})
        assert new.state == "running"
        assert new.total == 5


class TestProgressEvent:
    def test_default_type_is_status(self) -> None:
        event = ProgressEvent(
            status=JobStatus(state="idle", total=0, processed=0, skipped=0, failed=0)
        )
        assert event.type == "status"
