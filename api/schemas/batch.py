"""Batch related schemas."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class FolderEntry(BaseModel):
    label: str
    folder_path: str
    csv_path: Optional[str] = None
    has_prof: bool = False
    has_csv: bool = False
    has_log: bool = False


class BatchFilesDetail(BaseModel):
    prof: List[str]
    csv: List[str]
    log: List[str]


class LoadBatchRequest(BaseModel):
    folder_path: Optional[str] = None
    prof_file: Optional[str] = None
    csv_file: Optional[str] = None
    log_file: Optional[str] = None
    profile_mode: str = "auto"
    csv_encoding: str = "cp932"


class FileInfo(BaseModel):
    kind: str
    filename: Optional[str] = None
    size: Optional[int] = None
    folder: Optional[str] = None


class BatchSummaryResponse(BaseModel):
    name: str
    total_records: int
    samples_count: Optional[int] = None
    items_count: int
    csv_matched: int
    error_count: int
    modes: List[str] = []
    points_summary: str
    step_summary: str
    files: List[FileInfo]
    warnings: List[str] = []
    items_list: List[str] = []
    groups_list: List[str] = []
    columns: List[str] = []


class RecordQuery(BaseModel):
    items: Optional[List[str]] = None
    groups: Optional[List[str]] = None
    search: Optional[str] = None
    error_only: bool = False
    mode: Optional[str] = None
    limit: Optional[int] = None
    offset: int = 0


class RecordsListResponse(BaseModel):
    total: int
    filtered_total: int
    records: List[Dict[str, Any]]
