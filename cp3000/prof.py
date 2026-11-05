"""Reader for CP3000 prof*.dat (binary absorbance profiles, 3600 or 6000 points per record).

Copied from CWA-ML-tool src/cwa/ingestion/prof.py (commit a591105) without changes to the logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np
import pandas as pd

HEADER_SIZE = 16

PROFILE_N_600 = 6000
RECORD_SIZE_600 = HEADER_SIZE + PROFILE_N_600 * 2  # 12016

PROFILE_N_360 = 3600
RECORD_SIZE_360 = HEADER_SIZE + PROFILE_N_360 * 2  # 7216


@dataclass
class ProfRecord:
    no: int
    internal_request_no: int
    item_no: int
    port_no: int
    sec: int
    error_flag: int
    data_count: int
    data: np.ndarray
    time: Optional[np.ndarray] = None


def u16_le(buf: bytes, off: int) -> int:
    """Read little-endian uint16."""
    return int.from_bytes(buf[off : off + 2], byteorder="little", signed=False)


def first_zero_index(arr: np.ndarray) -> int:
    """Find index of the first 0 occurrence in array, or len(arr) if none."""
    z = np.where(arr == 0)[0]
    if len(z) == 0:
        return len(arr)
    return int(z[0])


def detect_profile_format(
    path: Union[str, Path],
    mode: str = "auto",
) -> Tuple[int, int, int, int, List[Dict[str, Any]]]:
    """
    Detect profile format (3600 or 6000 points) from file size.

    Returns:
        (profile_n, record_size, n_records, file_size, candidates)
    """
    path = Path(path)
    file_size = path.stat().st_size

    if file_size == 0:
        raise ValueError(f"File size is 0: {path}")

    candidates = [
        {
            "mode": "6000",
            "profile_n": PROFILE_N_600,
            "record_size": RECORD_SIZE_600,
            "records": file_size // RECORD_SIZE_600,
            "remainder": file_size % RECORD_SIZE_600,
            "divisible": file_size % RECORD_SIZE_600 == 0,
        },
        {
            "mode": "3600",
            "profile_n": PROFILE_N_360,
            "record_size": RECORD_SIZE_360,
            "records": file_size // RECORD_SIZE_360,
            "remainder": file_size % RECORD_SIZE_360,
            "divisible": file_size % RECORD_SIZE_360 == 0,
        },
    ]

    if mode == "6000":
        profile_n = PROFILE_N_600
        record_size = RECORD_SIZE_600
        if file_size % record_size != 0:
            raise ValueError(
                f"Specified 6000-point mode but file size is not divisible: {file_size} % {record_size} != 0"
            )
    elif mode == "3600":
        profile_n = PROFILE_N_360
        record_size = RECORD_SIZE_360
        if file_size % record_size != 0:
            raise ValueError(
                f"Specified 3600-point mode but file size is not divisible: {file_size} % {record_size} != 0"
            )
    else:
        divisible = [c for c in candidates if c["divisible"]]
        if not divisible:
            msg = [
                f"File size ({file_size}) is not divisible by 6000 or 3600 record sizes.",
                f"6000: rem={candidates[0]['remainder']}, 3600: rem={candidates[1]['remainder']}",
            ]
            raise ValueError("\n".join(msg))
        if any(c["mode"] == "6000" for c in divisible):
            profile_n = PROFILE_N_600
            record_size = RECORD_SIZE_600
        else:
            profile_n = PROFILE_N_360
            record_size = RECORD_SIZE_360

    n_records = file_size // record_size
    return profile_n, record_size, n_records, file_size, candidates


def parse_prof_dat(
    path: Union[str, Path],
    fill: bool = False,
    profile_n: Optional[int] = None,
) -> List[ProfRecord]:
    """
    Parse a Prof .dat binary file into a list of ProfRecord objects.
    """
    path = Path(path)
    if profile_n is None:
        profile_n, _, _, _, _ = detect_profile_format(path)

    raw = path.read_bytes()
    record_size = HEADER_SIZE + profile_n * 2

    if len(raw) == 0:
        raise ValueError("File size is 0.")
    if len(raw) % record_size != 0:
        raise ValueError(
            f"File size ({len(raw)}) not divisible by record size ({record_size})."
        )

    n_records = len(raw) // record_size
    records: List[ProfRecord] = []

    for j in range(n_records):
        base = j * record_size
        rec = raw[base : base + record_size]

        internal_request_no = u16_le(rec, 0)
        item_no = int(rec[2])
        port_no = int(rec[3])
        error_flag = u16_le(rec, 12)
        sec = u16_le(rec, 14)

        prof_bytes = rec[HEADER_SIZE : HEADER_SIZE + profile_n * 2]
        prof = np.frombuffer(prof_bytes, dtype="<u2", count=profile_n).copy()
        zero_idx = first_zero_index(prof)

        if fill and item_no < 31:
            filled = prof.copy()
            if zero_idx < profile_n:
                last = int(filled[zero_idx - 1]) if zero_idx > 0 else 0
                filled[zero_idx:] = last
                data_count = zero_idx
            else:
                data_count = profile_n
            data = filled
        else:
            if zero_idx > 0:
                data = prof[:zero_idx].copy()
                data_count = zero_idx
            else:
                data = np.array([], dtype=np.uint16)
                data_count = 0

        records.append(
            ProfRecord(
                no=j + 1,
                internal_request_no=internal_request_no,
                item_no=item_no,
                port_no=port_no,
                sec=sec,
                error_flag=error_flag,
                data_count=data_count,
                data=data,
            )
        )

    return records


def parse_prof_to_dataframe(
    path: Union[str, Path],
    fill: bool = False,
    profile_n: Optional[int] = None,
) -> pd.DataFrame:
    """
    Parse a Prof .dat file directly into a transposed DataFrame matching
    the layout expected by downstream merging logic.
    Row: metadata and time-series points (0.1, 0.2, ... seconds).
    Column: Each record (Record 1, Record 2, ...).
    """
    records = parse_prof_dat(path, fill=fill, profile_n=profile_n)
    if not records:
        return pd.DataFrame()

    meta_keys = [
        "内部依頼No",
        "項目No",
        "ポートNo",
        "秒",
        "エラーフラグ",
        "データ数",
    ]
    max_len = max((len(r.data) for r in records), default=0)

    rows = []
    # Header metadata rows
    rows.append(["内部依頼No"] + [r.internal_request_no for r in records])
    rows.append(["項目No"] + [r.item_no for r in records])
    rows.append(["ポートNo"] + [r.port_no for r in records])
    rows.append(["秒"] + [r.sec for r in records])
    rows.append(["エラーフラグ"] + [r.error_flag for r in records])
    rows.append(["データ数"] + [r.data_count for r in records])

    # Time point rows (0.1s increments)
    for t_idx in range(max_len):
        time_label = f"{(t_idx + 1) * 0.1:.1f}"
        row_vals = [time_label]
        for r in records:
            if t_idx < len(r.data):
                row_vals.append(r.data[t_idx])
            else:
                row_vals.append(np.nan)
        rows.append(row_vals)

    col_names = ["項目名"] + [f"レコード_{r.no}" for r in records]
    df = pd.DataFrame(rows, columns=col_names)
    return df
