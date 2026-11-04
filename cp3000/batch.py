"""Load one CP3000 measurement batch: prof*.dat (waveforms) + *CSV_data.csv + LOG*.dat.

The string helpers, ``read_csv_sections``, ``canonicalize_csv_attr_columns`` and
``csv_build_item_master`` are copied verbatim from CWA-ML-tool src/cwa/ingestion/merger.py
(commit a591105). The join is rebuilt for viewing:

* the base table is the prof file (one row per waveform record), so waveforms without a CSV
  match are still listed;
* prof (内部依頼No, 項目番号) -> LOG (内部依頼No, 項目No) -> 表示依頼No -> CSV (依頼No, 項目番号),
  which is the same key path as merger.merge_raw_inputs, read from the other side;
* the LOG file is parsed in memory (no "LOG展開後.xlsx" is written next to the raw data);
* CSV and LOG are optional: with prof only, the waveforms are shown by 内部依頼No / 項目番号.
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
from .signal import TIME_STEP_SEC, time_axis


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
        return bool(self.prof)


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


def find_batch_folders(root: Union[str, Path], max_depth: int = 3) -> List[Path]:
    """Folders under ``root`` (including itself) that contain a prof*.dat file, newest name first."""
    root = Path(clean_path(root))
    if not root.is_dir():
        return []
    found: List[Path] = []

    def walk(d: Path, depth: int) -> None:
        try:
            entries = list(d.iterdir())
        except (PermissionError, OSError):
            return
        if any(p.is_file() and "prof" in p.name.lower() and p.suffix.lower() == ".dat" for p in entries):
            found.append(d)
        if depth >= max_depth:
            return
        for p in sorted(entries):
            if p.is_dir() and not p.name.startswith((".", "_", "~")):
                walk(p, depth + 1)

    walk(root, 0)
    return sorted(found, key=lambda p: str(p.relative_to(root)) if p != root else "", reverse=True)


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
class CsvTables:
    attributes: pd.DataFrame   # one row per 依頼No (依頼No_norm + attribute columns)
    items: pd.DataFrame        # 依頼No_norm, 項目名, 測定値, Dフラグ, 項目番号
    item_master: pd.DataFrame  # 項目名, 項目番号 (section 2)


def read_device_csv(csv_path: Union[str, Path], encoding: str = "cp932") -> CsvTables:
    header1, body1, _header2, body2 = read_csv_sections(csv_path, encoding=encoding)
    attrs, items = csv_attributes_and_items(header1, body1)
    item_master = csv_build_item_master(body2)
    item_map = dict(zip(item_master["項目名"], item_master["項目番号"]))
    items["項目番号"] = items["項目名"].map(item_map)
    miss = items["項目番号"].isna()
    if miss.any():  # "LA1_ratio" -> item number of "LA1" (as in merger)
        items.loc[miss, "項目番号"] = items.loc[miss, "項目名"].str.replace("_ratio", "", regex=False).map(item_map)
    items["項目番号"] = pd.to_numeric(items["項目番号"], errors="coerce").astype("Int64")
    return CsvTables(attributes=attrs, items=items, item_master=item_master)


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
    """One measurement batch: prof records plus a table with one row per record."""

    name: str
    prof_path: Path
    csv_path: Optional[Path]
    log_path: Optional[Path]
    profile_n: int
    records: List[ProfRecord]
    table: pd.DataFrame
    csv: Optional[CsvTables] = None
    log_key: Optional[pd.DataFrame] = None
    log_info: Dict[str, Any] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)

    def matrix(self, positions: Sequence[int]) -> Tuple[np.ndarray, np.ndarray]:
        """Raw waveforms of the given record positions, padded with NaN to the longest one."""
        recs = [self.records[int(i)] for i in positions]
        n = max((len(r.data) for r in recs), default=0)
        out = np.full((len(recs), n), np.nan)
        for k, r in enumerate(recs):
            out[k, : len(r.data)] = r.data.astype(float)
        return time_axis(n), out


def _first_non_ratio(items: pd.DataFrame) -> pd.DataFrame:
    base = items[~items["項目名"].str.endswith("_ratio")]
    return base.dropna(subset=["項目番号"]).drop_duplicates(["依頼No_norm", "項目番号"], keep="first")


def load_batch(
    prof_path: Union[str, Path],
    csv_path: Optional[Union[str, Path]] = None,
    log_path: Optional[Union[str, Path]] = None,
    *,
    profile_mode: str = "auto",
    csv_encoding: str = "cp932",
    name: Optional[str] = None,
) -> Batch:
    """Read the prof file and, when given, the CSV and LOG files, and join them per waveform."""
    prof_path = Path(prof_path)
    warnings: List[str] = []
    profile_n, _, _, _, _ = detect_profile_format(prof_path, mode=profile_mode)
    records = parse_prof_dat(prof_path, profile_n=profile_n)

    table = pd.DataFrame({
        "No": [r.no for r in records],
        "内部依頼No": pd.array([r.internal_request_no for r in records], dtype="Int64"),
        "項目番号": pd.array([r.item_no for r in records], dtype="Int64"),
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

    first = ["No", "依頼No", "内部依頼No", "項目番号", "項目名", "測定値", "Dフラグ", "比"]
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
