"""Domain exceptions raised by the core layer."""

from __future__ import annotations


class DeleteBackgroundError(Exception):
    """Base exception for all application errors."""


class FolderNotFoundError(DeleteBackgroundError):
    """Raised when a user-supplied folder does not exist or is not a directory."""


class UnsafePathError(DeleteBackgroundError):
    """Raised when a path resolves outside an allowed root."""


class JobAlreadyRunningError(DeleteBackgroundError):
    """Raised when a second job is started while one is already in progress."""


class JobNotRunningError(DeleteBackgroundError):
    """Raised when an operation requires a running job and none is active."""


class ModelLoadError(DeleteBackgroundError):
    """Raised when the segmentation model cannot be loaded."""
