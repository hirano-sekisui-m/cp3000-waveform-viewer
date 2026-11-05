"""Settings schemas."""

from __future__ import annotations

from typing import Any, Dict, Optional
from pydantic import BaseModel, ConfigDict


class SettingsModel(BaseModel):
    model_config = ConfigDict(extra="allow")

    root: Optional[str] = None
    last_batch: Optional[str] = None
    extra: Dict[str, Any] = {}

