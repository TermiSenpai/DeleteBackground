"""Pydantic request/response models exposed by the API."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.config import SUPPORTED_MODELS, UserPreferences


class HealthResponse(BaseModel):
    """Simple liveness probe."""

    status: Literal["ok"] = "ok"
    version: str


class ModelInfo(BaseModel):
    """Description of an available segmentation model."""

    id: str
    label: str
    description: str
    quality: Literal["fast", "balanced", "high", "premium"]


class ModelsResponse(BaseModel):
    """List of all selectable models."""

    models: list[ModelInfo]
    default: str


class PreferencesResponse(BaseModel):
    """Current persisted preferences."""

    preferences: UserPreferences


class FolderProbeRequest(BaseModel):
    """Ask the server to validate a folder path and count its images."""

    path: str = Field(min_length=1)
    recursive: bool = False


class FolderProbeResponse(BaseModel):
    """Result of probing an input folder."""

    path: str
    exists: bool
    is_directory: bool
    image_count: int
    sample: list[str] = Field(default_factory=list)
    error: str | None = None


class PickFolderRequest(BaseModel):
    """Open a native folder-picker dialog on the host."""

    initial_dir: str = ""
    title: str = "Choose folder"


class PickFolderResponse(BaseModel):
    """Result of opening the native folder picker.

    ``path`` is empty if the user dismissed the dialog.
    """

    path: str = ""
    cancelled: bool = False


class StartJobRequest(BaseModel):
    """Trigger a batch job using the persisted preferences."""

    force: bool = False  # If True, re-process even if outputs already exist.


class JobStatus(BaseModel):
    """Snapshot of the running (or last) job."""

    state: Literal["idle", "running", "cancelling", "completed", "failed", "cancelled"]
    total: int
    processed: int
    skipped: int
    failed: int
    current_file: str | None = None
    current_output_relative: str | None = None
    started_at: float | None = None
    finished_at: float | None = None
    duration_seconds: float | None = None
    average_seconds_per_image: float | None = None
    last_error: str | None = None


class ProgressEvent(BaseModel):
    """WebSocket message describing job progress."""

    type: Literal["status", "item", "log", "done"] = "status"
    status: JobStatus
    message: str | None = None


class OutputFile(BaseModel):
    """Description of a single produced output PNG."""

    name: str
    relative_path: str
    size_bytes: int
    modified_at: float


class OutputListResponse(BaseModel):
    """Newest-first listing of files in the configured output folder."""

    folder: str
    files: list[OutputFile] = Field(default_factory=list)
    total: int = 0


# Static catalog used to build the model picker in the UI.
MODEL_CATALOG: list[ModelInfo] = [
    ModelInfo(
        id="birefnet-general",
        label="BiRefNet General",
        description="State-of-the-art quality. Slowest. Best for hero shots.",
        quality="premium",
    ),
    ModelInfo(
        id="birefnet-general-lite",
        label="BiRefNet Lite",
        description="High quality with a lighter footprint. Good middle ground.",
        quality="high",
    ),
    ModelInfo(
        id="isnet-general-use",
        label="ISNet General",
        description="Strong general-purpose model. Recommended default.",
        quality="high",
    ),
    ModelInfo(
        id="u2net",
        label="U²-Net",
        description="Classic baseline. Solid quality, moderate speed.",
        quality="balanced",
    ),
    ModelInfo(
        id="u2netp",
        label="U²-Net Lite",
        description="Smallest and fastest. Lower edge precision.",
        quality="fast",
    ),
    ModelInfo(
        id="u2net_human_seg",
        label="U²-Net Human",
        description="Specialised for people / portraits.",
        quality="balanced",
    ),
    ModelInfo(
        id="silueta",
        label="Silueta",
        description="Compact alternative to U²-Net.",
        quality="fast",
    ),
]

# Sanity check that the catalog matches the supported list.
assert {m.id for m in MODEL_CATALOG} == set(SUPPORTED_MODELS), (
    "MODEL_CATALOG and SUPPORTED_MODELS are out of sync"
)
