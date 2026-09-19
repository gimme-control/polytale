"""Serve the built web client from the API process (``bash run.sh --prod``)."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse


def mount_spa(app: FastAPI, dist: Path) -> None:
    """Static files from ``dist``; any other non-API path falls back to ``index.html``."""
    index = dist / "index.html"
    root = dist.resolve()

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        if path.startswith("api/"):
            raise HTTPException(404)
        file = (dist / path).resolve()
        if path and file.is_file() and file.is_relative_to(root):
            return FileResponse(file)
        return FileResponse(index)
