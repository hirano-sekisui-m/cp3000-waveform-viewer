"""FastAPI Application entry point."""

from __future__ import annotations

import os
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from api.config import STATIC_DIR
from api.routes import batches, export, system, waveforms

app = FastAPI(
    title="CP3000 Waveform Viewer API",
    description="FastAPI backend for CP3000 Waveform Viewer",
    version="0.2.1",
)

# CORS middleware for development (e.g. Vite dev server on port 5173)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register API routers
app.include_router(system.router, prefix="/api", tags=["system"])
app.include_router(batches.router, prefix="/api/batches", tags=["batches"])
app.include_router(waveforms.router, prefix="/api/waveforms", tags=["waveforms"])
app.include_router(export.router, prefix="/api/export", tags=["export"])

# Compatibility health endpoint for viewer_ctl.py / start_viewer.bat
@app.get("/_stcore/health", tags=["system"])
@app.get("/health", tags=["system"])
def compatibility_health():
    return "ok"


# Mount static files if web/dist exists (production/distribution mode)
if STATIC_DIR.is_dir():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        file_path = STATIC_DIR / full_path
        if file_path.is_file():
            return FileResponse(file_path)
        index_file = STATIC_DIR / "index.html"
        if index_file.is_file():
            return FileResponse(index_file)
        return {"status": "Frontend not built yet"}
else:
    @app.get("/")
    def root():
        return {
            "message": "CP3000 Waveform Viewer API is running.",
            "docs_url": "/docs",
            "note": "Frontend build (web/dist) not found. Run Vite dev server for frontend.",
        }
