from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.decorators.inject_module import Module

router = APIRouter(tags=["Health"])


@router.get("/", summary="Service and version")
def index(module: Module) -> JSONResponse:
    """No route list: that is the docs' job, and they are off in production."""
    return JSONResponse({"service": "stark-api", "version": module.config.version,
                         "stub": True})


@router.get("/health", summary="Liveness")
def health(module: Module) -> JSONResponse:
    return JSONResponse({"status": "ok", "stub": True, "version": module.config.version})
