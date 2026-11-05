"""In-memory session and cache manager for CP3000 batches."""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from cp3000.batch import Batch, clean_path, find_batch_files, find_batch_folders, load_batch
from cp3000.signal import Derived


def file_sig(p: Optional[Path]) -> str:
    """Generate a cache signature based on file path, size and modification time."""
    if p is None or not p.exists():
        return "-"
    try:
        s = p.stat()
        return f"{p}|{s.st_size}|{s.st_mtime_ns}"
    except OSError:
        return "-"


class SessionStore:
    """Manages currently active batch, temporary uploads, and calculation caches."""

    def __init__(self) -> None:
        self.current_batch: Optional[Batch] = None
        self.current_sig: str = ""
        self.temp_upload_dir: Optional[Path] = None
        self._tetc_cache: Dict[Tuple[str, Optional[float], float], pd.DataFrame] = {}
        self._derived_cache: Dict[Tuple[str, Tuple[int, ...], Optional[float], float], Derived] = {}

    def clear(self) -> None:
        """Clear active batch and caches."""
        self.current_batch = None
        self.current_sig = ""
        self._tetc_cache.clear()
        self._derived_cache.clear()
        if self.temp_upload_dir and self.temp_upload_dir.exists():
            try:
                shutil.rmtree(self.temp_upload_dir, ignore_errors=True)
            except Exception:
                pass
            self.temp_upload_dir = None

    def create_upload_dir(self) -> Path:
        """Create or recreate a temporary directory for uploaded files."""
        if self.temp_upload_dir and self.temp_upload_dir.exists():
            try:
                shutil.rmtree(self.temp_upload_dir, ignore_errors=True)
            except Exception:
                pass
        d = Path(tempfile.mkdtemp(prefix="cp3000_upload_"))
        self.temp_upload_dir = d
        return d

    def load_from_paths(
        self,
        prof_p: Optional[Path],
        csv_p: Optional[Path],
        log_p: Optional[Path],
        *,
        mode: str = "auto",
        enc: str = "cp932",
        name: str = "",
    ) -> Batch:
        """Load a batch from disk files and cache it."""
        sig = "||".join([file_sig(prof_p), file_sig(csv_p), file_sig(log_p), mode, enc])
        if self.current_batch is not None and self.current_sig == sig:
            return self.current_batch

        batch = load_batch(
            str(prof_p) if prof_p else None,
            str(csv_p) if csv_p else None,
            str(log_p) if log_p else None,
            profile_mode=mode,
            csv_encoding=enc,
            name=name or (prof_p.parent.name if prof_p else (csv_p.stem if csv_p else "Batch")),
        )
        self.current_batch = batch
        self.current_sig = sig
        self._tetc_cache.clear()
        self._derived_cache.clear()
        return batch

    def get_tetc(self, window: Optional[float] = None, coag: float = 0.5) -> pd.DataFrame:
        """Get Te/Tc table for all records in the active batch."""
        if self.current_batch is None:
            return pd.DataFrame(columns=["Te1", "Tc1", "Te1_Tc1", "Te2", "Tc2", "Te2_Tc2"])

        cache_key = (self.current_sig, window, round(coag, 3))
        if cache_key in self._tetc_cache:
            return self._tetc_cache[cache_key]

        parts = []
        n = len(self.current_batch.records)
        for start in range(0, n, 200):
            pos = list(range(start, min(n, start + 200)))
            parts.append(self.current_batch.derive(pos, window_end_sec=window, coag_ratio=coag).tetc)

        if not parts:
            df = pd.DataFrame(columns=["Te1", "Tc1", "Te1_Tc1", "Te2", "Tc2", "Te2_Tc2"])
        else:
            df = pd.concat(parts, ignore_index=True)

        if len(self._tetc_cache) > 8:
            self._tetc_cache.pop(next(iter(self._tetc_cache)))
        self._tetc_cache[cache_key] = df
        return df

    def get_derived(
        self,
        positions: Tuple[int, ...],
        window: Optional[float] = None,
        coag: float = 0.5,
    ) -> Derived:
        """Compute or retrieve derived waveforms for specified positions."""
        if self.current_batch is None:
            raise ValueError("No active batch loaded")

        cache_key = (self.current_sig, positions, window, round(coag, 3))
        if cache_key in self._derived_cache:
            return self._derived_cache[cache_key]

        d = self.current_batch.derive(list(positions), window_end_sec=window, coag_ratio=coag)

        if len(self._derived_cache) > 16:
            self._derived_cache.pop(next(iter(self._derived_cache)))
        self._derived_cache[cache_key] = d
        return d


# Global singleton instance for single-user application
session_store = SessionStore()
