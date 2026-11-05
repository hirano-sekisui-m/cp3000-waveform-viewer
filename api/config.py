"""Configuration and settings management for CP3000 Viewer."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict

ROOT_DIR = Path(__file__).resolve().parents[1]
SETTINGS_PATH = Path(os.environ.get("CP3000_SETTINGS") or (ROOT_DIR / "settings.json"))
DEMO_DIR = ROOT_DIR / "demo_data"
STATIC_DIR = ROOT_DIR / "web" / "dist"


def load_settings() -> Dict[str, Any]:
    """Load settings from JSON file or return empty dict."""
    try:
        if SETTINGS_PATH.is_file():
            return json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def save_settings(**kw: Any) -> Dict[str, Any]:
    """Update and persist settings."""
    data = load_settings()
    data.update(kw)
    try:
        SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass
    return data
