"""CP3000 波形ビューワー (Streamlit).

    streamlit run app.py

prof*.dat (波形) / *CSV_data.csv / LOG*.dat を読み、生波形・凝固波形・速度・加速度波形を表示する。
生データのフォルダには何も書き込まない(アップロードしたファイルは一時フォルダに置く)。
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import streamlit as st

import cp3000
from cp3000.batch import (
    MODE_CHROMOGENIC,
    MODE_COAGULATION,
    MODE_UNKNOWN,
    Batch,
    clean_path,
    find_batch_files,
    find_batch_folders,
    load_batch,
)
from cp3000.plots import (
    MAX_SERIES,
    WAVE_TYPES,
    Series,
    Theme,
    detail_chromogenic_figure,
    detail_figure,
    overlay_figure,
)
from cp3000.signal import align_waveform_time, derive_batch

APP_DIR = Path(__file__).resolve().parent
SETTINGS = Path(os.environ.get("CP3000_SETTINGS") or (APP_DIR / "settings.json"))
DEMO_DIR = APP_DIR / "demo_data"
PLOT_CONFIG = {"displaylogo": False, "toImageButtonOptions": {"format": "png", "scale": 2, "filename": "cp3000_waveform"}}

st.set_page_config(page_title="CP3000 波形ビューワー", page_icon="📈", layout="wide")

st.markdown(
    """
<style>
.block-container {padding-top: 1.6rem; padding-bottom: 2rem;}
div[data-testid="stMetric"] {border: 1px solid rgba(128,128,128,0.25); border-radius: 10px;
  padding: 10px 14px; background: rgba(128,128,128,0.04);}
div[data-testid="stMetricLabel"] p {font-size: 0.82rem;}
.chips {display: flex; flex-wrap: wrap; gap: 6px; margin: 2px 0 10px 0;}
.chip {border: 1px solid rgba(128,128,128,0.35); border-radius: 999px; padding: 2px 10px;
  font-size: 0.80rem; white-space: nowrap;}
.chip.ok::before {content: "✓ "; color: #1baf7a; font-weight: 700;}
.chip.no::before {content: "– "; opacity: 0.6;}
.chip.no {opacity: 0.65;}
.subtle {opacity: 0.7; font-size: 0.85rem;}
</style>
""",
    unsafe_allow_html=True,
)


# ---- settings / caching ----------------------------------------------------------------

def load_settings() -> dict:
    try:
        return json.loads(SETTINGS.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_settings(**kw) -> None:
    data = load_settings()
    data.update(kw)
    try:
        SETTINGS.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def file_sig(p: Optional[Path]) -> str:
    if p is None:
        return "-"
    s = p.stat()
    return f"{p}|{s.st_size}|{s.st_mtime_ns}"


@st.cache_resource(max_entries=4, show_spinner=False)
def cached_batch(sig: str, prof: Optional[str], csv: Optional[str], log: Optional[str], mode: str, enc: str, name: str) -> Batch:
    return load_batch(prof, csv, log, profile_mode=mode, csv_encoding=enc, name=name)


@st.cache_resource(max_entries=8, show_spinner=False)
def cached_tetc(sig: str, _batch: Batch, window: Optional[float], coag: float) -> pd.DataFrame:
    """Te/Tc of every waveform (computed in chunks, only the table is kept)."""
    parts = []
    n = len(_batch.records)
    for start in range(0, n, 200):
        pos = list(range(start, min(n, start + 200)))
        parts.append(_batch.derive(pos, window_end_sec=window, coag_ratio=coag).tetc)
    if not parts:
        return pd.DataFrame(columns=["Te1", "Tc1", "Te1_Tc1", "Te2", "Tc2", "Te2_Tc2"])
    return pd.concat(parts, ignore_index=True)


@st.cache_resource(max_entries=16, show_spinner=False)
def cached_derived(sig: str, _batch: Batch, positions: Tuple[int, ...], window: Optional[float], coag: float):
    return _batch.derive(list(positions), window_end_sec=window, coag_ratio=coag)


def current_theme() -> Theme:
    try:
        return Theme(dark=(st.context.theme.type == "dark"))
    except Exception:
        return Theme(dark=False)


# ---- sidebar: where the data is --------------------------------------------------------

settings = load_settings()

with st.sidebar:
    st.markdown("### 📂 データ")
    source = st.radio("読み込み方法", ["フォルダから選ぶ", "ファイルをアップロード"], horizontal=True,
                      label_visibility="collapsed")

    prof_p = csv_p = log_p = None
    batch_name = ""
    if source == "フォルダから選ぶ":
        default_root = settings.get("root") or str(DEMO_DIR)
        root = st.text_input("親フォルダ(バッチのフォルダを含む場所)", value=default_root,
                             help="例: E:\\CWA\\data\\raw。この下で prof*.dat または *CSV_data.csv を含むフォルダを探します(3階層まで)。")
        if root != settings.get("root"):
            save_settings(root=root)
        root_clean = clean_path(root)
        rootp = Path(root_clean) if root_clean else Path()
        direct_csv: Optional[Path] = None
        if root_clean and rootp.is_file() and rootp.suffix.lower() == ".csv":
            direct_csv = rootp
            rootp = rootp.parent
        folders = find_batch_folders(rootp) if root_clean else []
        batch_entries: List[Tuple[str, Path, Optional[Path]]] = []
        for f in folders:
            f_files = find_batch_files(f)
            if f_files.prof:
                lbl = str(f.relative_to(rootp)) if f != rootp else f.name
                batch_entries.append((lbl, f, None))
            else:
                for c in f_files.csv:
                    lbl = str(c.relative_to(rootp)) if (f == rootp or len(f_files.csv) > 1) else str(f.relative_to(rootp))
                    batch_entries.append((lbl, f, c))
        if not batch_entries:
            st.warning("prof*.dat または *CSV_data.csv を含むフォルダが見つかりません。")
        else:
            labels = [e[0] for e in batch_entries]
            last = str(direct_csv.relative_to(rootp)) if direct_csv is not None else settings.get("last_batch")
            idx = labels.index(last) if last in labels else 0
            pick = st.selectbox(f"測定バッチ({len(batch_entries)} 件)", labels, index=idx)
            if direct_csv is None and pick != settings.get("last_batch"):
                save_settings(last_batch=pick)
            _, folder, picked_csv = batch_entries[labels.index(pick)]
            files = find_batch_files(folder)
            with st.expander("使うファイル", expanded=len(files.prof) > 1 or len(files.csv) > 1 or len(files.log) > 1 or not files.prof):
                if files.prof:
                    prof_opts: List[Optional[Path]] = list(files.prof) + ([None] if files.csv else [])
                    prof_p = st.selectbox("prof(波形)", prof_opts,
                                          format_func=lambda p: "(使わない・CSVのみ)" if p is None else p.name)
                    csv_opts = ([None] + files.csv) if prof_p is not None else list(files.csv)
                    csv_p = st.selectbox("CSV(測定結果)", csv_opts,
                                         index=(1 if files.csv else 0) if prof_p is not None else 0,
                                         format_func=lambda p: "(使わない)" if p is None else p.name)
                    log_opts = [None] + files.log
                    log_p = st.selectbox("LOG(依頼No の対応)", log_opts,
                                         index=1 if (files.log and prof_p is not None) else 0,
                                         format_func=lambda p: "(使わない)" if p is None else p.name)
                    batch_name = folder.name if prof_p is not None else (csv_p.stem if csv_p is not None else folder.name)
                else:
                    prof_p = None
                    csv_idx = files.csv.index(picked_csv) if picked_csv in files.csv else 0
                    csv_p = st.selectbox("CSV(測定結果・簡易タイムコース)", files.csv, index=csv_idx,
                                         format_func=lambda p: p.name)
                    log_p = None
                    batch_name = csv_p.stem if csv_p is not None else folder.name
    else:
        ups = st.file_uploader("prof*.dat・LOG*.dat・*CSV_data.csv(まとめて選べます、CSV単独でも可)", type=["dat", "csv"],
                               accept_multiple_files=True)
        if ups:
            key = hashlib.sha1("|".join(f"{u.name}:{u.size}" for u in ups).encode()).hexdigest()[:12]
            if st.session_state.get("upload_key") != key:
                d = Path(tempfile.mkdtemp(prefix="cp3000_viewer_"))
                for u in ups:
                    (d / u.name).write_bytes(u.getvalue())
                st.session_state["upload_key"] = key
                st.session_state["upload_dir"] = str(d)
            files = find_batch_files(st.session_state["upload_dir"])
            prof_p = files.prof[0] if files.prof else None
            csv_p = files.csv[0] if files.csv else None
            log_p = files.log[0] if files.log else None
            batch_name = csv_p.stem if (prof_p is None and csv_p is not None) else "アップロード"
            if prof_p is None and csv_p is None:
                st.warning("prof*.dat または *CSV_data.csv が含まれていません。")

    with st.expander("読み込みの詳細設定"):
        mode = st.selectbox("prof の点数", ["auto", "6000", "3600"],
                            format_func=lambda m: {"auto": "自動判定", "6000": "6000 点", "3600": "3600 点"}[m])
        enc = st.selectbox("CSV の文字コード", ["cp932", "utf-8-sig", "utf-8"])

if prof_p is None and csv_p is None:
    st.title("CP3000 波形ビューワー")
    st.info("左のサイドバーで測定バッチのフォルダを選ぶか、ファイルをアップロードしてください。"
            "試しに見る場合は `python tools/make_demo_batch.py` で demo_data を作れます。")
    st.stop()

sig = "||".join([file_sig(prof_p), file_sig(csv_p), file_sig(log_p), mode, enc])
try:
    with st.spinner("読み込み中…"):
        batch = cached_batch(sig, str(prof_p) if prof_p else None, str(csv_p) if csv_p else None,
                             str(log_p) if log_p else None, mode, enc,
                             batch_name or (prof_p.parent.name if prof_p else csv_p.stem))
except Exception as e:  # show the reader's message instead of a traceback
    st.error(f"読み込みに失敗しました: {e}")
    st.stop()

# ---- mode detection & sidebar display options ------------------------------------------

available_modes = batch.modes
with st.sidebar:
    if len(available_modes) > 1:
        st.markdown("### 🔬 測定モード")
        selected_mode = st.radio("測定モード選択", available_modes, horizontal=True,
                                 help="凝固項目と比色項目で解析・表示方法が異なります。片方ずつ表示します。")
    elif len(available_modes) == 1:
        selected_mode = available_modes[0]
    else:
        selected_mode = MODE_COAGULATION

is_chromogenic = (selected_mode == MODE_CHROMOGENIC)
table = batch.table[batch.table["測定モード"] == selected_mode].copy().reset_index(drop=True)

with st.sidebar:
    st.markdown("### 🎛 表示")
    if is_chromogenic:
        type_keys = ["raw", "base_aligned", "abs_slope"]
        types = st.multiselect("波形の種類(上から順にパネル表示)", type_keys,
                               default=["raw", "base_aligned", "abs_slope"],
                               format_func=lambda k: WAVE_TYPES[k][0])
        st.markdown("#### ⏱️ タイムコースの0点合わせ")
        ref_mode = st.radio("0点の基準", ["始点(0秒時点)", "任意ポイント指定"], horizontal=True)
        time_pts = batch.time_points if batch.time_points is not None else np.array([])
        if len(time_pts) == 0 and len(batch.records):
            longest_rec = max(batch.records, key=lambda r: len(r.time) if r.time is not None else 0)
            if longest_rec.time is not None:
                time_pts = longest_rec.time
        ref_idx = 0
        ref_time_val = float(time_pts[0]) if len(time_pts) else 0.0
        if ref_mode == "任意ポイント指定" and len(time_pts):
            pt_options = list(range(len(time_pts)))
            ref_idx = st.selectbox(
                "合わせるポイント",
                pt_options,
                index=min(9, len(time_pts) - 1),
                format_func=lambda i: f"第 {i + 1} ポイント ({time_pts[i]:.1f} 秒)"
            )
            ref_time_val = float(time_pts[ref_idx])
        align = "off"
        show_tc2 = False
        window = None
        coag = 0.5
    else:
        type_keys = ["raw", "scaled", "endpoint_scaled", "slope", "acceleration"]
        types = st.multiselect("波形の種類(上から順にパネル表示)", type_keys,
                               default=["raw", "scaled", "slope"],
                               format_func=lambda k: WAVE_TYPES[k][0])
        align = st.selectbox("時間軸のそろえ方", ["off", "tc2", "peak", "rise"], format_func=lambda m: {
            "off": "そろえない(測定時間)", "tc2": "Tc2 を 0 秒に", "peak": "速度のピークを 0 秒に",
            "rise": "立ち上がり(10%)を 0 秒に"}[m])
        ref_idx = 0
        ref_time_val = None
        show_tc2 = st.toggle("Tc2 の位置に印を付ける", value=True)
        with st.expander("計算の設定"):
            window = st.number_input("解析窓(秒、空欄=全長)", value=None, min_value=10.0, step=10.0, placeholder="全長",
                                     help="生波形をこの時間で切ってから計算します(0–100% はこの窓内の最大で規格化)。")
            coag = st.slider("Tc の判定割合", 0.1, 0.9, 0.5, 0.05, help="累積の何割に達した時刻を Tc とするか(標準 0.5)。")

    c1, c2 = st.columns(2)
    x_lo = c1.number_input("表示開始(秒)", value=None, step=10.0, placeholder="自動")
    x_hi = c2.number_input("表示終了(秒)", value=None, step=10.0, placeholder="自動")
    baseline = st.toggle("生波形の開始値を 0 にそろえる", value=False,
                         help="生波形の最初の値を引いて、立ち上がりの大きさを比べやすくします。")
    thin = st.toggle("重ね描きは間引いて軽くする", value=True, help="1 本あたり約 1500 点に間引きます。詳細タブは全点です。")
    st.markdown(f"<div class='subtle'>cp3000 v{cp3000.__version__}</div>", unsafe_allow_html=True)

if not is_chromogenic and len(table):
    tetc = cached_tetc(sig, batch, window, coag)
    table["Tc2(計算)"] = tetc.iloc[table["No"] - 1]["Tc2"].round(1).to_numpy()
    table["Te2(計算)"] = tetc.iloc[table["No"] - 1]["Te2"].round(1).to_numpy()
else:
    table["Tc2(計算)"] = np.nan
    table["Te2(計算)"] = np.nan
table["_pos"] = table["No"] - 1

label_candidates = [c for c in ["依頼No", "SID", "検体名", "検体ﾊﾞｰｺｰﾄﾞ", "項目名", "内部依頼No", "No", "属性"] if c in table.columns]


def default_label_cols() -> List[str]:
    cols = [c for c in ["依頼No", "項目名"] if c in table.columns and table[c].notna().any()]
    for c in ["検体名", "SID"]:
        if c in table.columns and table[c].notna().any():
            cols.append(c)
            break
    if not cols or "依頼No" not in cols:
        cols = ["内部依頼No", "項目名"]
    return cols


with st.sidebar:
    label_cols = st.multiselect("凡例に出す列", label_candidates, default=default_label_cols())


def make_label(row: pd.Series) -> str:
    parts = []
    for c in label_cols or ["No"]:
        v = row.get(c)
        if v is None or (isinstance(v, float) and np.isnan(v)) or v is pd.NA or str(v) in ("", "nan", "<NA>"):
            continue
        parts.append(str(v))
    return " / ".join(parts) or f"No {row['No']}"


table["_label"] = table.apply(make_label, axis=1)

# ---- header ----------------------------------------------------------------------------

st.title(f"📈 {batch.name}")


def chip(label: str, path: Optional[Path]) -> str:
    cls = "ok" if path is not None else "no"
    return f"<span class='chip {cls}'>{label}{(': ' + path.name) if path is not None else ''}</span>"


pts_summary = batch.profile_n_summary()
step_summary = batch.time_step_summary()
pts_chip = (f"<span class='chip'>{pts_summary} (CSV 簡易タイムコース・{step_summary})</span>"
            if batch.prof_path is None else f"<span class='chip'>{pts_summary}</span>")
mode_chip = f"<span class='chip ok'>モード: {selected_mode}</span>"
st.markdown("<div class='chips'>" + mode_chip + chip("prof", batch.prof_path) + chip("CSV", batch.csv_path)
            + chip("LOG", batch.log_path) + pts_chip + "</div>",
            unsafe_allow_html=True)

m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("波形", f"{len(table):,}")
m2.metric("検体(依頼No)", f"{table['依頼No'].nunique():,}" if table["依頼No"].notna().any() else "–")
m3.metric("項目", f"{table['項目名'].nunique()}")
m4.metric("CSV と対応", f"{int(table['CSV対応'].sum()):,} / {len(table):,}" if batch.csv_path else "–")
m5.metric("エラーフラグあり", f"{int((table['エラーフラグ'] != 0).sum()):,}")

if batch.warnings:
    with st.expander(f"⚠️ 確認事項 {len(batch.warnings)} 件"):
        for w in batch.warnings:
            st.markdown(f"- {w}")

theme = current_theme()


def display_values(d, k: int) -> Dict[str, np.ndarray]:
    n_k = len(d.time_at(k))
    raw = d.raw[k, :n_k].copy()
    if baseline:
        fin = np.flatnonzero(np.isfinite(raw))
        if fin.size:
            raw = raw - raw[fin[0]]
    base_aligned = d.align_chromogenic_baseline(k, ref_idx=ref_idx)
    abs_slope = d.abs_slope[k, :n_k] if d.abs_slope is not None else np.full(n_k, np.nan)
    return {
        "raw": raw,
        "scaled": d.scaled[k, :n_k],
        "endpoint_scaled": d.endpoint_scaled[k, :n_k],
        "slope": d.slope[k, :n_k],
        "acceleration": d.acceleration[k, :n_k],
        "base_aligned": base_aligned,
        "abs_slope": abs_slope,
    }


def time_shift(d, k: int) -> float:
    t = d.time_at(k)
    if len(t) == 0:
        return np.nan
    if align == "off":
        return 0.0
    if align == "tc2":
        tc2 = d.tetc["Tc2"].iloc[k]
        return float(tc2) if np.isfinite(tc2) else np.nan
    ref = (d.slope[k] if align == "peak" else d.scaled[k])[: len(t)]
    if not np.isfinite(ref).any():
        return np.nan
    shifted = align_waveform_time(t, ref, align_mode=align)
    return float(t[0] - shifted[0])


def x_range(default_hi: Optional[float]) -> Optional[Tuple[float, float]]:
    if x_lo is None and x_hi is None:
        return None
    lo = x_lo if x_lo is not None else (0.0 if align == "off" else -60.0)
    hi = x_hi if x_hi is not None else (default_hi or 600.0)
    return (lo, hi) if hi > lo else None


# ---- color assignment (color follows the waveform / group, never its rank) ---------------

def per_wave_colors(nos: List[int]) -> Dict[int, str]:
    slots: Dict[int, int] = st.session_state.setdefault("color_slots", {})
    for no in list(slots):
        if no not in nos:
            del slots[no]
    for no in nos:
        if no not in slots:
            used = set(slots.values())
            free = [i for i in range(MAX_SERIES) if i not in used]
            if not free:
                break
            slots[no] = free[0]
    return {no: theme.series[slots[no]] for no in nos if no in slots}


def group_colors(col: str) -> Dict[str, str]:
    """Up to 7 largest groups of the whole batch get fixed slots; the rest fold into その他."""
    counts = table[col].astype(str).value_counts()
    order = sorted(counts.index[:MAX_SERIES - 1]) if len(counts) > MAX_SERIES else sorted(counts.index)
    return {g: theme.series[i] for i, g in enumerate(order)}


# ---- tabs ------------------------------------------------------------------------------

tab_overlay, tab_detail, tab_info = st.tabs(["📈 重ね描き", "🔍 1波形の詳細", "🗂 一覧・読み込み情報"])

with tab_overlay:
    f1, f2, f3, f4 = st.columns([2, 2, 3, 1.3])
    items = sorted(table["項目名"].unique())
    pick_items = f1.multiselect("項目", items, default=[], placeholder="すべて")
    group_col = "属性" if "属性" in table.columns else ("測定種別" if "測定種別" in table.columns else None)
    pick_groups = []
    if group_col:
        pick_groups = f2.multiselect(group_col, sorted(table[group_col].dropna().astype(str).unique()),
                                     default=[], placeholder="すべて")
    query = f3.text_input("検索(依頼No・SID・検体名など)", placeholder="例: 0012, DEMO-01")
    only_err = f4.toggle("エラーのみ", value=False)

    view = table
    if pick_items:
        view = view[view["項目名"].isin(pick_items)]
    if pick_groups:
        view = view[view[group_col].astype(str).isin(pick_groups)]
    if query:
        cols = [c for c in ["依頼No", "SID", "検体名", "検体ﾊﾞｰｺｰﾄﾞ", "内部依頼No", "_label"] if c in view.columns]
        hit = np.zeros(len(view), dtype=bool)
        for c in cols:
            hit |= view[c].astype(str).str.contains(query, case=False, regex=False, na=False).to_numpy()
        view = view[hit]
    if only_err:
        view = view[view["エラーフラグ"] != 0]

    if is_chromogenic:
        show_cols = [c for c in ["No", "依頼No", "SID", "検体名", "項目名", "測定値", "処理値", "ポートNo",
                                 "測定時間(秒)", "エラーフラグ", "再測定"] if c in view.columns]
    else:
        show_cols = [c for c in ["No", "依頼No", "SID", "検体名", "項目名", "測定値", "Tc2(計算)", "属性",
                                 "測定時間(秒)", "エラーフラグ", "再測定"] if c in view.columns]
    if not table["CSV対応"].any():
        show_cols = [c for c in ["No", "内部依頼No", "項目番号", "項目名", "測定モード", "ポートNo",
                                 "測定時間(秒)", "エラーフラグ", "重複"] if c in view.columns]

    left, right = st.columns([1, 2.4], gap="medium")
    with left:
        st.markdown(f"**波形の一覧** <span class='subtle'>{len(view):,} 件 ・ 行を選ぶと右に重ねて表示</span>",
                    unsafe_allow_html=True)
        event = st.dataframe(view[show_cols], hide_index=True, height=560, on_select="rerun",
                             selection_mode="multi-row", key=f"pick_{sig}",
                             column_config={"No": st.column_config.NumberColumn(width="small"),
                                            "再測定": st.column_config.CheckboxColumn(width="small")})
        rows = list(event.selection.rows) if event is not None else []
        show_all = st.toggle("絞り込んだ波形をすべて重ねる(最大 300 本)", value=False)

    if show_all:
        chosen = view.head(300)
    elif rows:
        chosen = view.iloc[rows]
    else:
        chosen = view.head(min(5, len(view)))

    with right:
        if chosen.empty or not types:
            st.info("表示する波形または波形の種類がありません。")
        else:
            color_opts = ["波形ごと"] + [c for c in ["項目名", "属性", "測定種別", "依頼No"] if c in table.columns]
            cc1, cc2 = st.columns([2, 3])
            color_by = cc1.selectbox("色分け", color_opts, index=0 if len(chosen) <= MAX_SERIES else 1)
            if not rows and not show_all:
                cc2.markdown("<div class='subtle' style='padding-top:2rem'>一覧の先頭 5 件を表示中。"
                             "行を選ぶと切り替わります(Ctrl / Shift で複数)。</div>", unsafe_allow_html=True)

            positions = tuple(int(p) for p in chosen["_pos"])
            d = cached_derived(sig, batch, positions, window, coag)
            nos = [int(n) for n in chosen["No"]]
            if color_by == "波形ごと":
                cmap = per_wave_colors(nos)
                if len(nos) > MAX_SERIES:
                    st.caption(f"{MAX_SERIES} 本を超えたため 1 色で表示しています(色を使い回すと見分けられないため)。"
                               "線にマウスを合わせると名前が出ます。色分けを「項目名」などにも切り替えられます。")
                    cmap = {}
            else:
                gmap = group_colors(color_by)
            series = []
            for k, (_, row) in enumerate(chosen.iterrows()):
                shift = time_shift(d, k)
                if not np.isfinite(shift):
                    continue
                if color_by == "波形ごと":
                    color, group = cmap.get(int(row["No"]), theme.other), None
                else:
                    g = str(row[color_by])
                    color, group = gmap.get(g, theme.other), (g if g in gmap else "その他")
                tc2 = d.tetc["Tc2"].iloc[k]
                tk = d.time_at(k)
                series.append(Series(label=row["_label"], color=color, time=tk - shift,
                                     values=display_values(d, k), tc2=(tc2 - shift) if np.isfinite(tc2) else np.nan,
                                     group=group))
            skipped = len(chosen) - len(series)
            if skipped:
                st.caption(f"そろえる基準が求まらない波形 {skipped} 件は表示していません。")
            if series:
                max_t = max(float(np.nanmax(s.time[np.isfinite(s.values['raw'])])) if np.isfinite(s.values['raw']).any()
                            else 0.0 for s in series)
                fig = overlay_figure(
                    series, types, theme, x_range=x_range(max_t),
                    x_title="時間 (秒)" if align == "off" else "そろえた時間 (秒)",
                    show_tc2=(show_tc2 if not is_chromogenic else False),
                    ref_time=(ref_time_val if is_chromogenic else None),
                    max_points=1500 if thin else None,
                    legend_groups=(color_by != "波形ごと"),
                    panel_height=230 if len(types) >= 3 else 300,
                )
                fig.update_layout(uirevision=f"{sig}|{align}|{','.join(types)}|{ref_idx}")
                st.plotly_chart(fig, width="stretch", config=PLOT_CONFIG, theme=None)

                with st.popover("⬇ 表示中の波形を CSV で保存"):
                    kind = st.selectbox("波形の種類", type_keys, format_func=lambda k: WAVE_TYPES[k][0], key="dl_kind")
                    meta_cols = ["No", "依頼No", "内部依頼No", "項目番号", "項目名", "測定モード", "SID", "検体名",
                                 "測定値", "処理値", "Tc2(計算)"]
                    meta = chosen[[c for c in meta_cols if c in chosen.columns]].reset_index(drop=True)
                    if d.times is None:
                        vals = np.vstack([display_values(d, k)[kind] for k in range(len(chosen))])
                        val_df = pd.DataFrame(vals, columns=[f"{x:g}" if round(x, 1) != x else f"{x:.1f}" for x in d.time])
                    else:
                        row_series = [
                            pd.Series(display_values(d, k)[kind], index=np.round(d.time_at(k), 3))
                            for k in range(len(chosen))
                        ]
                        val_df = pd.DataFrame(row_series).reset_index(drop=True)
                        val_df.columns = [f"{float(x):g}" if round(float(x), 1) != float(x) else f"{float(x):.1f}" for x in val_df.columns]
                    wide = pd.concat([meta, val_df], axis=1)
                    st.download_button("CSV をダウンロード", wide.to_csv(index=False).encode("utf-8-sig"),
                                       file_name=f"{batch.name}_{kind}.csv", mime="text/csv")
                    st.caption("1 行 = 1 波形、列 = 時間(秒)。時間軸はそろえる前の値です。")

with tab_detail:
    if table.empty:
        st.info("波形がありません。")
    else:
        opts = table["No"].tolist()
        labels = dict(zip(table["No"], table["_label"]))
        if "detail_no" not in st.session_state or st.session_state["detail_no"] not in opts:
            st.session_state["detail_no"] = opts[0]

        def step(delta: int) -> None:
            i = opts.index(st.session_state["detail_no"])
            st.session_state["detail_no"] = opts[(i + delta) % len(opts)]

        b1, b2, b3 = st.columns([0.6, 6, 0.6])
        b1.button("◀ 前", on_click=step, args=(-1,), width="stretch")
        b2.selectbox("波形", opts, key="detail_no", format_func=lambda n: f"No {n} ・ {labels[n]}",
                     label_visibility="collapsed")
        b3.button("次 ▶", on_click=step, args=(1,), width="stretch")

        no = st.session_state["detail_no"]
        row = table[table["No"] == no].iloc[0]
        d1 = cached_derived(sig, batch, (int(row["_pos"]),), window, coag)
        t1 = d1.time_at(0)
        tt = d1.tetc.iloc[0].to_dict()
        try:
            device = float(row["測定値"]) if "測定値" in row and pd.notna(row["測定値"]) else None
        except (TypeError, ValueError):
            device = None
        g, info = st.columns([3, 1.1], gap="medium")
        with g:
            vals = display_values(d1, 0)
            if is_chromogenic:
                try:
                    proc_val = float(row["処理値"]) if "処理値" in row and pd.notna(row["処理値"]) else None
                except (TypeError, ValueError):
                    proc_val = None
                dfig = detail_chromogenic_figure(
                    t1, vals, theme, color=theme.series[0],
                    ref_time=ref_time_val,
                    x_range=x_range(float(t1[-1]) if len(t1) else None),
                    device_value=device, proc_value=proc_val,
                )
            else:
                dfig = detail_figure(
                    t1, vals, tt, theme, color=theme.series[0],
                    x_range=x_range(float(t1[-1]) if len(t1) else None) if align == "off" else None,
                    device_value=device,
                )
            dfig.update_layout(uirevision=f"{sig}|detail|{selected_mode}|{ref_idx}")
            st.plotly_chart(dfig, width="stretch", config=PLOT_CONFIG, theme=None)
        with info:
            def fmt(x: float, unit: str = " s", nd: int = 1) -> str:
                return f"{x:.{nd}f}{unit}" if x is not None and np.isfinite(x) else "–"

            if is_chromogenic:
                v_slp = vals["abs_slope"]
                vmax = float(np.nanmax(v_slp)) if np.isfinite(v_slp).any() else np.nan
                t_vmax = float(t1[int(np.nanargmax(v_slp))]) if np.isfinite(v_slp).any() else np.nan
                ref_raw = vals["raw"][ref_idx] if 0 <= ref_idx < len(vals["raw"]) else np.nan
                kv = [
                    ("基準点", f"{ref_time_val:.1f} s"),
                    ("基準点吸光度", f"{ref_raw:.0f}" if np.isfinite(ref_raw) else "–"),
                    ("最大反応速度", f"{fmt(vmax, ' mAbs/min.', 2)}({fmt(t_vmax)})"),
                    ("装置測定値", f"{row['測定値']}" if "測定値" in row and pd.notna(row["測定値"]) else "–"),
                ]
                if "処理値" in row and pd.notna(row["処理値"]):
                    kv.append(("装置処理値", f"{row['処理値']} mAbs/min."))
                st.markdown("**比色解析値**")
            else:
                v = vals["slope"]
                vmax = float(np.nanmax(v)) if np.isfinite(v).any() else np.nan
                t_vmax = float(t1[int(np.nanargmax(v))]) if np.isfinite(v).any() else np.nan
                kv = [("Tc2", fmt(tt["Tc2"])), ("Te2", fmt(tt["Te2"])), ("Tc1", fmt(tt["Tc1"])), ("Te1", fmt(tt["Te1"])),
                      ("装置の測定値", fmt(device) if device is not None else "–"),
                      ("Tc2 − 装置値", fmt(tt["Tc2"] - device, " s") if device is not None and np.isfinite(tt["Tc2"]) else "–"),
                      ("速度の最大", f"{fmt(vmax, ' %/s', 2)}({fmt(t_vmax)})")]
                st.markdown("**計算値**")
            st.markdown("<table style='width:100%;font-size:0.9rem'>" + "".join(
                f"<tr><td style='opacity:.75;padding:3px 6px'>{k}</td>"
                f"<td style='text-align:right;font-weight:600;padding:3px 6px;font-variant-numeric:tabular-nums'>{val}</td></tr>"
                for k, val in kv) + "</table>", unsafe_allow_html=True)
            st.markdown("**レコード情報**")
            skip = {"_pos", "_label", "Tc2(計算)", "Te2(計算)"}
            info_df = pd.DataFrame({"項目": [c for c in table.columns if c not in skip],
                                    "値": [("" if pd.isna(row[c]) else str(row[c])) for c in table.columns if c not in skip]})
            st.dataframe(info_df, hide_index=True, height=360, width="stretch")
        if is_chromogenic:
            st.caption("比色項目: 生波形、指定基準点で 0 にそろえたタイムコース差分、および反応速度(一次微分: mAbs/min.)を表示しています。")
        else:
            st.caption("縦線: 点線 = Tc1 / Te1、破線 = Tc2 / Te2、橙の実線 = 装置の測定値(CSV)。"
                       "Te/Tc はリポジトリの 01 バッチと同じ手順で計算(移動平均 → 差分 → 移動中央値 → 累積)。")

with tab_info:
    st.markdown("**全波形の一覧**")
    full = table.drop(columns=["_pos", "_label"])
    st.dataframe(full, hide_index=True, height=380, width="stretch")
    st.download_button("一覧を CSV で保存", full.to_csv(index=False).encode("utf-8-sig"),
                       file_name=f"{batch.name}_一覧.csv", mime="text/csv")

    st.markdown("**読み込んだファイル**")
    rows_info = []
    for kind, p in [("prof", batch.prof_path), ("CSV", batch.csv_path), ("LOG", batch.log_path)]:
        if p is None:
            rows_info.append({"種類": kind, "ファイル": "(なし)", "サイズ": "", "フォルダ": ""})
        else:
            rows_info.append({"種類": kind, "ファイル": p.name, "サイズ": f"{p.stat().st_size:,} bytes", "フォルダ": str(p.parent)})
    st.dataframe(pd.DataFrame(rows_info), hide_index=True, width="stretch")
    if batch.prof_path is not None:
        detail = [f"prof: {pts_summary}、{len(batch.records):,} レコード"]
    else:
        detail = [f"CSV プロファイル(簡易タイムコース): {pts_summary}({step_summary})、{len(batch.records):,} レコード"]
    if batch.log_info:
        detail.append(f"LOG: 文字コード {batch.log_info['encoding']}、{batch.log_info['lines']:,} 行"
                      f"(うち時刻付き {batch.log_info['parsed_lines']:,} 行)")
    for line in detail:
        st.markdown(f"- {line}")

    if batch.csv is not None and (batch.log_path is not None or batch.prof_path is None):
        items_csv = batch.csv.items[~batch.csv.items["項目名"].str.endswith("_ratio")].dropna(subset=["項目番号"])
        have = set(zip(table["依頼No"].astype(str), table["項目番号"].astype("Int64").astype(str)))
        missing = items_csv[[(a, str(b)) not in have for a, b in zip(items_csv["依頼No_norm"], items_csv["項目番号"])]]
        st.markdown(f"**CSV にあって波形が見つからない測定** {len(missing):,} 件")
        if len(missing):
            st.dataframe(missing.rename(columns={"依頼No_norm": "依頼No"}), hide_index=True, height=240, width="stretch")
