"""Parser for CP3000 LOG*.dat (text event log) into two tables.

The line parser (state machine) is copied from CWA-ML-tool src/cwa/log_parser.py (commit a591105).
Change: instead of writing a "LOG展開後.xlsx" next to the .dat file, ``parse_log_dat`` returns the
two sheets as DataFrames, so the raw-data folder is never written to.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

import pandas as pd

# Sheet names and constants (aligned with instrument VBA logic)
SinfoSheetName = "サンプリング情報"
AnalRunSheetName = "依頼情報"

SinfoTypeSamp = "ｻﾝﾌﾟﾙ"
SinfoTypeDil = "希釈液"
SinfoTypeBuf = "緩衝液"

ColSinfoS = 1
ColSinfoRP1 = 9
ColSinfoRP2 = 16

MAX_SINFO_COLS = 21
ANALRUN_COLS = 7

EVENT_NAMES: List[str] = [
    "分析ｽﾀｰﾄ",
    "分析終了",
    "ｺﾝﾄﾛｰﾙ",
    "ｷｬﾘﾌﾞﾚｰｼｮﾝ",
    "ｻﾝﾌﾟﾙｽﾄｯﾌﾟ",
    "泡抜き",
    "STAT",
    "後処理",
    "前準備",
    "日替わり処理",
    "搬送ｽﾀｰﾄ",
    "搬送ｵﾌﾗｲﾝ",
    "緊急停止",
    "泡抜き・前準備",
]


def safe_int_prefix(s: object, default: int = 0) -> int:
    """Read leading integer similar to VBA Val."""
    if s is None:
        return default
    m = re.match(r"^\s*([+-]?\d+)", str(s))
    return int(m.group(1)) if m else default


def safe_nibble(ch: str, default: int = 0) -> int:
    """Read single hex char as 0-15."""
    if not ch:
        return default
    ch = ch.strip()
    if not ch:
        return default
    try:
        return int(ch, 16)
    except Exception:
        return default


def parse_time(hms: object) -> Optional[dt.time]:
    """Parse 'hh:mm:ss' to dt.time."""
    if hms is None:
        return None
    s = str(hms).strip()
    m = re.match(r"^(\d{1,2}):(\d{2}):(\d{2})$", s)
    if not m:
        return None
    hh, mm, ss = map(int, m.groups())
    if 0 <= hh <= 23 and 0 <= mm <= 59 and 0 <= ss <= 59:
        return dt.time(hh, mm, ss)
    return None


def to_excel_time_or_text(s: str) -> object:
    t = parse_time(s)
    return t if t is not None else s


def split_time_and_body(line: str) -> Optional[Tuple[str, str]]:
    if not line:
        return None
    k = line.find(" ")
    if k != -1 and k > 9:
        k2 = line.find("<")
        if k2 != -1:
            k = k2
    if k == -1 or k < 4:
        return None
    return line[:k], line[k:]


def ensure_row(rows: List[List[object]], row_idx_1based: int, ncols: int) -> None:
    while len(rows) < row_idx_1based:
        rows.append([""] * ncols)


def normalize_display_no(int_dno: int, run_type: str) -> str:
    if int_dno == 0:
        return ""
    if run_type == "Calibration":
        return f"C{int(int_dno):03d}"
    return str(int(int_dno))


def check_sinfo(str_log: str) -> List[int]:
    int_info: List[int] = [0] * 7
    int_info[0] = safe_int_prefix(str_log[:1], 0)
    int_info[1] = safe_int_prefix(str_log[2:3], 0)
    rest = str_log[4:]

    last_has_slash = False
    for i in range(2, 7):
        j = rest.find("/")
        if j == -1:
            int_info[i] = 999
            last_has_slash = False
        else:
            token = rest[:j]
            int_info[i] = safe_int_prefix(token, 0)
            rest = rest[j + 1 :]
            last_has_slash = True

    if int_info[0] <= 3 and int_info[1] >= 8:
        int_info[0] = 4
        for k in range(4, 7):
            int_info[k - 1] = int_info[k]
        int_info[6] = safe_int_prefix(rest, 0)
    else:
        if last_has_slash and rest:
            hi = safe_nibble(rest[:1], 0)
            int_info[6] = int_info[6] + hi * 256

    return int_info


def parse_prefix_rno_tno(body: str) -> Tuple[int, int, str]:
    int_rno = 0
    int_tno = 0
    if body.startswith("<"):
        i = body.find("-", 1)
        if i != -1:
            int_rno = safe_int_prefix(body[1:i], 0)
            body2 = body[i + 1 :]
            j = body2.find(">", 1)
            if j != -1:
                int_tno = safe_int_prefix(body2[:j], 0)
                body2 = body2[j + 1 :]
                return int_rno, int_tno, body2
    return int_rno, int_tno, body


def find_autosaiken_tno(chunk: str) -> int:
    m = re.search(r"AutoSaikenTest\s+.*?\s+(\d+)", chunk)
    return safe_int_prefix(m.group(1), 0) if m else 0


@dataclass
class LogParseState:
    row_sinfo: int = 1
    row_analrun: int = 1
    sinfo_rows: List[List[object]] = None
    anal_rows: List[List[object]] = None
    pending_run_type: Optional[str] = None
    active_run_type: str = "Sample"

    def __post_init__(self) -> None:
        if self.sinfo_rows is None:
            self.sinfo_rows = []
        if self.anal_rows is None:
            self.anal_rows = []


def add_sinfo(state: LogParseState, str_time: str, body: str) -> None:
    int_row = 0
    while body:
        pos = body.find("SInfo")
        if pos == -1:
            break

        if int_row == 0:
            int_row = state.row_sinfo + 1
            state.row_sinfo = int_row

        body = body[pos + 5 :]
        int_info = check_sinfo(body)

        ensure_row(state.sinfo_rows, int_row, MAX_SINFO_COLS)
        tval = to_excel_time_or_text(str_time)

        if int_info[0] <= 3:
            if state.sinfo_rows[int_row - 1][ColSinfoS - 1] != "":
                int_row += 1
                state.row_sinfo = int_row
                ensure_row(state.sinfo_rows, int_row, MAX_SINFO_COLS)

            r = state.sinfo_rows[int_row - 1]
            r[ColSinfoS - 1] = tval

            if int_info[1] == 0:
                r[ColSinfoS] = SinfoTypeSamp
            elif int_info[1] == 1:
                r[ColSinfoS] = SinfoTypeBuf
            else:
                r[ColSinfoS] = SinfoTypeDil

            for i in range(2, 7):
                r[(ColSinfoS - 1) + i] = int_info[i]
        else:
            int_col = ColSinfoRP1 if int_info[5] == 0 else ColSinfoRP2
            r = state.sinfo_rows[int_row - 1]
            r[int_col - 1] = tval
            if int_info[1] in (8, 9):
                r[int_col] = f"R{int_info[1] - 7}"
            else:
                r[int_col] = int_info[1]
            r[int_col + 1] = int_info[2]
            r[int_col + 2] = int_info[3]
            r[int_col + 3] = int_info[4]
            r[int_col + 4] = int_info[6]


def add_event_list(state: LogParseState, str_time: str, body: str) -> None:
    tval = to_excel_time_or_text(str_time)
    for ev in EVENT_NAMES:
        if ev and (ev in body):
            if ev == "ｷｬﾘﾌﾞﾚｰｼｮﾝ":
                state.pending_run_type = "Calibration"
            elif ev == "分析ｽﾀｰﾄ":
                state.active_run_type = state.pending_run_type or "Sample"
                state.pending_run_type = None
            elif ev == "分析終了":
                state.pending_run_type = None
                state.active_run_type = "Sample"

            state.row_analrun += 1
            ensure_row(state.anal_rows, state.row_analrun, ANALRUN_COLS)
            r = state.anal_rows[state.row_analrun - 1]
            r[0] = tval
            r[1] = ev


def add_analrun(state: LogParseState, str_time: str, body: str) -> None:
    int_rno, int_tno, rest = parse_prefix_rno_tno(body)
    tval = to_excel_time_or_text(str_time)

    while rest:
        p = rest.find("AnalRunSet:")
        if p == -1:
            break
        rest = rest[p + 11 :]

        dot = rest.find(".")
        int_dno = 0
        int_type = 0
        if dot != -1:
            int_dno = safe_int_prefix(rest[:dot], 0)
            tail = rest[dot + 1 :].strip()
            int_type = safe_int_prefix(tail.split()[0] if tail else "0", 0)

        if int_rno == 0:
            q = rest.find("IraiUp")
            if q != -1:
                tail = rest[q + 6 :].strip()
                int_rno = safe_int_prefix(tail.split()[0] if tail else "0", 0)

        if int_tno == 0:
            next_p = rest.find("AnalRunSet:")
            chunk = rest if next_p == -1 else rest[:next_p]
            int_tno = find_autosaiken_tno(chunk)

        state.row_analrun += 1
        ensure_row(state.anal_rows, state.row_analrun, ANALRUN_COLS)

        r = state.anal_rows[state.row_analrun - 1]
        r[0] = tval
        r[1] = "Samp" if int_type == 255 else "Data"
        r[2] = "" if int_rno == 0 else int_rno
        r[3] = "" if int_dno == 0 else int_dno
        r[4] = "" if int_tno == 0 else int_tno
        r[5] = state.active_run_type
        r[6] = normalize_display_no(int_dno, state.active_run_type)

        int_tno = 0
        int_rno = 0
        int_dno = 0
        int_type = 0


SINFO_HEADER = [""] * MAX_SINFO_COLS
for _i, _name in enumerate(["ｻﾝﾌﾟﾙ", "ﾀｲﾌﾟ", "内部依頼No", "ﾁｬﾝﾈﾙNo", "ﾗｯｸNo", "ﾎﾟｼﾞｼｮﾝNo", "液面高さ"]):
    SINFO_HEADER[_i] = _name
for _base, _probe in ((ColSinfoRP1, "ﾌﾟﾛｰﾌﾞ1"), (ColSinfoRP2, "ﾌﾟﾛｰﾌﾞ2")):
    for _k, _name in enumerate([_probe, "ﾀｲﾌﾟ", "内部依頼No", "ﾁｬﾝﾈﾙNo", "ﾎﾟｼﾞｼｮﾝNo", "液面高さ"]):
        SINFO_HEADER[_base - 1 + _k] = _name
ANALRUN_HEADER = ["時刻", "ｲﾍﾞﾝﾄ", "内部依頼No", "表示依頼No", "項目No", "測定種別", "表示依頼No_正規化"]


def read_log_lines(dat_path: str | Path) -> Tuple[List[str], str]:
    """Read the LOG text, trying the same encodings as the original parser."""
    dat_path = Path(dat_path)
    for enc in ("cp932", "utf-8", "utf-8-sig", "latin-1"):
        try:
            with dat_path.open("r", encoding=enc, errors="strict") as f:
                return f.read().splitlines(), enc
        except Exception:
            pass
    with dat_path.open("r", encoding="cp932", errors="replace") as f:
        return f.read().splitlines(), "cp932(replace)"


def _rows_to_frame(rows: List[List[object]], header: List[str]) -> pd.DataFrame:
    """Body rows -> DataFrame. Empty cells become NaN, like reading the original Excel sheet."""
    body = [[None if (v == "" or v is None) else v for v in r] for r in rows[1:]]
    body = [r for r in body if any(v is not None for v in r)]
    cols = [h if h else f"col_{i + 1}" for i, h in enumerate(header)]
    seen: dict = {}
    unique = []
    for c in cols:  # duplicate names get .1, .2 like pandas.read_excel
        if c in seen:
            seen[c] += 1
            unique.append(f"{c}.{seen[c]}")
        else:
            seen[c] = 0
            unique.append(c)
    return pd.DataFrame(body, columns=unique)


@dataclass
class LogTables:
    sampling: pd.DataFrame  # "サンプリング情報" sheet
    requests: pd.DataFrame  # "依頼情報" sheet
    encoding: str
    n_lines: int
    n_parsed_lines: int


def parse_log_dat(dat_path: str | Path) -> LogTables:
    """Parse a LOG .dat file into the サンプリング情報 / 依頼情報 tables (nothing is written to disk)."""
    dat_path = Path(dat_path)
    if not dat_path.is_file():
        raise FileNotFoundError(f"LOG .dat file not found: {dat_path}")
    lines, used_enc = read_log_lines(dat_path)

    state = LogParseState()
    state.sinfo_rows = [list(SINFO_HEADER)]
    state.anal_rows = [list(ANALRUN_HEADER)]

    hit = 0
    for line in lines:
        if not line:
            continue
        sp = split_time_and_body(line)
        if sp is None:
            continue
        hit += 1
        str_time, body = sp
        add_event_list(state, str_time, body)
        add_sinfo(state, str_time, body)
        add_analrun(state, str_time, body)

    return LogTables(
        sampling=_rows_to_frame(state.sinfo_rows, SINFO_HEADER),
        requests=_rows_to_frame(state.anal_rows, ANALRUN_HEADER),
        encoding=used_enc,
        n_lines=len(lines),
        n_parsed_lines=hit,
    )
