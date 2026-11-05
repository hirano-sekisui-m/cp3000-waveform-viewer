"""Waveform calculation and detail routes."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
from fastapi import APIRouter, HTTPException, Path as FPath, Query

import numpy as np
import pandas as pd

from api.schemas.waveform import (
    DeriveWaveformsRequest,
    DeriveWaveformsResponse,
    DetailWaveformResponse,
    WaveformSeries,
)
from api.services.session_store import session_store
from cp3000.signal import align_waveform_time

router = APIRouter()


def _downsample(arr: np.ndarray, max_points: int = 1500) -> np.ndarray:
    """Evenly downsample array to approximately max_points."""
    if len(arr) <= max_points:
        return arr
    step = int(np.ceil(len(arr) / max_points))
    sub = arr[::step]
    if len(arr) > 0 and (len(sub) == 0 or sub[-1] != arr[-1]):
        sub = np.append(sub, arr[-1])
    return sub


def _to_clean_list(arr: Optional[np.ndarray]) -> Optional[List[float]]:
    """Convert numpy array to list with NaN converted to None/nan."""
    if arr is None:
        return None
    # Replace NaN or Inf with None for valid JSON output
    cleaned = []
    for x in arr:
        if np.isnan(x) or np.isinf(x):
            cleaned.append(None)
        else:
            cleaned.append(float(round(x, 4)))
    return cleaned


@router.post("/derive", response_model=DeriveWaveformsResponse)
def derive_waveforms(req: DeriveWaveformsRequest) -> DeriveWaveformsResponse:
    """Calculate derived waveforms for given record positions."""
    batch = session_store.current_batch
    if batch is None:
        raise HTTPException(status_code=404, detail="No active batch")

    if not req.positions:
        return DeriveWaveformsResponse(series=[], skipped_count=0)

    # Limit to maximum 300 waveforms
    positions = tuple(int(p) for p in req.positions[:300])
    d = session_store.get_derived(positions, req.window_end_sec, req.coag_ratio)

    series_list: List[WaveformSeries] = []
    skipped_count = 0

    table = batch.table

    for k, pos in enumerate(positions):
        row = table[table["No"] == (pos + 1)].iloc[0] if (table["No"] == (pos + 1)).any() else table.iloc[pos]
        t = d.time_at(k)
        if len(t) == 0:
            skipped_count += 1
            continue

        # Calculate time shift
        shift = 0.0
        if req.align == "tc2":
            tc2_val = d.tetc["Tc2"].iloc[k]
            if np.isfinite(tc2_val):
                shift = float(tc2_val)
            else:
                skipped_count += 1
                continue
        elif req.align in ("peak", "rise"):
            ref = (d.slope[k] if req.align == "peak" else d.scaled[k])[: len(t)]
            if not np.isfinite(ref).any():
                skipped_count += 1
                continue
            shifted = align_waveform_time(t, ref, align_mode=req.align)
            shift = float(t[0] - shifted[0])

        shifted_time = t - shift
        n_k = len(t)
        raw = d.raw[k, :n_k].copy()
        if req.baseline:
            fin = np.flatnonzero(np.isfinite(raw))
            if fin.size:
                raw = raw - raw[fin[0]]

        scaled = d.scaled[k, :n_k]
        endpoint_scaled = d.endpoint_scaled[k, :n_k]
        slope = d.slope[k, :n_k]
        acceleration = d.acceleration[k, :n_k]
        abs_slope = d.abs_slope[k, :n_k] if d.abs_slope is not None else None
        base_aligned = d.align_chromogenic_baseline(k, ref_idx=req.ref_point_idx)

        # Downsample if thin requested
        if req.thin and len(shifted_time) > 1500:
            step = int(np.ceil(len(shifted_time) / 1500))
            idx = np.arange(0, len(shifted_time), step)
            shifted_time = shifted_time[idx]
            raw = raw[idx]
            scaled = scaled[idx]
            endpoint_scaled = endpoint_scaled[idx]
            slope = slope[idx]
            acceleration = acceleration[idx]
            if abs_slope is not None:
                abs_slope = abs_slope[idx]
            if base_aligned is not None:
                base_aligned = base_aligned[idx]

        tc2 = float(d.tetc["Tc2"].iloc[k]) if np.isfinite(d.tetc["Tc2"].iloc[k]) else None
        te2 = float(d.tetc["Te2"].iloc[k]) if np.isfinite(d.tetc["Te2"].iloc[k]) else None

        label_parts = []
        for c in ["依頼No", "項目名", "検体名", "SID", "内部依頼No"]:
            if c in row and pd.notna(row[c]) and str(row[c]).strip() not in ("", "nan", "<NA>"):
                label_parts.append(str(row[c]))
        label = " / ".join(label_parts[:2]) if label_parts else f"No {row['No']}"

        series_list.append(WaveformSeries(
            position=pos,
            no=int(row["No"]),
            label=label,
            item_name=str(row.get("項目名", "")),
            mode=str(row.get("測定モード", "その他")),
            time=_to_clean_list(shifted_time) or [],
            raw=_to_clean_list(raw) or [],
            scaled=_to_clean_list(scaled) or [],
            endpoint_scaled=_to_clean_list(endpoint_scaled) or [],
            slope=_to_clean_list(slope) or [],
            acceleration=_to_clean_list(acceleration) or [],
            abs_slope=_to_clean_list(abs_slope),
            base_aligned=_to_clean_list(base_aligned),
            tc2=float(round(tc2 - shift, 2)) if tc2 is not None else None,
            te2=float(round(te2 - shift, 2)) if te2 is not None else None,
            shift=float(round(shift, 2)),
        ))


    return DeriveWaveformsResponse(
        series=series_list,
        skipped_count=skipped_count,
    )


@router.get("/detail/{no}", response_model=DetailWaveformResponse)
def get_waveform_detail(
    no: int,
    window_end_sec: Optional[float] = Query(None),
    coag_ratio: float = Query(0.5),
    ref_point_idx: int = Query(0),
) -> DetailWaveformResponse:
    """Get full-resolution detail for a single waveform by No."""
    batch = session_store.current_batch
    if batch is None:
        raise HTTPException(status_code=404, detail="No active batch")

    table = batch.table
    match = table[table["No"] == no]
    if match.empty:
        raise HTTPException(status_code=404, detail=f"Waveform No {no} not found")

    row = match.iloc[0]
    pos = int(row["No"]) - 1

    d = session_store.get_derived((pos,), window_end_sec, coag_ratio)
    t = d.time_at(0)
    tt = d.tetc.iloc[0].to_dict()

    n_k = len(t)
    raw = d.raw[0, :n_k]
    scaled = d.scaled[0, :n_k]
    endpoint_scaled = d.endpoint_scaled[0, :n_k]
    slope = d.slope[0, :n_k]
    acceleration = d.acceleration[0, :n_k]
    abs_slope = d.abs_slope[0, :n_k] if d.abs_slope is not None else None
    base_aligned = d.align_chromogenic_baseline(0, ref_idx=ref_point_idx)


    # Calculated metrics
    v = slope
    vmax = float(np.nanmax(v)) if np.isfinite(v).any() else None
    t_vmax = float(t[int(np.nanargmax(v))]) if np.isfinite(v).any() else None

    device_val = None
    if "測定値" in row and pd.notna(row["測定値"]):
        try:
            device_val = float(row["測定値"])
        except (ValueError, TypeError):
            pass

    tc2_diff = None
    if device_val is not None and np.isfinite(tt.get("Tc2")):
        tc2_diff = float(round(tt["Tc2"] - device_val, 2))

    calculated = {
        "Tc2": float(round(tt["Tc2"], 2)) if np.isfinite(tt.get("Tc2")) else None,
        "Te2": float(round(tt["Te2"], 2)) if np.isfinite(tt.get("Te2")) else None,
        "Tc1": float(round(tt["Tc1"], 2)) if np.isfinite(tt.get("Tc1")) else None,
        "Te1": float(round(tt["Te1"], 2)) if np.isfinite(tt.get("Te1")) else None,
        "device_val": device_val,
        "tc2_diff": tc2_diff,
        "vmax": float(round(vmax, 2)) if vmax is not None else None,
        "t_vmax": float(round(t_vmax, 1)) if t_vmax is not None else None,
    }

    label_parts = []
    for c in ["依頼No", "項目名", "検体名", "SID", "内部依頼No"]:
        if c in row and pd.notna(row[c]) and str(row[c]).strip() not in ("", "nan", "<NA>"):
            label_parts.append(str(row[c]))
    label = " / ".join(label_parts[:2]) if label_parts else f"No {row['No']}"

    record_info = {
        k: ("" if pd.isna(v) else (int(v) if isinstance(v, (np.integer, int)) else str(v)))
        for k, v in row.items()
        if not k.startswith("_")
    }

    return DetailWaveformResponse(
        position=pos,
        no=no,
        label=label,
        item_name=str(row.get("項目名", "")),
        mode=str(row.get("測定モード", "その他")),
        time=_to_clean_list(t) or [],
        raw=_to_clean_list(raw) or [],
        scaled=_to_clean_list(scaled) or [],
        endpoint_scaled=_to_clean_list(endpoint_scaled) or [],
        slope=_to_clean_list(slope) or [],
        acceleration=_to_clean_list(acceleration) or [],
        abs_slope=_to_clean_list(abs_slope),
        base_aligned=_to_clean_list(base_aligned),
        calculated=calculated,

        record_info=record_info,
    )
