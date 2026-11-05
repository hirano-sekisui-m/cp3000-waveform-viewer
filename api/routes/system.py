"""System and settings routes."""

from __future__ import annotations

from typing import Any, Dict
from fastapi import APIRouter

from api.config import load_settings, save_settings
from api.schemas.settings import SettingsModel

router = APIRouter()


@router.get("/health")
def health_check() -> Dict[str, str]:
    return {"status": "ok"}


@router.get("/settings")
def get_settings() -> Dict[str, Any]:
    return load_settings()


@router.post("/settings")
def update_settings(settings: SettingsModel) -> Dict[str, Any]:
    data = settings.model_dump(exclude_unset=True)
    extra = data.pop("extra", {})
    data.update(extra)
    return save_settings(**data)

