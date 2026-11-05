"""Data export routes (CSV download)."""

from __future__ import annotations

import io
from urllib.parse import quote
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel

import numpy as np
import pandas as pd

from api.services.session_store import session_store

router = APIRouter()


class ExportWaveformsRequest(BaseModel):
    positions: List[int]
    kind: str = "raw"  # "raw" | "scaled" | "endpoint_scaled" | "slope" | "acceleration" | "abs_slope" | "base_aligned"
    window_end_sec: Optional[float] = None
    coag_ratio: float = 0.5
    ref_point_idx: int = 0


@router.get("/table-csv")
def export_table_csv() -> Response:
    """Export current batch record table as CSV (UTF-8 with BOM for Excel)."""
    batch = session_store.current_batch
    if batch is None:
        raise HTTPException(status_code=404, detail="No active batch")

    table = batch.table.copy()
    tetc = session_store.get_tetc()
    if len(tetc) == len(table):
        table["Tc2(計算)"] = tetc["Tc2"].round(1).to_numpy()
        table["Te2(計算)"] = tetc["Te2"].round(1).to_numpy()

    drop_cols = [c for c in ["_pos", "_label"] if c in table.columns]
    table = table.drop(columns=drop_cols)

    csv_data = table.to_csv(index=False).encode("utf-8-sig")
    filename = f"{batch.name}_table.csv"
    encoded_fn = quote(filename)

    return Response(
        content=csv_data,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{encoded_fn}"; filename*=UTF-8\'\'{encoded_fn}'},
    )


@router.post("/waveforms-csv")
def export_waveforms_csv(req: ExportWaveformsRequest) -> Response:
    """Export selected waveforms as wide CSV (1 row per waveform, columns = seconds)."""
    batch = session_store.current_batch
    if batch is None:
        raise HTTPException(status_code=404, detail="No active batch")

    if not req.positions:
        raise HTTPException(status_code=400, detail="No positions selected")

    positions = tuple(int(p) for p in req.positions)
    d = session_store.get_derived(positions, req.window_end_sec, req.coag_ratio)

    table = batch.table
    chosen = table[table["No"].isin([p + 1 for p in positions])].reset_index(drop=True)
    if chosen.empty:
        chosen = table.iloc[list(positions)].reset_index(drop=True)

    meta_cols = [c for c in ["No", "依頼No", "内部依頼No", "項目番号", "項目名", "SID", "検体名", "測定モード", "測定値", "Tc2(計算)"] if c in chosen.columns]
    meta = chosen[meta_cols]

    kind = req.kind

    def get_kind_arr(k: int) -> np.ndarray:
        n_k = len(d.time_at(k))
        if kind == "scaled":
            return d.scaled[k, :n_k]
        elif kind == "endpoint_scaled":
            return d.endpoint_scaled[k, :n_k]
        elif kind == "slope":
            return d.slope[k, :n_k]
        elif kind == "acceleration":
            return d.acceleration[k, :n_k]
        elif kind == "abs_slope" and d.abs_slope is not None:
            return d.abs_slope[k, :n_k]
        elif kind == "base_aligned":
            aligned = d.align_chromogenic_baseline(k, ref_idx=req.ref_point_idx)
            if aligned is not None:
                return aligned
        return d.raw[k, :n_k]

    if d.times is None:
        vals = np.vstack([get_kind_arr(k) for k in range(len(positions))])
        val_df = pd.DataFrame(vals, columns=[f"{x:g}" if round(x, 1) != x else f"{x:.1f}" for x in d.time])
    else:
        row_series = [
            pd.Series(get_kind_arr(k), index=np.round(d.time_at(k), 3))
            for k in range(len(positions))
        ]
        val_df = pd.DataFrame(row_series).reset_index(drop=True)
        val_df.columns = [f"{float(x):g}" if round(float(x), 1) != float(x) else f"{float(x):.1f}" for x in val_df.columns]

    wide = pd.concat([meta, val_df], axis=1)
    csv_data = wide.to_csv(index=False).encode("utf-8-sig")
    filename = f"{batch.name}_{kind}.csv"
    encoded_fn = quote(filename)

    return Response(
        content=csv_data,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{encoded_fn}"; filename*=UTF-8\'\'{encoded_fn}'},
    )
