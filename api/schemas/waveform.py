"""Waveform schemas."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel


class DeriveWaveformsRequest(BaseModel):
    positions: List[int]
    window_end_sec: Optional[float] = None
    coag_ratio: float = 0.5
    align: str = "off"  # "off" | "tc2" | "peak" | "rise"
    baseline: bool = False
    thin: bool = True  # downsample to ~1500 points for overlay
    ref_point_idx: int = 0  # index for chromogenic baseline alignment


class WaveformSeries(BaseModel):
    position: int
    no: int
    label: str
    item_name: str
    mode: str
    time: List[Optional[float]]
    raw: List[Optional[float]]
    scaled: List[Optional[float]]
    endpoint_scaled: List[Optional[float]]
    slope: List[Optional[float]]
    acceleration: List[Optional[float]]
    abs_slope: Optional[List[Optional[float]]] = None
    base_aligned: Optional[List[Optional[float]]] = None
    tc2: Optional[float] = None
    te2: Optional[float] = None
    shift: float = 0.0


class DeriveWaveformsResponse(BaseModel):
    series: List[WaveformSeries]
    skipped_count: int


class DetailWaveformResponse(BaseModel):
    position: int
    no: int
    label: str
    item_name: str
    mode: str
    time: List[Optional[float]]
    raw: List[Optional[float]]
    scaled: List[Optional[float]]
    endpoint_scaled: List[Optional[float]]
    slope: List[Optional[float]]
    acceleration: List[Optional[float]]
    abs_slope: Optional[List[Optional[float]]] = None
    base_aligned: Optional[List[Optional[float]]] = None
    calculated: Dict[str, Any]  # Tc2, Te2, Tc1, Te1, vmax, t_vmax, device_val, diff
    record_info: Dict[str, Any]  # full row metadata
