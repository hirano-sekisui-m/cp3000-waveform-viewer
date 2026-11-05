"""Batch management routes."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, File, HTTPException, Query, UploadFile

import numpy as np
import pandas as pd

from api.config import DEMO_DIR, load_settings, save_settings
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
        root_path = settings.get("root") or str(DEMO_DIR)

    clean_root = clean_path(root_path)
    if not clean_root:
        return []

    rootp = Path(clean_root)
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
                    label=lbl,
                    folder_path=str(f),
                    csv_path=str(c),
                    has_prof=False,
                    has_csv=True,
                    has_log=False,
                ))

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
    if not req.folder_path:
        raise HTTPException(status_code=400, detail="folder_path is required")

    folder = Path(clean_path(req.folder_path))
    if not folder.exists():
        raise HTTPException(status_code=400, detail=f"Folder not found: {folder}")

    files = find_batch_files(folder)

    prof_p: Optional[Path] = None
    if req.prof_file:
        prof_p = folder / req.prof_file
    elif files.prof:
        prof_p = files.prof[0]

    csv_p: Optional[Path] = None
    if req.csv_file:
        csv_p = folder / req.csv_file
    elif files.csv:
        csv_p = files.csv[0]

    log_p: Optional[Path] = None
    if req.log_file:
        log_p = folder / req.log_file
    elif files.log and prof_p is not None:
        log_p = files.log[0]

    if prof_p is None and csv_p is None:
        raise HTTPException(status_code=400, detail="No prof*.dat or *CSV_data.csv found")

    batch_name = folder.name if prof_p is not None else (csv_p.stem if csv_p else folder.name)

    try:
        batch = session_store.load_from_paths(
            prof_p, csv_p, log_p,
            mode=req.profile_mode,
            enc=req.csv_encoding,
            name=batch_name,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load batch: {e}")

    # Persist last batch
    save_settings(last_batch=str(folder))

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
    for kind, p in [("prof", batch.prof_path), ("CSV", batch.csv_path), ("LOG", batch.log_path)]:
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
    )


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
