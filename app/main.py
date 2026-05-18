"""FastAPI application entrypoint."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app import __version__
from app.api.routes import router as api_router
from app.api.websocket import ws_router
from app.config import settings
from app.core.background_remover import BackgroundRemover
from app.core.batch_processor import BatchProcessor
from app.utils.logger import configure_logging

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = PROJECT_ROOT / "templates"
STATIC_DIR = PROJECT_ROOT / "static"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Initialise singletons at startup and clean them up at shutdown."""
    configure_logging(settings.log_level)
    logger.info("DeleteBackground %s starting on %s:%d", __version__, settings.host, settings.port)

    remover = BackgroundRemover()
    processor = BatchProcessor(remover)
    app.state.remover = remover
    app.state.processor = processor

    try:
        yield
    finally:
        if processor.is_running:
            try:
                processor.request_cancel()
            except Exception:
                logger.debug("Cancel on shutdown raised; ignoring.")
        logger.info("DeleteBackground shutting down.")


def create_app() -> FastAPI:
    """Build the FastAPI application."""
    app = FastAPI(
        title="DeleteBackground",
        version=__version__,
        description="Batch background removal — local, free, fast.",
        lifespan=lifespan,
    )

    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    app.include_router(api_router)
    app.include_router(ws_router)

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    async def index(request: Request) -> HTMLResponse:
        """Render the single-page UI."""
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={"version": __version__},
        )

    return app


app = create_app()
