"""Batch management routes."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, File, HTTPException, Query, UploadFile

import numpy as np
import pandas as pd

from api.config import (
    DATA_SOURCE_DIR,
    DEMO_DIR,
    ROOT_DIR,
    get_default_root_path,
    load_settings,
    resolve_data_path,
    save_settings,
)
from api.schemas.batch import (
    BatchFilesDetail,
    BatchSummaryResponse,
    FileInfo,
    FolderEntry,
    LoadBatchRequest,
    RecordQuery,
    RecordsListResponse,
)
from api.services.session_store import session_store
from cp3000.batch import clean_path, find_batch_files, find_batch_folders

router = APIRouter()


@router.get("/folders", response_model=List[FolderEntry])
def list_batch_folders(root_path: Optional[str] = Query(None)) -> List[FolderEntry]:
    """Find batch candidate folders under root_path."""
    if not root_path:
        settings = load_settings()
        root_path = settings.get("root") or get_default_root_path()

    clean_root = clean_path(root_path)
    if not clean_root:
        return []

    rootp = resolve_data_path(clean_root)

    if not rootp.exists():
        return []

    direct_csv: Optional[Path] = None
    if rootp.is_file() and rootp.suffix.lower() == ".csv":
        direct_csv = rootp
        rootp = rootp.parent

    folders = find_batch_folders(rootp)
    entries: List[FolderEntry] = []

    for f in folders:
        f_files = find_batch_files(f)
        if f_files.prof:
            lbl = str(f.relative_to(rootp)) if f != rootp else f.name
            entries.append(FolderEntry(
                entry_id=str(f),
                label=lbl,
                folder_path=str(f),
                csv_path=None,
                has_prof=True,
                has_csv=len(f_files.csv) > 0,
                has_log=len(f_files.log) > 0,
            ))
        else:
            for c in f_files.csv:
                lbl = str(c.relative_to(rootp)) if (f == rootp or len(f_files.csv) > 1) else str(f.relative_to(rootp))
                entries.append(FolderEntry(
                    entry_id=str(c),
                    label=lbl,
                    folder_path=str(f),
                    csv_path=str(c),
                    has_prof=False,
                    has_csv=True,
                    has_log=False,
                ))

    def _entry_mtime(entry: FolderEntry) -> float:
        try:
            if entry.csv_path:
                p = Path(entry.csv_path)
                if p.is_file():
                    return p.stat().st_mtime
            if entry.folder_path:
                fp = Path(entry.folder_path)
                if fp.is_file():
                    return fp.stat().st_mtime
                if fp.is_dir():
                    mtimes = [p.stat().st_mtime for p in fp.iterdir() if p.is_file()]
                    if mtimes:
                        return max(mtimes)
                    return fp.stat().st_mtime
        except Exception:
            pass
        return 0.0

    # Sort entries by modified time descending (newest first)
    entries.sort(key=_entry_mtime, reverse=True)

    if direct_csv is not None:
        direct_str = str(direct_csv)
        entries.sort(key=lambda e: 0 if (e.csv_path == direct_str or e.entry_id == direct_str) else 1)

    return entries


@router.get("/folder-files", response_model=BatchFilesDetail)
def get_folder_files(folder_path: str) -> BatchFilesDetail:
    """Get list of prof, csv, log files inside a folder."""
    p = Path(clean_path(folder_path))
    if not p.is_dir():
        raise HTTPException(status_code=400, detail="Invalid folder path")
    f = find_batch_files(p)
    return BatchFilesDetail(
        prof=[x.name for x in f.prof],
        csv=[x.name for x in f.csv],
        log=[x.name for x in f.log],
    )


@router.post("/load", response_model=BatchSummaryResponse)
def load_batch_endpoint(req: LoadBatchRequest) -> BatchSummaryResponse:
    """Load a batch from folder and options."""
    # Handle single CSV file batch
    target_csv_str = req.csv_path or (req.entry_id if req.entry_id and req.entry_id.lower().endswith(".csv") else None)
    if not target_csv_str and req.folder_path and req.folder_path.lower().endswith(".csv"):
        target_csv_str = req.folder_path

    if target_csv_str:
        csv_p = resolve_data_path(clean_path(target_csv_str))
        if not csv_p.is_file():
            raise HTTPException(status_code=400, detail=f"CSV file not found: {csv_p}")
        prof_p = None
        log_p = None
        folder = csv_p.parent
        batch_name = csv_p.stem
    else:
        if not req.folder_path and not req.entry_id:
            raise HTTPException(status_code=400, detail="folder_path or entry_id is required")

        folder_str = req.folder_path or req.entry_id
        folder = resolve_data_path(clean_path(folder_str))
        if not folder.exists():
            raise HTTPException(status_code=400, detail=f"Folder not found: {folder}")

        files = find_batch_files(folder)

        prof_p = None
        if req.prof_file:
            prof_p = folder / req.prof_file
        elif files.prof:
            prof_p = files.prof[0]

        csv_p = None
        if req.csv_file:
            csv_p = folder / req.csv_file
        elif files.csv:
            csv_p = files.csv[0]

        log_p = None
        if req.log_file:
            log_p = folder / req.log_file
        elif files.log and prof_p is not None:
            log_p = files.log[0]

        if prof_p is None and csv_p is None:
            raise HTTPException(status_code=400, detail="No prof*.dat or *CSV_data.csv found")

        batch_name = folder.name if prof_p is not None else (csv_p.stem if csv_p else folder.name)

    try:
        session_store.load_from_paths(
            prof_p, csv_p, log_p,
            mode=req.profile_mode,
            enc=req.csv_encoding,
            name=batch_name,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load batch: {e}")

    # Persist last batch
    last_val = str(csv_p) if (prof_p is None and csv_p is not None) else str(folder)
    save_settings(last_batch=last_val)

    return get_current_summary()


@router.post("/upload", response_model=BatchSummaryResponse)
async def upload_files(
    files: List[UploadFile] = File(...),
    profile_mode: str = "auto",
    csv_encoding: str = "cp932",
) -> BatchSummaryResponse:
    """Upload data files (.dat, .csv) and load as batch."""
    upload_dir = session_store.create_upload_dir()
    for uf in files:
        if not uf.filename:
            continue
        dest = upload_dir / Path(uf.filename).name
        dest.write_bytes(await uf.read())

    f = find_batch_files(upload_dir)
    prof_p = f.prof[0] if f.prof else None
    csv_p = f.csv[0] if f.csv else None
    log_p = f.log[0] if f.log else None

    if prof_p is None and csv_p is None:
        raise HTTPException(status_code=400, detail="Uploaded files do not contain prof*.dat or *CSV_data.csv")

    batch_name = csv_p.stem if (prof_p is None and csv_p is not None) else "アップロード"
    try:
        session_store.load_from_paths(
            prof_p, csv_p, log_p,
            mode=profile_mode,
            enc=csv_encoding,
            name=batch_name,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load uploaded batch: {e}")

    return get_current_summary()


@router.get("/summary", response_model=BatchSummaryResponse)
def get_current_summary() -> BatchSummaryResponse:
    """Get active batch summary."""
    batch = session_store.current_batch
    if batch is None:
        raise HTTPException(status_code=404, detail="No active batch")

    table = batch.table
    samples_count = int(table["依頼No"].nunique()) if "依頼No" in table.columns and table["依頼No"].notna().any() else None
    items_count = int(table["項目名"].nunique()) if "項目名" in table.columns else 0
    csv_matched = int(table["CSV対応"].sum()) if "CSV対応" in table.columns else 0
    err_count = int((table["エラーフラグ"] != 0).sum()) if "エラーフラグ" in table.columns else 0

    file_infos: List[FileInfo] = []
    for kind, p in [("prof", batch.prof_path), ("csv", batch.csv_path), ("log", batch.log_path)]:
        if p is None:
            file_infos.append(FileInfo(kind=kind))
        else:
            file_infos.append(FileInfo(
                kind=kind,
                filename=p.name,
                size=p.stat().st_size if p.exists() else None,
                folder=str(p.parent) if p.exists() else None,
            ))

    group_col = "属性" if "属性" in table.columns else ("測定種別" if "測定種別" in table.columns else None)
    groups = sorted(table[group_col].dropna().astype(str).unique().tolist()) if group_col else []
    items = sorted(table["項目名"].dropna().unique().tolist()) if "項目名" in table.columns else []

    time_pts: List[float] = []
    chromo_time_pts: List[float] = []

    if "測定モード" in table.columns and (table["測定モード"] == "比色項目").any():
        chromo_rows = table[table["測定モード"] == "比色項目"]
        first_chromo_pos = int(chromo_rows.iloc[0]["No"]) - 1
        if 0 <= first_chromo_pos < len(batch.records):
            cr = batch.records[first_chromo_pos]
            if cr.time is not None and len(cr.time):
                chromo_time_pts = [float(round(x, 1)) for x in cr.time]

    if batch.time_points is not None and len(batch.time_points):
        time_pts = [float(round(x, 1)) for x in batch.time_points]
    elif len(batch.records):
        longest = max(batch.records, key=lambda r: len(r.time) if r.time is not None else 0)
        if longest.time is not None:
            time_pts = [float(round(x, 1)) for x in longest.time]

    if not chromo_time_pts and "比色項目" in batch.modes:
        chromo_time_pts = time_pts

    return BatchSummaryResponse(
        name=batch.name,
        total_records=len(batch.records),
        samples_count=samples_count,
        items_count=items_count,
        csv_matched=csv_matched,
        error_count=err_count,
        modes=batch.modes,
        points_summary=batch.profile_n_summary(),
        step_summary=batch.time_step_summary(),
        files=file_infos,
        warnings=batch.warnings,
        items_list=items,
        groups_list=groups,
        columns=list(table.columns),
        time_points=time_pts,
        chromo_time_points=chromo_time_pts,
    )



def _eval_numeric_expr(series: pd.Series, expr: str) -> pd.Series:
    """Evaluate numeric condition on a pandas Series (e.g. '> 50', '<= 20', '10-50')."""
    s = pd.to_numeric(series, errors="coerce")
    trimmed = expr.strip()
    if not trimmed:
        return pd.Series(True, index=series.index)

    # Range: "10-50", "10..50", "10～50"
    m_range = re.match(r"^(-?\d+(?:\.\d+)?)\s*(?:-|\.\.|～|~)\s*(-?\d+(?:\.\d+)?)$", trimmed)
    if m_range:
        lo = float(m_range.group(1))
        hi = float(m_range.group(2))
        return s.notna() & (s >= min(lo, hi)) & (s <= max(lo, hi))

    # Operator + number: ">= 50", "< 10", "= 5", "50"
    m_op = re.match(r"^(>=|<=|>|<|==|=|!=)?\s*(-?\d+(?:\.\d+)?)$", trimmed)
    if m_op:
        op = m_op.group(1) or "="
        target = float(m_op.group(2))
        if op == ">":
            return s.notna() & (s > target)
        elif op == ">=":
            return s.notna() & (s >= target)
        elif op == "<":
            return s.notna() & (s < target)
        elif op == "<=":
            return s.notna() & (s <= target)
        elif op in ("=", "=="):
            return s.notna() & np.isclose(s, target, atol=1e-5)
        elif op == "!=":
            return s.notna() & (~np.isclose(s, target, atol=1e-5))

    return pd.Series(True, index=series.index)


@router.post("/records", response_model=RecordsListResponse)
def query_records(
    query: RecordQuery,
    window_end_sec: Optional[float] = Query(None),
    coag_ratio: float = Query(0.5),
) -> RecordsListResponse:
    """Get filtered and searched waveform records table."""
    batch = session_store.current_batch
    if batch is None:
        raise HTTPException(status_code=404, detail="No active batch")

    table = batch.table.copy()
    tetc = session_store.get_tetc(window_end_sec, coag_ratio)

    if len(tetc) == len(table):
        table["Tc2(計算)"] = tetc["Tc2"].round(1).to_numpy()
        table["Te2(計算)"] = tetc["Te2"].round(1).to_numpy()
    table["_pos"] = table["No"] - 1

    group_col = "属性" if "属性" in table.columns else ("測定種別" if "測定種別" in table.columns else None)

    view = table
    if query.items:
        view = view[view["項目名"].isin(query.items)]
    if query.groups and group_col:
        view = view[view[group_col].astype(str).isin(query.groups)]
    if query.mode and "測定モード" in view.columns:
        view = view[view["測定モード"] == query.mode]
    if query.error_only and "エラーフラグ" in view.columns:
        view = view[view["エラーフラグ"] != 0]

    if query.request_no:
        req_cols = [c for c in ["依頼No", "内部依頼No"] if c in view.columns]
        if req_cols:
            parts = [p.strip() for p in re.split(r"[,、\s]+", query.request_no) if p.strip()]
            if parts:
                hit = np.zeros(len(view), dtype=bool)
                for c in req_cols:
                    for p in parts:
                        hit |= view[c].astype(str).str.contains(p, case=False, regex=False, na=False).to_numpy()
                view = view[hit]

    if query.meas_expr and "測定値" in view.columns:
        mask = _eval_numeric_expr(view["測定値"], query.meas_expr)
        view = view[mask]

    if query.proc_expr:
        proc_col = "処理値" if "処理値" in view.columns else ("Tc2(計算)" if "Tc2(計算)" in view.columns else None)
        if proc_col:
            mask = _eval_numeric_expr(view[proc_col], query.proc_expr)
            view = view[mask]

    if query.search:
        search_cols = [c for c in ["依頼No", "SID", "検体名", "検体ﾊﾞｰｺｰﾄﾞ", "内部依頼No", "項目名"] if c in view.columns]
        hit = np.zeros(len(view), dtype=bool)
        for c in search_cols:
            hit |= view[c].astype(str).str.contains(query.search, case=False, regex=False, na=False).to_numpy()
        view = view[hit]

    filtered_total = len(view)

    if query.limit is not None and query.limit > 0:
        view = view.iloc[query.offset : query.offset + query.limit]

    # Convert table to records list with NaN replaced
    records_dict = view.replace({np.nan: None}).to_dict(orient="records")

    return RecordsListResponse(
        total=len(batch.records),
        filtered_total=filtered_total,
        records=records_dict,
    )
