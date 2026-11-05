"""Load one CP3000 measurement batch: prof*.dat (waveforms) + *CSV_data.csv + LOG*.dat.

The string helpers, ``read_csv_sections``, ``canonicalize_csv_attr_columns`` and
``csv_build_item_master`` are copied verbatim from CWA-ML-tool src/cwa/ingestion/merger.py
(commit a591105). The join is rebuilt for viewing:

* the base table is the prof file (one row per waveform record), so waveforms without a CSV
  match are still listed;
* prof (内部依頼No, 項目番号) -> LOG (内部依頼No, 項目No) -> 表示依頼No -> CSV (依頼No, 項目番号),
  which is the same key path as merger.merge_raw_inputs, read from the other side;
* the LOG file is parsed in memory (no "LOG展開後.xlsx" is written next to the raw data);
* CSV and LOG are optional: with prof only, the waveforms are shown by 内部依頼No / 項目番号;
* with CSV only (no prof), the simplified timecourse in Section 2 (ﾌﾟﾛﾌｧｲﾙ) of the CSV is loaded.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple, Union

import numpy as np
import pandas as pd

from .log import LogTables, parse_log_dat
from .prof import ProfRecord, detect_profile_format, parse_prof_dat
from .signal import TIME_STEP_SEC, Derived, derive_batch, time_axis

MODE_COAGULATION = "凝固項目"
MODE_CHROMOGENIC = "比色項目"
MODE_UNKNOWN = "その他"


def classify_measurement_mode(port_no: Any) -> str:
    """Classify CP3000 measurement mode from photometric port number.

    Port 1-14: Coagulation mode (PT, APTT, Fbg, etc.)
    Port 15-20: Chromogenic / Latex turbidimetric mode (TAT, D-dimer, etc.)
    """
    try:
        p = int(port_no)
    except (ValueError, TypeError):
        return MODE_UNKNOWN
    if 1 <= p <= 14:
        return MODE_COAGULATION
    elif 15 <= p <= 20:
        return MODE_CHROMOGENIC
    return MODE_UNKNOWN


# ---- copied from src/cwa/ingestion/merger.py ------------------------------------------

def clean_path(p: Any) -> str:
    """Strip quotes and whitespace from path input."""
    if p is None:
        return ""
    s = str(p).strip().replace("\u3000", " ")
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ('"', "'"):
        s = s[1:-1].strip()
    return s


def make_unique(cols: Any) -> List[str]:
    """Ensure column names are unique by appending _1, _2 to duplicates."""
    seen: Dict[str, int] = {}
    out: List[str] = []
    for c in cols:
        s = str(c).strip()
        if s in seen:
            seen[s] += 1
            out.append(f"{s}_{seen[s]}")
        else:
            seen[s] = 0
            out.append(s)
    return out


def is_blankish(s: Any) -> bool:
    """Check if string is None, empty, NaN, whitespace, or generated suffix like '_1'."""
    if s is None:
        return True
    st = str(s).strip()
    if st == "" or st.lower() in ("nan", "none", "<na>"):
        return True
    t = st.replace(" ", "")
    if re.fullmatch(r"_+\d+", t):
        return True
    return False


def strip_paren(s: Any) -> str:
    """Remove parentheses and their contents from string."""
    if is_blankish(s):
        return ""
    return re.sub(r"[\(（].*?[\)）]", "", str(s)).strip()


def normalize_item_name(colname: Any) -> str:
    """Normalize item name string (e.g. CWAPTN(sec) -> CWAPTN, LA1(ﾚｼｵ) -> LA1_ratio)."""
    s = str(colname).strip()
    m = re.search(r"[\(（](.*?)[\)）]", s)
    base = strip_paren(s)
    if m:
        inside = m.group(1)
        if ("ﾚｼｵ" in inside) or ("レシオ" in inside) or ("比" in inside) or ("ratio" in inside.lower()):
            return f"{base}_ratio"
    return base


def norm_reqno(x: Any) -> str:
    """Normalize request number (0001, 1, 1.0, Q001, etc.)."""
    if is_blankish(x):
        return ""
    s = str(x).strip()
    # If float string like '1.0', remove decimal part
    if re.match(r"^\d+\.0+$", s):
        s = s.split(".")[0]
    # If numeric string, format with leading zeros or standardize
    m_c = re.match(r"^[cC](\d+)$", s)
    if m_c:
        return f"C{int(m_c.group(1)):03d}"
    m_q = re.match(r"^[qQ](\d+)$", s)
    if m_q:
        return f"Q{int(m_q.group(1)):03d}"
    if s.isdigit():
        return f"{int(s):04d}"
    return s


def to_q(v: Any) -> str:
    """Convert integer/float rack index to Q-notation (e.g. 1 -> Q001)."""
    try:
        val = int(float(v))
        return f"Q{val:03d}"
    except Exception:
        return str(v).strip()


def pick_series(obj: Any) -> pd.Series:
    """Safely return a 1D pd.Series from either Series or DataFrame column slice."""
    if isinstance(obj, pd.DataFrame):
        return obj.iloc[:, 0]
    return obj


def read_csv_sections(
    csv_path: Union[str, Path],
    encoding: str = "cp932",
) -> Tuple[List[str], pd.DataFrame, List[str], pd.DataFrame]:
    """
    Split blood analyzer raw CSV into Header1/Body1 (sample attributes)
    and Header2/Body2 (item measurement definitions).
    Handles null-byte sanitization.
    """
    raw_bytes = Path(csv_path).read_bytes().replace(b"\x00", b"")
    text = raw_bytes.decode(encoding, errors="replace")
    lines = [line.strip("\r\n") for line in text.splitlines()]

    reader = csv.reader(lines)
    rows = list(reader)
    idx = [i for i, r in enumerate(rows) if r and str(r[0]).strip() in ("依頼No.", "依頼No")]
    if len(idx) < 2:
        raise ValueError("CSV内に '依頼No.' が2回見つかりませんでした。CSV形式を確認してください。")

    i1, i2 = idx[0], idx[1]
    h1 = make_unique(rows[i1])
    b1 = [r for r in rows[i1 + 1 : i2] if any(str(x).strip() != "" for x in r)]
    h2 = rows[i2]
    b2 = rows[i2 + 1 :]

    return h1, b1, h2, b2


def canonicalize_csv_attr_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize CSV attribute header variations (SID vs PID, barcode variants)."""
    rename = {}
    cols = list(df.columns)

    # SID / PID handling
    if "SID" not in cols:
        pid_cols = [c for c in cols if str(c).strip().upper() == "PID"]
        if pid_cols:
            rename[pid_cols[0]] = "SID"

    # Barcode column handling
    if "検体ﾊﾞｰｺｰﾄﾞ" not in cols:
        barcode_candidates = [
            c
            for c in cols
            if str(c).strip()
            in [
                "検体ﾊﾞｰｺｰﾄﾞ",
                "検体バーコード",
                "ﾊﾞｰｺｰﾄﾞ",
                "バーコード",
                "検体Barcode",
                "Barcode",
                "BARCODE",
            ]
        ]
        if barcode_candidates:
            rename[barcode_candidates[0]] = "検体ﾊﾞｰｺｰﾄﾞ"
        else:
            df["検体ﾊﾞｰｺｰﾄﾞ"] = ""

    if rename:
        df = df.rename(columns=rename)
    return df


def csv_build_item_master(body2: Any) -> pd.DataFrame:
    """Build item master table from Section 2 of CSV (依頼No., 項目名, 項目番号, ...)."""
    if isinstance(body2, list):
        clean = [r for r in body2 if any(str(x).strip() != "" for x in r)]
        rows = []
        for r in clean:
            if len(r) < 3:
                continue
            reqno = str(r[0]).strip()
            itemname = str(r[1]).strip()
            itemno = str(r[2]).strip()
            if reqno != "" and itemname != "" and re.fullmatch(r"\d+", itemno):
                rows.append((itemname, int(itemno)))
        return pd.DataFrame(rows, columns=["項目名", "項目番号"]).drop_duplicates("項目名")
    elif isinstance(body2, pd.DataFrame):
        if body2.empty:
            return pd.DataFrame(columns=["項目名", "項目番号"])
        return csv_build_item_master(body2.values.tolist())
    return pd.DataFrame(columns=["項目名", "項目番号"])


# ---- files in a folder --------------------------------------------------------------

def _visible_files(folder: Path) -> List[Path]:
    return [p for p in folder.iterdir()
            if p.is_file() and not p.name.startswith("~$") and not p.name.startswith(".")]


@dataclass
class BatchFiles:
    """Candidate raw files found in one folder (lists, because a folder may hold several)."""

    folder: Path
    prof: List[Path]
    csv: List[Path]
    log: List[Path]

    @property
    def ok(self) -> bool:
        return bool(self.prof or self.csv)


def find_batch_files(folder: Union[str, Path]) -> BatchFiles:
    """Find prof*.dat, LOG*.dat and *.csv in a folder (same name tokens as merger.detect_in_folder)."""
    f = Path(clean_path(folder))
    if not f.is_dir():
        raise FileNotFoundError(f"フォルダが見つかりません: {f}")
    files = _visible_files(f)
    prof = sorted(p for p in files if "prof" in p.name.lower() and p.suffix.lower() == ".dat")
    log = sorted(p for p in files if "log" in p.name.lower() and p.suffix.lower() == ".dat")
    csvs = [p for p in files if p.suffix.lower() == ".csv"]
    # the device CSV is "*CSV_data.csv"; put it first when other CSV files are present
    csvs = sorted(csvs, key=lambda p: (0 if "csv_data" in p.name.lower() else 1, p.name))
    return BatchFiles(folder=f, prof=prof, csv=csvs, log=log)


def _has_prof_file(folder: Path) -> bool:
    try:
        return any(
            p.is_file() and not p.name.startswith(("~$", "."))
            and "prof" in p.name.lower() and p.suffix.lower() == ".dat"
            for p in folder.iterdir()
        )
    except (PermissionError, OSError):
        return False


def find_batch_folders(root: Union[str, Path], max_depth: int = 3) -> List[Path]:
    """Folders under ``root`` (including itself) that contain prof*.dat or *.csv, prof folders first."""
    root = Path(clean_path(root))
    if not root.is_dir():
        return []
    found: List[Path] = []

    def walk(d: Path, depth: int) -> None:
        try:
            entries = list(d.iterdir())
        except (PermissionError, OSError):
            return
        visible = [p for p in entries if p.is_file() and not p.name.startswith(("~$", "."))]
        has_prof = any("prof" in p.name.lower() and p.suffix.lower() == ".dat" for p in visible)
        has_csv = any(p.suffix.lower() == ".csv" for p in visible)
        if has_prof or has_csv:
            found.append(d)
        if depth >= max_depth:
            return
        for p in sorted(entries):
            if p.is_dir() and not p.name.startswith((".", "_", "~")):
                walk(p, depth + 1)

    walk(root, 0)
    return sorted(
        found,
        key=lambda p: (1 if _has_prof_file(p) else 0, str(p.relative_to(root)) if p != root else ""),
        reverse=True,
    )


# ---- CSV ------------------------------------------------------------------------------

CSV_META_COLS = ["依頼No.", "SID", "検体ﾊﾞｰｺｰﾄﾞ", "測定日", "属性"]


def _first_item_index(cols: List[str]) -> int:
    """Without a 属性 column: the first column that looks like an item (unit in brackets, or a
    blank D-flag column right after it)."""
    for i in range(1, len(cols)):
        c = cols[i]
        if is_blankish(c):
            continue
        has_unit = bool(re.search(r"[\(（].*?[\)）]", c))
        flag_next = i + 1 < len(cols) and is_blankish(cols[i + 1])
        if has_unit or flag_next:
            return i
    return len(cols)


def csv_attributes_and_items(header1: List[str], body1: List[List[str]]) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Section 1 of the device CSV -> (attributes per 依頼No, long table of item values).

    With a 属性 column, the item / D-flag pairing is the one of merger.csv_attr_wide_to_long.
    Files without 属性 / 測定日 (e.g. the repo's mock data) are accepted: the attribute columns are
    then the columns left of the first item column. Extra attribute columns (検体名, 受付日時, ...)
    are kept.
    """
    padded_rows = [r[:len(header1)] + [""] * max(0, len(header1) - len(r)) for r in body1]
    df = pd.DataFrame(padded_rows, columns=header1)
    df = canonicalize_csv_attr_columns(df)
    if "依頼No." not in df.columns:
        raise ValueError(f"CSV の属性部に 依頼No. 列がありません。列={df.columns.tolist()}")

    cols = list(df.columns)
    if "属性" in cols:
        attr_i = cols.index("属性")
        df["属性"] = df["属性"].astype(str).replace("nan", "").replace("None", "").str.strip()
        df.loc[df["属性"] == "", "属性"] = "blank"
        first_item = attr_i + 1
    else:
        first_item = _first_item_index(cols)
    attr_cols = [c for c in cols[:first_item] if not is_blankish(c)]
    attr_cols += [c for c in CSV_META_COLS if c in cols and c not in attr_cols]
    right = [c for c in cols[first_item:] if c not in CSV_META_COLS]

    for c in attr_cols:
        df[c] = df[c].astype(str).replace("nan", "").replace("None", "").str.strip()

    pairs = []
    i = 0
    while i < len(right):
        val_col = right[i]
        if is_blankish(val_col):
            i += 1
            continue
        base = strip_paren(val_col)
        if is_blankish(base):
            i += 1
            continue
        d_col = None
        if i + 1 < len(right) and is_blankish(right[i + 1]):
            d_col = right[i + 1]
            i += 2
        else:
            i += 1
        pairs.append((val_col, d_col))

    attrs = df[attr_cols].copy()
    attrs.insert(0, "依頼No_norm", attrs["依頼No."].map(norm_reqno))

    parts = []
    for val_col, d_col in pairs:
        part = pd.DataFrame({"依頼No_norm": attrs["依頼No_norm"]})
        part["項目名"] = normalize_item_name(val_col)
        part["測定値"] = df[val_col].astype(str).replace("nan", "").replace("None", "").str.strip()
        if d_col is not None:
            part["Dフラグ"] = df[d_col].astype(str).replace("nan", "").replace("None", "").str.strip()
        else:
            part["Dフラグ"] = ""
        parts.append(part[part["測定値"] != ""])
    items = (pd.concat(parts, ignore_index=True) if parts
             else pd.DataFrame(columns=["依頼No_norm", "項目名", "測定値", "Dフラグ"]))
    return attrs, items


@dataclass
class CsvProfile:
    """One simplified timecourse profile from Section 2 (ﾌﾟﾛﾌｧｲﾙ) of a CP3000 CSV."""

    no: int
    req_no_raw: str
    req_no_norm: str
    item_name: str
    item_no: int
    port_no: int
    process_val: str
    process_flag: str
    time: np.ndarray
    data: np.ndarray


def csv_parse_profiles(header2: Sequence[Any], body2: Any) -> List[CsvProfile]:
    """Parse simplified timecourse profiles from Section 2 of the device CSV.

    Supports both:
    * Standard 2-row CP3000 CSV format: row ``i`` holds ``(依頼No., 項目名, 項目番号, 測光ﾎﾟｰﾄ,
      処理値, フラグ, t_0, t_1, ...)`` and row ``i + 1`` (with blank ``依頼No.``) holds the
      corresponding absorbance change values ``v_0, v_1, ...``. Each measurement record keeps its
      own time axis ``t_0, t_1, ...`` (which varies with measurement mode / interval).
    * Single-row format where ``header2[prof_col:]`` holds numeric time points and each row holds values.
    """
    if isinstance(body2, pd.DataFrame):
        rows = body2.values.tolist() if not body2.empty else []
    elif isinstance(body2, list):
        rows = body2
    else:
        return []

    clean = [r for r in rows if any(str(x).strip() != "" for x in r)]
    prof_col = 6
    for i, cell in enumerate(header2):
        s = str(cell).strip()
        if s in ("ﾌﾟﾛﾌｧｲﾙ", "プロファイル"):
            prof_col = i
            break

    header_times: List[float] = []
    for cell in list(header2)[prof_col:]:
        s = str(cell).strip()
        if s == "":
            break
        try:
            header_times.append(float(s))
        except ValueError:
            header_times = []
            break

    profiles: List[CsvProfile] = []
    idx = 0
    while idx < len(clean):
        r = clean[idx]
        if len(r) < 3:
            idx += 1
            continue
        req_raw = str(r[0]).strip()
        item_name = str(r[1]).strip()
        item_no_str = str(r[2]).strip()
        if not (req_raw != "" and item_name != "" and re.fullmatch(r"\d+", item_no_str)):
            idx += 1
            continue
        item_no = int(item_no_str)
        port_str = str(r[3]).strip() if len(r) > 3 else ""
        port_no = int(port_str) if re.fullmatch(r"\d+", port_str) else 0
        proc_val = str(r[4]).strip() if len(r) > 4 else ""
        proc_flag = str(r[5]).strip() if len(r) > 5 else ""

        t_vals: List[float] = []
        v_vals: List[float] = []

        if idx + 1 < len(clean) and str(clean[idx + 1][0]).strip() == "":
            r_val = clean[idx + 1]
            col_end = prof_col
            for c_idx in range(prof_col, len(r)):
                s = str(r[c_idx]).strip()
                if s == "":
                    break
                try:
                    t_vals.append(float(s))
                    col_end = c_idx + 1
                except ValueError:
                    break
            for c_idx in range(prof_col, col_end):
                s = str(r_val[c_idx]).strip() if c_idx < len(r_val) else ""
                try:
                    v_vals.append(float(s))
                except ValueError:
                    v_vals.append(np.nan)
            idx += 2
        elif header_times and len(r) > prof_col:
            for c_idx, t_pt in enumerate(header_times, start=prof_col):
                if c_idx >= len(r):
                    break
                s = str(r[c_idx]).strip()
                if s == "":
                    break
                try:
                    v_vals.append(float(s))
                    t_vals.append(t_pt)
                except ValueError:
                    break
            idx += 1
        else:
            idx += 1

        if t_vals and v_vals:
            profiles.append(
                CsvProfile(
                    no=len(profiles) + 1,
                    req_no_raw=req_raw,
                    req_no_norm=norm_reqno(req_raw),
                    item_name=item_name,
                    item_no=item_no,
                    port_no=port_no,
                    process_val=proc_val,
                    process_flag=proc_flag,
                    time=np.asarray(t_vals, dtype=float),
                    data=np.asarray(v_vals, dtype=float),
                )
            )

    return profiles


@dataclass
class CsvTables:
    attributes: pd.DataFrame   # one row per 依頼No (依頼No_norm + attribute columns)
    items: pd.DataFrame        # 依頼No_norm, 項目名, 測定値, Dフラグ, 項目番号
    item_master: pd.DataFrame  # 項目名, 項目番号 (section 2)
    profiles: List[CsvProfile] = field(default_factory=list)


def read_device_csv(csv_path: Union[str, Path], encoding: str = "cp932") -> CsvTables:
    header1, body1, header2, body2 = read_csv_sections(csv_path, encoding=encoding)
    attrs, items = csv_attributes_and_items(header1, body1)
    item_master = csv_build_item_master(body2)
    profiles = csv_parse_profiles(header2, body2)
    item_map = dict(zip(item_master["項目名"], item_master["項目番号"]))
    items["項目番号"] = items["項目名"].map(item_map)
    miss = items["項目番号"].isna()
    if miss.any():  # "LA1_ratio" -> item number of "LA1" (as in merger)
        items.loc[miss, "項目番号"] = items.loc[miss, "項目名"].str.replace("_ratio", "", regex=False).map(item_map)
    items["項目番号"] = pd.to_numeric(items["項目番号"], errors="coerce").astype("Int64")
    return CsvTables(attributes=attrs, items=items, item_master=item_master, profiles=profiles)


# ---- LOG ------------------------------------------------------------------------------

def log_request_key(tables: LogTables) -> pd.DataFrame:
    """(内部依頼No, 項目No) -> 表示依頼No_norm, 測定種別. Same rules as merger.read_log_key."""
    req = tables.requests.copy()
    samp = tables.sampling.copy()

    req_cols = {}
    for c in req.columns:
        s = str(c).strip()
        if "ｲﾍﾞﾝﾄ" in s or s == "イベント":
            req_cols[c] = "イベント"
        elif "内部依頼" in s:
            req_cols[c] = "内部依頼No"
        elif "表示依頼No_正規化" in s:
            req_cols[c] = "表示依頼No_正規化"
        elif "表示依頼" in s or s == "依頼No.":
            req_cols[c] = "表示依頼No"
        elif "項目" in s:
            req_cols[c] = "項目No"
        elif "測定種別" in s:
            req_cols[c] = "測定種別"
    req = req.rename(columns=req_cols)
    req = req.loc[:, ~req.columns.duplicated()].copy()
    for need in ["イベント", "内部依頼No", "表示依頼No", "項目No"]:
        if need not in req.columns:
            raise ValueError(f"LOG 依頼情報に必要な列がありません: {need}")

    ev = pick_series(req["イベント"]).astype(str)
    req_samp = req[ev.str.contains("Samp", na=False)].copy()

    samp_cols = {}
    for c in samp.columns:
        s = str(c).strip()
        if "ﾀｲﾌﾟ" in s or "タイプ" in s:
            samp_cols[c] = "ﾀｲﾌﾟ"
        elif "内部依頼" in s:
            samp_cols[c] = "内部依頼No"
        elif "ﾗｯｸ" in s:
            samp_cols[c] = "ﾗｯｸNo"
        elif "液面高さ" in s:
            samp_cols[c] = "液面高さ"
    samp = samp.rename(columns=samp_cols)
    samp = samp.loc[:, ~samp.columns.duplicated()].copy()

    if "ﾀｲﾌﾟ" in samp.columns and "内部依頼No" in samp.columns:
        typ = pick_series(samp["ﾀｲﾌﾟ"]).astype(str)
        mask_sample = typ.str.contains("ｻﾝﾌﾟﾙ", na=False)
        if "液面高さ" in samp.columns:
            height = pd.to_numeric(pick_series(samp["液面高さ"]), errors="coerce").fillna(0)
            samp_only = samp[mask_sample & (height > 0)].copy()
        else:
            samp_only = samp[mask_sample].copy()
    else:
        samp_only = pd.DataFrame(columns=["内部依頼No"])

    if "ﾗｯｸNo" in samp_only.columns and len(samp_only):
        rack_map = samp_only[["内部依頼No", "ﾗｯｸNo"]].dropna().drop_duplicates("内部依頼No")
        req_samp = req_samp.merge(rack_map, on="内部依頼No", how="left")
    else:
        req_samp["ﾗｯｸNo"] = None

    if "表示依頼No_正規化" in req_samp.columns:
        req_samp["表示依頼No_norm"] = req_samp["表示依頼No_正規化"].astype(object).map(norm_reqno)
    else:
        req_samp["表示依頼No_norm"] = req_samp["表示依頼No"].astype(object).map(norm_reqno)
        is_rack_45 = req_samp["ﾗｯｸNo"].astype(str).str.strip().str.fullmatch(r"45(?:\.0+)?", na=False)
        req_samp.loc[is_rack_45, "表示依頼No_norm"] = req_samp.loc[is_rack_45, "表示依頼No"].map(to_q)

    req_samp["内部依頼No"] = pd.to_numeric(req_samp["内部依頼No"], errors="coerce").astype("Int64")
    req_samp["項目No"] = pd.to_numeric(req_samp["項目No"], errors="coerce").astype("Int64")
    keep_cols = ["内部依頼No", "表示依頼No_norm", "項目No", "ﾗｯｸNo"]
    if "測定種別" in req_samp.columns:
        keep_cols.append("測定種別")
    key = req_samp[keep_cols].copy()
    key["表示依頼No_norm"] = key["表示依頼No_norm"].replace("", np.nan)
    return key.dropna(subset=["内部依頼No", "表示依頼No_norm", "項目No"]).drop_duplicates()


# ---- batch ----------------------------------------------------------------------------

@dataclass
class Batch:
    """One measurement batch: prof (or CSV profile) records plus a table with one row per record."""

    name: str
    prof_path: Optional[Path]
    csv_path: Optional[Path]
    log_path: Optional[Path]
    profile_n: int
    records: List[ProfRecord]
    table: pd.DataFrame
    csv: Optional[CsvTables] = None
    log_key: Optional[pd.DataFrame] = None
    log_info: Dict[str, Any] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    time_points: Optional[np.ndarray] = None

    @property
    def modes(self) -> List[str]:
        """Unique measurement modes present in this batch."""
        if "測定モード" in self.table.columns:
            return [m for m in [MODE_COAGULATION, MODE_CHROMOGENIC, MODE_UNKNOWN]
                    if (self.table["測定モード"] == m).any()]
        return []

    def record_time(self, pos: int) -> np.ndarray:
        """Time axis (in seconds) of the record at ``pos``."""
        r = self.records[int(pos)]
        if r.time is not None and len(r.time):
            return r.time.astype(float, copy=True)
        if self.time_points is not None and len(self.time_points) >= len(r.data):
            return self.time_points[: len(r.data)].astype(float, copy=True)
        return time_axis(len(r.data))

    def time_step_summary(self) -> str:
        """Human-readable summary of time interval(s) across records (e.g. '2.8秒間隔' or '1.4〜4.8秒間隔')."""
        if self.prof_path is not None:
            return f"{TIME_STEP_SEC:g}秒間隔"
        steps: List[float] = []
        for r in self.records:
            t = r.time if (r.time is not None and len(r.time) > 1) else self.time_points
            if t is not None and len(t) > 1:
                steps.append(round(float(np.median(np.diff(t))), 3))
        if not steps:
            return f"{TIME_STEP_SEC:g}秒間隔"
        lo, hi = min(steps), max(steps)
        if abs(hi - lo) < 1e-6:
            return f"{lo:g}秒間隔"
        return f"{lo:g}〜{hi:g}秒間隔"

    def profile_n_summary(self) -> str:
        """Human-readable summary of points per record."""
        if self.prof_path is not None or not self.records:
            return f"{self.profile_n} 点/レコード"
        counts = [len(r.data) for r in self.records if len(r.data) > 0]
        if not counts:
            return f"{self.profile_n} 点/レコード"
        lo, hi = min(counts), max(counts)
        if lo == hi:
            return f"{lo} 点/レコード"
        return f"{lo}〜{hi} 点/レコード"

    def matrix(self, positions: Sequence[int]) -> Tuple[np.ndarray, np.ndarray]:
        """Raw waveforms of the given record positions, padded with NaN to the longest one."""
        recs = [self.records[int(i)] for i in positions]
        n = max((len(r.data) for r in recs), default=0)
        out = np.full((len(recs), n), np.nan)
        for k, r in enumerate(recs):
            out[k, : len(r.data)] = r.data.astype(float)
        if recs:
            longest_rec = max(recs, key=lambda r: len(r.time) if r.time is not None else 0)
            if longest_rec.time is not None and len(longest_rec.time) == n:
                return longest_rec.time.astype(float, copy=True), out
        if self.time_points is not None:
            if n <= len(self.time_points):
                return self.time_points[:n].copy(), out
            dt = float(np.median(np.diff(self.time_points))) if len(self.time_points) > 1 else TIME_STEP_SEC
            extra = self.time_points[-1] + dt * np.arange(1, n - len(self.time_points) + 1)
            return np.r_[self.time_points, np.round(extra, 1)], out
        return time_axis(n), out

    def derive(
        self,
        positions: Sequence[int],
        *,
        window_end_sec: Optional[float] = None,
        coag_ratio: float = 0.5,
        do_trim: bool = False,
    ) -> Derived:
        """Derive waveforms and Te/Tc for ``positions``, honoring each record's own time axis."""
        pos_list = [int(p) for p in positions]
        is_csv = self.prof_path is None
        if not pos_list:
            return derive_batch(
                np.empty((0, 0)),
                np.empty(0),
                window_end_sec=window_end_sec,
                coag_ratio=coag_ratio,
                do_trim=do_trim,
                is_csv_profile=is_csv,
            )

        rec_times = [self.record_time(p) for p in pos_list]
        t_longest = max(rec_times, key=len)
        same_grid = all(
            len(tk) == 0 or np.allclose(tk, t_longest[: len(tk)], atol=1e-6)
            for tk in rec_times
        )
        if same_grid:
            t, m = self.matrix(pos_list)
            d = derive_batch(
                m,
                t,
                window_end_sec=window_end_sec,
                coag_ratio=coag_ratio,
                do_trim=do_trim,
                is_csv_profile=is_csv,
            )
            if any(len(tk) != len(t_longest) for tk in rec_times):
                max_t = float(d.time[-1]) if len(d.time) else np.inf
                d.times = [tk[tk <= max_t + 1e-9] for tk in rec_times]
            return d

        groups: Dict[Tuple[float, ...], List[int]] = {}
        for k, tk in enumerate(rec_times):
            sig_key = tuple(np.round(tk, 4).tolist())
            groups.setdefault(sig_key, []).append(k)

        group_derived: List[Tuple[List[int], Derived]] = []
        for ks in groups.values():
            sub_pos = [pos_list[k] for k in ks]
            t_sub, m_sub = self.matrix(sub_pos)
            d_sub = derive_batch(
                m_sub,
                t_sub,
                window_end_sec=window_end_sec,
                coag_ratio=coag_ratio,
                do_trim=do_trim,
                is_csv_profile=is_csv,
            )
            group_derived.append((ks, d_sub))

        n_rows = len(pos_list)
        max_cols = max((d_sub.raw.shape[1] for _, d_sub in group_derived), default=0)
        raw = np.full((n_rows, max_cols), np.nan)
        cumulative = np.full((n_rows, max_cols), np.nan)
        scaled = np.full((n_rows, max_cols), np.nan)
        endpoint_scaled = np.full((n_rows, max_cols), np.nan)
        slope = np.full((n_rows, max_cols), np.nan)
        acceleration = np.full((n_rows, max_cols), np.nan)
        abs_slope = np.full((n_rows, max_cols), np.nan)
        times_out: List[np.ndarray] = [np.empty(0, dtype=float) for _ in range(n_rows)]
        tetc_rows: List[Optional[pd.Series]] = [None] * n_rows

        for ks, d_sub in group_derived:
            c = d_sub.raw.shape[1]
            for local_i, k in enumerate(ks):
                raw[k, :c] = d_sub.raw[local_i]
                cumulative[k, :c] = d_sub.cumulative[local_i]
                scaled[k, :c] = d_sub.scaled[local_i]
                endpoint_scaled[k, :c] = d_sub.endpoint_scaled[local_i]
                slope[k, :c] = d_sub.slope[local_i]
                acceleration[k, :c] = d_sub.acceleration[local_i]
                if d_sub.abs_slope is not None:
                    abs_slope[k, :c] = d_sub.abs_slope[local_i]
                times_out[k] = d_sub.time.copy()
                tetc_rows[k] = d_sub.tetc.iloc[local_i]

        tetc_df = pd.DataFrame(tetc_rows).reset_index(drop=True)
        rep_time = max(times_out, key=len).copy() if times_out else np.empty(0, dtype=float)
        return Derived(
            time=rep_time,
            raw=raw,
            cumulative=cumulative,
            scaled=scaled,
            endpoint_scaled=endpoint_scaled,
            slope=slope,
            acceleration=acceleration,
            tetc=tetc_df,
            times=times_out,
            abs_slope=abs_slope,
        )


def _first_non_ratio(items: pd.DataFrame) -> pd.DataFrame:
    base = items[~items["項目名"].str.endswith("_ratio")]
    return base.dropna(subset=["項目番号"]).drop_duplicates(["依頼No_norm", "項目番号"], keep="first")


def _load_csv_only_batch(
    csv_path: Path,
    *,
    csv_encoding: str = "cp932",
    name: Optional[str] = None,
) -> Batch:
    """Build a Batch directly from Section 1 + Section 2 (ﾌﾟﾛﾌｧｲﾙ) of a CP3000 CSV file."""
    warnings: List[str] = []
    csv_tables = read_device_csv(csv_path, encoding=csv_encoding)
    profiles = csv_tables.profiles
    if not profiles:
        raise ValueError("CSV 内にプロファイル(タイムコース)データが含まれていません。")

    records: List[ProfRecord] = []
    for p in profiles:
        sec = int(round(float(p.time[-1]))) if len(p.time) else 0
        records.append(
            ProfRecord(
                no=p.no,
                internal_request_no=0,
                item_no=p.item_no,
                port_no=p.port_no,
                sec=sec,
                error_flag=0,
                data_count=len(p.data),
                data=p.data.copy(),
                time=p.time.copy(),
            )
        )

    longest_time = max((p.time for p in profiles), key=len)
    time_points = longest_time.copy()
    profile_n = len(time_points)

    table = pd.DataFrame({
        "No": [p.no for p in profiles],
        "依頼No": [p.req_no_norm for p in profiles],
        "項目番号": pd.array([p.item_no for p in profiles], dtype="Int64"),
        "項目名": [p.item_name for p in profiles],
        "測定モード": [classify_measurement_mode(p.port_no) for p in profiles],
        "ポートNo": [p.port_no for p in profiles],
        "処理値": [p.process_val for p in profiles],
        "秒": [int(round(float(p.time[-1]))) if len(p.time) else 0 for p in profiles],
        "エラーフラグ": [0 for _ in profiles],
        "データ数": [len(p.data) for p in profiles],
        "時間間隔(秒)": [round(float(np.median(np.diff(p.time))), 2) if len(p.time) > 1 else 0.0 for p in profiles],
        "測定時間(秒)": [round(float(p.time[-1]), 1) if len(p.time) else 0.0 for p in profiles],
    })
    dup = table.duplicated(["依頼No", "項目番号"], keep=False)
    table["重複"] = dup
    table["再測定"] = dup
    if dup.any():
        warnings.append(f"CSV 内で 依頼No・項目番号 が重複するプロファイルが {int(dup.sum())} 件あります(すべて一覧に残しています)。")

    attrs = csv_tables.attributes
    n_dup = int(attrs.duplicated("依頼No_norm").sum())
    if n_dup:
        warnings.append(f"CSV で同じ依頼No が {n_dup} 行重複しています(先頭の行を使いました)。")
    attrs = attrs.drop_duplicates("依頼No_norm", keep="first").drop(columns=["依頼No."])
    items = csv_tables.items
    base = _first_non_ratio(items)[["依頼No_norm", "項目番号", "測定値", "Dフラグ"]]
    ratio = (items[items["項目名"].str.endswith("_ratio")].dropna(subset=["項目番号"])
             .drop_duplicates(["依頼No_norm", "項目番号"])[["依頼No_norm", "項目番号", "測定値"]]
             .rename(columns={"測定値": "比"}))
    table = table.merge(attrs, left_on="依頼No", right_on="依頼No_norm", how="left").drop(columns=["依頼No_norm"])
    table = table.merge(base, left_on=["依頼No", "項目番号"], right_on=["依頼No_norm", "項目番号"], how="left")
    table = table.drop(columns=["依頼No_norm"])
    if len(ratio):
        table = table.merge(ratio, left_on=["依頼No", "項目番号"], right_on=["依頼No_norm", "項目番号"], how="left")
        table = table.drop(columns=["依頼No_norm"])
    table["CSV対応"] = table["測定値"].notna()

    first = ["No", "依頼No", "内部依頼No", "項目番号", "項目名", "測定モード", "測定値", "処理値", "Dフラグ", "比"]
    attr_cols = [c for c in csv_tables.attributes.columns
                 if c not in ("依頼No_norm", "依頼No.") and c in table.columns]
    rest = ["測定種別", "ﾗｯｸNo", "ポートNo", "秒", "エラーフラグ", "データ数", "時間間隔(秒)", "測定時間(秒)", "重複", "再測定", "CSV対応"]
    order = [c for c in first if c in table.columns] + attr_cols + [c for c in rest if c in table.columns]
    order += [c for c in table.columns if c not in order]
    table = table[order].reset_index(drop=True)

    return Batch(
        name=name or csv_path.stem,
        prof_path=None,
        csv_path=csv_path,
        log_path=None,
        profile_n=profile_n,
        records=records,
        table=table,
        csv=csv_tables,
        log_key=None,
        log_info={},
        warnings=warnings,
        time_points=time_points,
    )


def load_batch(
    prof_path: Optional[Union[str, Path]] = None,
    csv_path: Optional[Union[str, Path]] = None,
    log_path: Optional[Union[str, Path]] = None,
    *,
    profile_mode: str = "auto",
    csv_encoding: str = "cp932",
    name: Optional[str] = None,
) -> Batch:
    """Read the prof file and, when given, the CSV and LOG files, and join them per waveform.

    When ``prof_path`` is None (or a ``.csv`` file with ``csv_path=None``), loads the simplified
    timecourse profiles from Section 2 of ``csv_path``.
    """
    if prof_path is not None and csv_path is None and Path(prof_path).suffix.lower() == ".csv":
        csv_path = prof_path
        prof_path = None

    if prof_path is None:
        if csv_path is None:
            raise ValueError("prof ファイルまたは CSV ファイルのいずれかを指定してください。")
        return _load_csv_only_batch(Path(csv_path), csv_encoding=csv_encoding, name=name)

    prof_path = Path(prof_path)
    warnings: List[str] = []
    profile_n, _, _, _, _ = detect_profile_format(prof_path, mode=profile_mode)
    records = parse_prof_dat(prof_path, profile_n=profile_n)

    table = pd.DataFrame({
        "No": [r.no for r in records],
        "内部依頼No": pd.array([r.internal_request_no for r in records], dtype="Int64"),
        "項目番号": pd.array([r.item_no for r in records], dtype="Int64"),
        "測定モード": [classify_measurement_mode(r.port_no) for r in records],
        "ポートNo": [r.port_no for r in records],
        "秒": [r.sec for r in records],
        "エラーフラグ": [r.error_flag for r in records],
        "データ数": [r.data_count for r in records],
    })
    table["測定時間(秒)"] = (table["データ数"] * TIME_STEP_SEC).round(1)
    dup = table.duplicated(["内部依頼No", "項目番号"], keep=False)
    table["重複"] = dup
    if dup.any():
        warnings.append(f"prof 内で 内部依頼No・項目番号 が重複する波形が {int(dup.sum())} 件あります(すべて一覧に残しています)。")
    n_empty = int((table["データ数"] == 0).sum())
    if n_empty:
        warnings.append(f"データ数 0 の波形が {n_empty} 件あります。")

    log_key = None
    log_info: Dict[str, Any] = {}
    if log_path is not None:
        tables = parse_log_dat(log_path)
        log_info = {"encoding": tables.encoding, "lines": tables.n_lines, "parsed_lines": tables.n_parsed_lines}
        log_key = log_request_key(tables)
        k = log_key.drop_duplicates(["内部依頼No", "項目No"], keep="first")
        if len(k) < len(log_key):
            warnings.append(f"LOG で 内部依頼No・項目No に複数の表示依頼No があり、先頭を使いました({len(log_key) - len(k)} 件)。")
        cols = ["内部依頼No", "項目No", "表示依頼No_norm", "ﾗｯｸNo"] + (["測定種別"] if "測定種別" in k.columns else [])
        table = table.merge(k[cols], left_on=["内部依頼No", "項目番号"], right_on=["内部依頼No", "項目No"], how="left")
        table = table.drop(columns=["項目No"]).rename(columns={"表示依頼No_norm": "依頼No"})
        n_miss = int(table["依頼No"].isna().sum())
        if n_miss:
            warnings.append(f"LOG で表示依頼No が見つからない波形が {n_miss} 件あります。")
    else:
        table["依頼No"] = np.nan

    csv_tables = None
    if csv_path is not None:
        csv_tables = read_device_csv(csv_path, encoding=csv_encoding)
        names = dict(zip(csv_tables.item_master["項目番号"], csv_tables.item_master["項目名"]))
        if log_path is None:
            warnings.append("LOG がないため、CSV(依頼No)と prof(内部依頼No)を対応づけられません。項目名だけ CSV から付けています。")
            table["CSV対応"] = False
        else:
            attrs = csv_tables.attributes
            n_dup = int(attrs.duplicated("依頼No_norm").sum())
            if n_dup:
                warnings.append(f"CSV で同じ依頼No が {n_dup} 行重複しています(先頭の行を使いました)。")
            attrs = attrs.drop_duplicates("依頼No_norm", keep="first").drop(columns=["依頼No."])
            items = csv_tables.items
            base = _first_non_ratio(items)[["依頼No_norm", "項目番号", "項目名", "測定値", "Dフラグ"]]
            ratio = (items[items["項目名"].str.endswith("_ratio")].dropna(subset=["項目番号"])
                     .drop_duplicates(["依頼No_norm", "項目番号"])[["依頼No_norm", "項目番号", "測定値"]]
                     .rename(columns={"測定値": "比"}))
            table = table.merge(attrs, left_on="依頼No", right_on="依頼No_norm", how="left").drop(columns=["依頼No_norm"])
            table = table.merge(base, left_on=["依頼No", "項目番号"], right_on=["依頼No_norm", "項目番号"], how="left")
            table = table.drop(columns=["依頼No_norm"])
            if len(ratio):
                table = table.merge(ratio, left_on=["依頼No", "項目番号"], right_on=["依頼No_norm", "項目番号"], how="left")
                table = table.drop(columns=["依頼No_norm"])
            table["CSV対応"] = table["測定値"].notna()
            n_no = int((~table["CSV対応"]).sum())
            if n_no:
                warnings.append(f"CSV に測定値が見つからない波形が {n_no} 件あります。")
        if "項目名" not in table.columns:
            table["項目名"] = pd.Series([None] * len(table), dtype=object)
        table["項目名"] = table["項目名"].astype(object)
        fill = table["項目名"].isna()
        table.loc[fill, "項目名"] = table.loc[fill, "項目番号"].map(lambda v: names.get(int(v)) if pd.notna(v) else None)
    else:
        table["CSV対応"] = False
        table["項目名"] = pd.Series([None] * len(table), dtype=object)

    # the same 依頼No + item measured more than once (re-measurement gets a new 内部依頼No)
    has_req = table["依頼No"].notna()
    table["再測定"] = has_req & table.duplicated(["依頼No", "項目番号"], keep=False)

    table["項目名"] = table["項目名"].astype(object).where(table["項目名"].notna(), "")
    table["項目名"] = table["項目名"].astype(str)
    no_name = table["項目名"] == ""
    table.loc[no_name, "項目名"] = "項目" + table.loc[no_name, "項目番号"].astype(str)

    first = ["No", "依頼No", "内部依頼No", "項目番号", "項目名", "測定モード", "測定値", "処理値", "Dフラグ", "比"]
    attr_cols = [c for c in (csv_tables.attributes.columns if csv_tables is not None else [])
                 if c not in ("依頼No_norm", "依頼No.") and c in table.columns]
    rest = ["測定種別", "ﾗｯｸNo", "ポートNo", "秒", "エラーフラグ", "データ数", "測定時間(秒)", "重複", "再測定", "CSV対応"]
    order = [c for c in first if c in table.columns] + attr_cols + [c for c in rest if c in table.columns]
    order += [c for c in table.columns if c not in order]
    table = table[order].reset_index(drop=True)

    return Batch(
        name=name or prof_path.parent.name,
        prof_path=prof_path,
        csv_path=Path(csv_path) if csv_path is not None else None,
        log_path=Path(log_path) if log_path is not None else None,
        profile_n=profile_n,
        records=records,
        table=table,
        csv=csv_tables,
        log_key=log_key,
        log_info=log_info,
        warnings=warnings,
    )
