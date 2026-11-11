"""Configuration and settings management for CP3000 Viewer."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict

ROOT_DIR = Path(__file__).resolve().parents[1]
# Support both dev repository root and distributable package root (parent of app/)
APP_PARENT = ROOT_DIR.parent if (ROOT_DIR.parent / "start_viewer.bat").is_file() else ROOT_DIR
SETTINGS_PATH = Path(os.environ.get("CP3000_SETTINGS") or (ROOT_DIR / "settings.json"))
DEMO_DIR = (ROOT_DIR / "demo_data") if (ROOT_DIR / "demo_data").exists() else (APP_PARENT / "demo_data")
DATA_SOURCE_DIR = (APP_PARENT / "data-source") if (APP_PARENT / "data-source").exists() else (ROOT_DIR / "data-source")
STATIC_DIR = ROOT_DIR / "web" / "dist"


def resolve_data_path(path_str: str) -> Path:
    """Resolve a relative or absolute path against DATA_SOURCE_DIR, APP_PARENT, or ROOT_DIR."""
    p = Path(path_str)
    if p.is_absolute():
        return p
    for base in (DATA_SOURCE_DIR.parent, APP_PARENT, ROOT_DIR):
        cand = (base / p).resolve()
        if cand.exists():
            return cand
    return (ROOT_DIR / p).resolve()


def get_default_root_path() -> str:
    """Determine the default root folder path:
    Always prefer data-source as standard location for routine operation.
    Falls back to demo_data only if data-source directory does not exist at all.
    """
    if DATA_SOURCE_DIR.exists():
        return "data-source"
    if DEMO_DIR.exists():
        return "demo_data"
    return "data-source"


def load_settings() -> Dict[str, Any]:
    """Load settings from JSON file or return default dict."""
    try:
        if SETTINGS_PATH.is_file():
            data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            if not data.get("root"):
                data["root"] = get_default_root_path()
            return data
    except Exception:
        pass
    return {"root": get_default_root_path()}


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
