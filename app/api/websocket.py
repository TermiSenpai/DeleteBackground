"""WebSocket endpoint that streams batch progress to the UI."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.batch_processor import BatchProcessor
from app.models.schemas import ProgressEvent

logger = logging.getLogger(__name__)

ws_router = APIRouter()


@ws_router.websocket("/ws/progress")
async def progress_socket(websocket: WebSocket) -> None:
    """Stream :class:`ProgressEvent` JSON messages until the client disconnects.

    A snapshot of the current status is sent on connect so the UI can render
    immediately even when no job is running.
    """
    await websocket.accept()
    processor: BatchProcessor = websocket.app.state.processor
    queue: asyncio.Queue[ProgressEvent] = asyncio.Queue(maxsize=256)

    async def sink(event: ProgressEvent) -> None:
        # ``put_nowait`` drops the oldest progress message if the consumer
        # is slow — we prefer staying responsive over guaranteeing every
        # intermediate progress tick.
        if queue.full():
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        await queue.put(event)

    processor.subscribe(sink)
    try:
        await websocket.send_json(
            ProgressEvent(type="status", status=processor.status).model_dump()
        )
        while True:
            event = await queue.get()
            await websocket.send_json(event.model_dump())
    except WebSocketDisconnect:
        logger.debug("Progress WebSocket disconnected.")
    except Exception:
        logger.exception("Progress WebSocket error.")
    finally:
        processor.unsubscribe(sink)
