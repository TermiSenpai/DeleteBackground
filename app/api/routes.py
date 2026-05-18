"""REST endpoints for the DeleteBackground app.

This module wires Pydantic-validated HTTP I/O to the core layer. It owns no
business logic itself; orchestration lives in :mod:`app.core.batch_processor`.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import FileResponse

from app import __version__
from app.config import (
    PreferencesStore,
    UserPreferences,
    preferences_store,
)
from app.core.batch_processor import BatchProcessor
from app.core.exceptions import (
    DeleteBackgroundError,
    FolderNotFoundError,
    JobAlreadyRunningError,
    JobNotRunningError,
    UnsafePathError,
)
from app.core.file_manager import iter_images
from app.core.folder_picker import pick_folder as _pick_folder_native
from app.models.schemas import (
    FolderProbeRequest,
    FolderProbeResponse,
    HealthResponse,
    JobStatus,
    MODEL_CATALOG,
    ModelsResponse,
    OutputFile,
    OutputListResponse,
    PickFolderRequest,
    PickFolderResponse,
    PreferencesResponse,
    StartJobRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["delete-background"])


def get_processor(request: Request) -> BatchProcessor:
    """FastAPI dependency: return the shared :class:`BatchProcessor`."""
    processor: BatchProcessor = request.app.state.processor
    return processor


def get_preferences_store() -> PreferencesStore:
    """FastAPI dependency: return the singleton preferences store."""
    return preferences_store


ProcessorDep = Annotated[BatchProcessor, Depends(get_processor)]
PrefsStoreDep = Annotated[PreferencesStore, Depends(get_preferences_store)]


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Liveness probe."""
    return HealthResponse(status="ok", version=__version__)


@router.get("/models", response_model=ModelsResponse)
async def list_models() -> ModelsResponse:
    """Return the catalog of segmentation models the UI can offer."""
    return ModelsResponse(models=MODEL_CATALOG, default="isnet-general-use")


@router.get("/preferences", response_model=PreferencesResponse)
async def get_preferences(store: PrefsStoreDep) -> PreferencesResponse:
    """Return the currently persisted user preferences."""
    return PreferencesResponse(preferences=store.load())


@router.put("/preferences", response_model=PreferencesResponse)
async def update_preferences(
    prefs: UserPreferences, store: PrefsStoreDep
) -> PreferencesResponse:
    """Replace and persist the user preferences."""
    saved = store.save(prefs)
    return PreferencesResponse(preferences=saved)


@router.post("/folder/pick", response_model=PickFolderResponse)
async def pick_folder(payload: PickFolderRequest) -> PickFolderResponse:
    """Open the host's native folder-picker dialog and return the choice.

    The dialog renders on the machine running the server. This endpoint is
    intended for the local-use case (``host=127.0.0.1``) the rest of the app
    is built around. Returns an empty ``path`` with ``cancelled=true`` when
    the user dismisses the dialog.
    """
    try:
        selected = await asyncio.to_thread(
            _pick_folder_native, payload.initial_dir, payload.title
        )
    except OSError as exc:
        detail = str(exc) or f"{type(exc).__name__} (no message)"
        logger.exception("Native folder picker failed: %s", detail)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=detail,
        ) from exc

    if not selected:
        return PickFolderResponse(path="", cancelled=True)

    try:
        resolved = Path(selected).expanduser().resolve()
    except OSError:
        resolved = Path(selected)
    return PickFolderResponse(path=str(resolved), cancelled=False)


def _probe_folder_sync(raw_path_str: str, recursive: bool) -> FolderProbeResponse:
    """Filesystem-bound implementation of :func:`probe_folder`.

    Runs in a worker thread so a slow drive or a huge directory cannot stall
    the asyncio event loop while a user clicks Check.
    """
    raw_path = Path(raw_path_str).expanduser()
    try:
        resolved = raw_path.resolve()
    except OSError as exc:
        return FolderProbeResponse(
            path=str(raw_path),
            exists=False,
            is_directory=False,
            image_count=0,
            error=str(exc),
        )

    if not resolved.exists():
        return FolderProbeResponse(
            path=str(resolved),
            exists=False,
            is_directory=False,
            image_count=0,
            error="Folder does not exist.",
        )
    if not resolved.is_dir():
        return FolderProbeResponse(
            path=str(resolved),
            exists=True,
            is_directory=False,
            image_count=0,
            error="Path is not a directory.",
        )

    sample: list[str] = []
    count = 0
    for img in iter_images(resolved, recursive):
        count += 1
        if len(sample) < 5:
            sample.append(img.name)

    return FolderProbeResponse(
        path=str(resolved),
        exists=True,
        is_directory=True,
        image_count=count,
        sample=sample,
    )


@router.post("/folder/probe", response_model=FolderProbeResponse)
async def probe_folder(payload: FolderProbeRequest) -> FolderProbeResponse:
    """Validate a folder path and report how many images live in it."""
    return await asyncio.to_thread(
        _probe_folder_sync, payload.path, payload.recursive
    )


@router.get("/job", response_model=JobStatus)
async def job_status(processor: ProcessorDep) -> JobStatus:
    """Return the current job status snapshot."""
    return processor.status


@router.post("/job", response_model=JobStatus, status_code=status.HTTP_202_ACCEPTED)
async def start_job(
    payload: StartJobRequest,
    processor: ProcessorDep,
    store: PrefsStoreDep,
) -> JobStatus:
    """Start a batch job using the persisted preferences."""
    prefs = store.load()
    if not prefs.input_folder or not prefs.output_folder:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Input and output folders must be configured first.",
        )
    try:
        return await processor.start(prefs=prefs, force=payload.force)
    except JobAlreadyRunningError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    except FolderNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    except DeleteBackgroundError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
        ) from exc


@router.delete("/job", response_model=JobStatus)
async def cancel_job(processor: ProcessorDep) -> JobStatus:
    """Request cancellation of the running job."""
    try:
        processor.request_cancel()
    except JobNotRunningError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    return processor.status


def _resolve_within(root: Path, relative: str) -> Path:
    """Resolve ``relative`` against ``root`` and reject paths that escape it.

    Raises:
        UnsafePathError: If the resolved path is not inside ``root``.
    """
    if not relative:
        raise UnsafePathError("Empty path.")
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise UnsafePathError(f"Path escapes root: {relative}") from exc
    return candidate


@router.get("/output", response_model=OutputListResponse)
async def list_output(
    store: PrefsStoreDep,
    limit: int = Query(default=24, ge=1, le=200),
) -> OutputListResponse:
    """Return the newest-first listing of PNGs in the configured output folder."""
    prefs = store.load()
    if not prefs.output_folder:
        return OutputListResponse(folder="", files=[], total=0)

    root = Path(prefs.output_folder).expanduser()
    try:
        root = root.resolve()
    except OSError:
        return OutputListResponse(folder=str(root), files=[], total=0)

    if not root.exists() or not root.is_dir():
        return OutputListResponse(folder=str(root), files=[], total=0)

    entries: list[OutputFile] = []
    for entry in root.rglob("*.png"):
        if not entry.is_file():
            continue
        try:
            stat = entry.stat()
        except OSError:
            continue
        try:
            relative = entry.relative_to(root).as_posix()
        except ValueError:
            continue
        entries.append(
            OutputFile(
                name=entry.name,
                relative_path=relative,
                size_bytes=stat.st_size,
                modified_at=stat.st_mtime,
            )
        )

    entries.sort(key=lambda f: f.modified_at, reverse=True)
    return OutputListResponse(
        folder=str(root),
        files=entries[:limit],
        total=len(entries),
    )


@router.get("/output/file")
async def get_output_file(
    store: PrefsStoreDep,
    path: str = Query(..., min_length=1, description="Relative path inside output folder."),
) -> FileResponse:
    """Stream a single file from the configured output folder.

    The supplied ``path`` is interpreted relative to the user's output folder
    and rejected if it escapes that root via ``..`` or absolute components.
    """
    prefs = store.load()
    if not prefs.output_folder:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Output folder not configured."
        )
    root = Path(prefs.output_folder).expanduser().resolve()
    try:
        target = _resolve_within(root, path)
    except UnsafePathError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    if not target.exists() or not target.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="File not found."
        )
    return FileResponse(target, media_type="image/png", filename=target.name)


@router.get("/input/file")
async def get_input_file(
    store: PrefsStoreDep,
    path: str = Query(..., min_length=1, description="Relative path inside input folder."),
) -> FileResponse:
    """Stream a single source file from the configured input folder."""
    prefs = store.load()
    if not prefs.input_folder:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Input folder not configured."
        )
    root = Path(prefs.input_folder).expanduser().resolve()
    try:
        target = _resolve_within(root, path)
    except UnsafePathError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    if not target.exists() or not target.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="File not found."
        )
    return FileResponse(target, filename=target.name)
