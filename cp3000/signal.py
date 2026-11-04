"""Signal processing for coagulation waveforms (derived waveforms and Te/Tc).

Functions are copied verbatim from CWA-ML-tool (commit a591105):
src/cwa/signal/{filters,cumulative,slope}.py, src/cwa/coagulation/{tetc,trimming}.py and
src/cwa/plotting/waveforms.py (align_waveform_time). Only the repo's feature-registry decorator
on ``search_te_tc`` is removed. ``derive_record`` at the bottom follows
src/cwa/signal/derive.py::derive_waveforms (the 01 batch steps) for numpy arrays.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view

RATIO_POINTS = 20
SLOPE_HALF = 10


# ---- from src/cwa/signal/filters.py -------------------------------------------

def moving_average_batch(
    arr2d: np.ndarray, AnF: int = 4, AnB: int = 4, batch_size: int = 100
) -> np.ndarray:
    """Moving average over a 2D waveform array [N, points] with forward/backward window."""
    arr2d = np.asarray(arr2d, dtype=float)
    if arr2d.ndim == 1:
        arr2d = arr2d[None, :]
    w = AnF + AnB + 1
    out = np.full_like(arr2d, np.nan)
    if arr2d.shape[1] < w:
        return out
    for start in range(0, arr2d.shape[0], batch_size):
        end = min(start + batch_size, arr2d.shape[0])
        block = arr2d[start:end]
        win = sliding_window_view(block, window_shape=w, axis=1)
        ok = np.isfinite(win).all(axis=-1)
        vals = np.full(ok.shape, np.nan)
        vals[ok] = win[ok].mean(axis=-1)
        out[start:end, AnF : AnF + vals.shape[1]] = vals
    return out


def adjacent_diff(arr2d: np.ndarray) -> np.ndarray:
    """Adjacent difference for a 2D waveform array [N, points] (arr[:, 1:] - arr[:, :-1])."""
    arr2d = np.asarray(arr2d, dtype=float)
    if arr2d.ndim == 1:
        arr2d = arr2d[None, :]
    diff_array = np.full_like(arr2d, np.nan)
    if arr2d.shape[1] < 2:
        return diff_array
    diff_array[:, 1:] = np.where(
        np.isfinite(arr2d[:, 1:]) & np.isfinite(arr2d[:, :-1]),
        arr2d[:, 1:] - arr2d[:, :-1],
        np.nan,
    )
    return diff_array


def median_batch(
    arr2d: np.ndarray, Mn: int = 20, batch_size: int = 100
) -> np.ndarray:
    """Moving median filter over a 2D waveform array [N, points]."""
    arr2d = np.asarray(arr2d, dtype=float)
    if arr2d.ndim == 1:
        arr2d = arr2d[None, :]
    w = 2 * Mn + 1
    out = np.full_like(arr2d, np.nan)
    if arr2d.shape[1] < w:
        return out
    for start in range(0, arr2d.shape[0], batch_size):
        end = min(start + batch_size, arr2d.shape[0])
        block = arr2d[start:end]
        win = sliding_window_view(block, window_shape=w, axis=1)
        ok = np.isfinite(win).all(axis=-1)
        vals = np.full(ok.shape, np.nan)
        vals[ok] = np.median(win[ok], axis=-1)
        out[start:end, Mn : Mn + vals.shape[1]] = vals
    return out


def window_all_finite_mask_2d(
    arr2d: np.ndarray, left: int, right: int
) -> np.ndarray:
    """Create boolean mask where all elements in sliding window [left + right + 1] are finite."""
    arr2d = np.asarray(arr2d, dtype=float)
    if arr2d.ndim == 1:
        arr2d = arr2d[None, :]
    n_rows, ncols = arr2d.shape
    w = left + right + 1
    if ncols < w:
        return np.zeros_like(arr2d, dtype=bool)
    finite2d = np.isfinite(arr2d).astype(np.int8)
    wins = sliding_window_view(finite2d, window_shape=(w,), axis=1)
    ok = wins.sum(axis=-1) == w
    mask = np.zeros_like(arr2d, dtype=bool)
    mask[:, left : ncols - right] = ok
    return mask


def head_zero_inplace(arr2d: np.ndarray, valid_mask2d: np.ndarray) -> None:
    """Fill leading NaNs preceding the first valid element with 0.0 in-place."""
    any_true = valid_mask2d.any(axis=1)
    first = np.where(any_true, valid_mask2d.argmax(axis=1), -1)
    for r, f in enumerate(first):
        if f > 0:
            arr2d[r, :f] = 0.0


# ---- from src/cwa/signal/cumulative.py ----------------------------------------

def cumulative_sum_with_condition_fast(data: np.ndarray) -> np.ndarray:
    """Cumulative sum reset on NaN, clipped at zero lower bound (1D array)."""
    y = np.asarray(data, dtype=float)
    out = np.full_like(y, np.nan)
    finite = np.isfinite(y)
    if not finite.any():
        return out
    idx = np.flatnonzero(finite)
    cuts = np.where(np.diff(idx) > 1)[0]
    starts = np.r_[0, cuts + 1]
    ends = np.r_[cuts, idx.size - 1]
    for s, e in zip(starts, ends):
        seg_idx = idx[s : e + 1]
        c = np.cumsum(y[seg_idx])
        c = np.maximum(c, 0.0)
        out[seg_idx] = c
    return out


def cumulative_batch(arr2d: np.ndarray) -> np.ndarray:
    """Batch cumulative sum clipped at zero over a 2D array [N, points]."""
    arr2d = np.asarray(arr2d, dtype=float)
    if arr2d.ndim == 1:
        return cumulative_sum_with_condition_fast(arr2d)[None, :]
    out = np.full_like(arr2d, np.nan)
    for row_index, row in enumerate(arr2d):
        out[row_index] = cumulative_sum_with_condition_fast(row)
    return out


def ratio_batch(
    arr2d: np.ndarray, points: int = RATIO_POINTS, batch_size: int = 100
) -> np.ndarray:
    """Ratio of forward vs backward window sums over a 2D array [N, points]."""
    arr2d = np.asarray(arr2d, dtype=float)
    if arr2d.ndim == 1:
        arr2d = arr2d[None, :]
    out = np.full_like(arr2d, np.nan)
    w = 2 * points + 1
    if arr2d.shape[1] < w:
        return out
    for start in range(0, arr2d.shape[0], batch_size):
        end = min(start + batch_size, arr2d.shape[0])
        block = arr2d[start:end]
        win = sliding_window_view(block, window_shape=w, axis=1)
        prev = win[..., :points]
        nxt = win[..., -points:]
        prev_sum = prev.sum(axis=-1)
        next_sum = nxt.sum(axis=-1)
        ok = (
            np.isfinite(prev).all(axis=-1)
            & np.isfinite(nxt).all(axis=-1)
            & (prev_sum != 0)
        )
        vals = np.full(ok.shape, np.nan)
        vals[ok] = next_sum[ok] / prev_sum[ok]
        out[start:end, points : points + vals.shape[1]] = vals
    return out


def normalize_max_100(base_array: np.ndarray) -> np.ndarray:
    """Normalize waveforms such that the maximum value equals 100.0%.

    Parameters
    ----------
    base_array : np.ndarray
        1D or 2D array of cumulative waveform values.

    Returns
    -------
    np.ndarray
        Array scaled from 0% to 100%, preserving input dimensions.
    """
    arr = np.asarray(base_array, dtype=float)
    is_1d = arr.ndim == 1
    if is_1d:
        arr2d = arr[None, :]
    else:
        arr2d = arr

    row_max = np.full(arr2d.shape[0], np.nan)
    finite_rows = np.isfinite(arr2d).any(axis=1)
    if finite_rows.any():
        row_max[finite_rows] = np.nanmax(arr2d[finite_rows], axis=1)

    scaled = np.full_like(arr2d, np.nan)
    valid_scale = np.isfinite(row_max) & (row_max != 0)
    if valid_scale.any():
        scaled[valid_scale] = (
            arr2d[valid_scale] / row_max[valid_scale, None] * 100.0
        )

    return scaled[0] if is_1d else scaled


def normalize_endpoint_100(base_array: np.ndarray) -> np.ndarray:
    """Normalize cumulative waveforms such that the endpoint (rightmost finite value) equals 100.0%.

    Parameters
    ----------
    base_array : np.ndarray
        1D or 2D array of cumulative waveform values.

    Returns
    -------
    np.ndarray
        Array scaled from 0% to 100% relative to the endpoint value, preserving input dimensions.
    """
    arr = np.asarray(base_array, dtype=float)
    is_1d = arr.ndim == 1
    if is_1d:
        arr2d = arr[None, :]
    else:
        arr2d = arr

    row_endpoint = np.full(arr2d.shape[0], np.nan)
    for i in range(arr2d.shape[0]):
        row = arr2d[i]
        finite_idx = np.flatnonzero(np.isfinite(row))
        if finite_idx.size > 0:
            row_endpoint[i] = row[finite_idx[-1]]

    scaled = np.full_like(arr2d, np.nan)
    valid_scale = np.isfinite(row_endpoint) & (row_endpoint != 0)
    if valid_scale.any():
        scaled[valid_scale] = (
            arr2d[valid_scale] / row_endpoint[valid_scale, None] * 100.0
        )

    return scaled[0] if is_1d else scaled


# ---- from src/cwa/signal/slope.py ---------------------------------------------

def calculate_slope_fast(
    time_data: np.ndarray, data: np.ndarray, half: int = SLOPE_HALF
) -> np.ndarray:
    """Calculate slope for a single 1D waveform using moving linear regression."""
    y = np.asarray(data, dtype=float)
    n = y.size
    w = 2 * half + 1
    if n < w:
        return np.full(n, np.nan)

    td = np.asarray(time_data, dtype=float)
    diffs = np.diff(td)
    dt = float(diffs[np.isfinite(diffs)][0]) if np.isfinite(diffs).any() else 1.0

    x = np.arange(-half, half + 1, dtype=float)
    denom = np.sum(x * x) * dt

    fin = np.isfinite(y).astype(int)
    fin_win = sliding_window_view(fin, window_shape=w).sum(axis=1)
    all_ok = fin_win == w

    y0 = np.nan_to_num(y, nan=0.0)
    xy = np.convolve(y0, x[::-1], mode="valid")

    slope_center = np.full(xy.shape, np.nan)
    if all_ok.any():
        slope_center[all_ok] = xy[all_ok] / denom

    out = np.full(n, np.nan)
    out[half : half + slope_center.size] = slope_center
    return out


def slope_batch(
    time_data: np.ndarray,
    arr2d: np.ndarray,
    half: int = SLOPE_HALF,
    batch_size: int = 100,
) -> np.ndarray:
    """Calculate 1st-derivative velocity waveforms over a 2D array [N, points]."""
    arr2d = np.asarray(arr2d, dtype=float)
    if arr2d.ndim == 1:
        arr2d = arr2d[None, :]
    out = np.full_like(arr2d, np.nan)
    w = 2 * half + 1
    if arr2d.shape[1] < w:
        return out
    td = np.asarray(time_data, dtype=float)
    diffs = np.diff(td)
    dt = float(diffs[np.isfinite(diffs)][0]) if np.isfinite(diffs).any() else 1.0
    x = np.arange(-half, half + 1, dtype=float)
    denom = np.sum(x * x) * dt
    for start in range(0, arr2d.shape[0], batch_size):
        end = min(start + batch_size, arr2d.shape[0])
        block = arr2d[start:end]
        win = sliding_window_view(block, window_shape=w, axis=1)
        ok = np.isfinite(win).all(axis=-1)
        vals = np.full(ok.shape, np.nan)
        vals[ok] = (
            np.einsum("rnk,k->rn", np.nan_to_num(win, nan=0.0), x)[ok] / denom
        )
        out[start:end, half : half + vals.shape[1]] = vals
    return out


# ---- from src/cwa/coagulation/tetc.py -----------------------------------------

@dataclass(frozen=True)
class TeTcResult:
    """Structured container holding all Te/Tc timing metrics for a batch of waveforms."""

    te1: np.ndarray
    tc1: np.ndarray
    te1_tc1: np.ndarray
    te2: np.ndarray
    tc2: np.ndarray
    te2_tc2: np.ndarray
    te2_end_indices: list[int | None]

    def to_dataframe(self, ids: Sequence[str] | np.ndarray | None = None) -> pd.DataFrame:
        """Convert metrics to a pandas DataFrame, optionally prepending an ID column."""
        data: dict[str, Sequence] = {
            "Te1": self.te1,
            "Tc1": self.tc1,
            "Te1_Tc1": self.te1_tc1,
            "Te2": self.te2,
            "Tc2": self.tc2,
            "Te2_Tc2": self.te2_tc2,
        }
        if ids is not None:
            return pd.DataFrame({"ID": ids, **data})
        return pd.DataFrame(data)


def search_te_tc(
    cumulative_array: np.ndarray,
    ratio_array: np.ndarray,
    time_data: np.ndarray,
    *,
    ratio_threshold: float = 1.05,
    AD_threshold: float = 250.0,
    search_start_time: float = 15.0,
    coag_ratio: float = 0.5,
    te_tc_cutoff: float = 1.8,
) -> TeTcResult:
    """Identify Te/Tc timing metrics from pre-calculated cumulative and ratio arrays.

    Parameters
    ----------
    cumulative_array : np.ndarray
        2D array of cumulative waveform values [N, points].
    ratio_array : np.ndarray
        2D array of moving ratio values [N, points].
    time_data : np.ndarray
        1D array of time values in seconds [points].
    ratio_threshold : float
        Ratio threshold below which coagulation plateau candidate is detected.
    AD_threshold : float
        Minimum cumulative amplitude threshold.
    search_start_time : float
        Minimum time (sec) before which candidates are ignored.
    coag_ratio : float
        Fraction of plateau amplitude defining coagulation time Tc (default: 0.5).
    te_tc_cutoff : float
        Maximum ratio of Te/Tc to consider a valid termination point (default: 1.8).

    Returns
    -------
    TeTcResult
        Container holding Te1, Tc1, Te2, Tc2, Te1_Tc1, Te2_Tc2, and te2_end_indices.
    """
    cumulative_array = np.asarray(cumulative_array, dtype=float)
    ratio_array = np.asarray(ratio_array, dtype=float)
    time_data = np.asarray(time_data, dtype=float)

    n_rows = cumulative_array.shape[0] if cumulative_array.ndim >= 1 else 0
    if n_rows == 0:
        empty = np.array([], dtype=float)
        return TeTcResult(
            te1=empty,
            tc1=empty,
            te1_tc1=empty,
            te2=empty,
            tc2=empty,
            te2_tc2=empty,
            te2_end_indices=[],
        )

    te1_list: list[float] = []
    tc1_list: list[float] = []
    te1_tc1_list: list[float] = []
    te2_list: list[float] = []
    tc2_list: list[float] = []
    te2_tc2_list: list[float] = []
    te2_end_idx_list: list[int | None] = []

    for idx in range(n_rows):
        cum_values = cumulative_array[idx]
        ratios = ratio_array[idx]

        finite_ratio = np.isfinite(ratios)
        finite_cum = np.isfinite(cum_values)
        finite_time = np.isfinite(time_data)

        mask = (
            finite_ratio
            & finite_cum
            & finite_time
            & (ratios < ratio_threshold)
            & (cum_values >= AD_threshold)
            & (time_data >= search_start_time)
        )
        valid_idx = np.where(mask)[0]

        Te1 = Tc1 = Te2 = Tc2 = Te1_Tc1 = Te2_Tc2 = np.nan
        te2_end_idx: int | None = None

        for end_idx in valid_idx:
            end_val = cum_values[end_idx]
            if not np.isfinite(end_val):
                continue
            threshold_val = end_val * coag_ratio
            if not np.isfinite(threshold_val):
                continue

            tc_mask = np.isfinite(cum_values) & (cum_values >= threshold_val)
            tc_idx = np.where(tc_mask)[0]
            if tc_idx.size == 0:
                continue

            te_candidate = time_data[end_idx]
            tc_candidate = time_data[tc_idx[0]]
            te_tc = te_candidate / tc_candidate if tc_candidate != 0 else np.inf

            if np.isnan(Te1):
                Te1 = te_candidate
                Tc1 = tc_candidate
                Te1_Tc1 = Te1 / Tc1 if Tc1 != 0 else np.nan

            if te_tc <= te_tc_cutoff:
                Te2 = te_candidate
                Tc2 = tc_candidate
                Te2_Tc2 = te_tc
                te2_end_idx = int(end_idx)
                break

        te1_list.append(Te1)
        tc1_list.append(Tc1)
        te1_tc1_list.append(Te1_Tc1)
        te2_list.append(Te2)
        tc2_list.append(Tc2)
        te2_tc2_list.append(Te2_Tc2)
        te2_end_idx_list.append(te2_end_idx)

    return TeTcResult(
        te1=np.array(te1_list, dtype=float),
        tc1=np.array(tc1_list, dtype=float),
        te1_tc1=np.array(te1_tc1_list, dtype=float),
        te2=np.array(te2_list, dtype=float),
        tc2=np.array(tc2_list, dtype=float),
        te2_tc2=np.array(te2_tc2_list, dtype=float),
        te2_end_indices=te2_end_idx_list,
    )


# ---- from src/cwa/coagulation/trimming.py -------------------------------------

def apply_te2_trimming(
    arr2d: np.ndarray,
    te2_end_indices: Sequence[int | None],
    *,
    inplace: bool = False,
) -> np.ndarray:
    """Trim waveforms by setting points strictly after the Te2 termination point to NaN.

    Parameters
    ----------
    arr2d : np.ndarray
        2D waveform array [N, points] (or 1D waveform [points]).
    te2_end_indices : Sequence[int | None]
        Index of the Te2 reaction completion point for each waveform.
        If an element is None, the corresponding waveform is not trimmed.
    inplace : bool, default False
        Whether to modify arr2d in-place.

    Returns
    -------
    np.ndarray
        Waveform array where columns > end_idx are replaced with np.nan.
    """
    arr = np.asarray(arr2d, dtype=float)
    is_1d = arr.ndim == 1
    if is_1d:
        out = arr[None, :] if inplace else arr[None, :].copy()
    else:
        out = arr if inplace else arr.copy()

    n_rows, n_cols = out.shape
    if len(te2_end_indices) != n_rows:
        raise ValueError(
            f"Length of te2_end_indices ({len(te2_end_indices)}) "
            f"does not match waveform rows ({n_rows})"
        )

    for r, end_idx in enumerate(te2_end_indices):
        if end_idx is None:
            continue
        idx_val = int(end_idx)
        if idx_val < 0:
            continue
        cut_from = idx_val + 1
        if cut_from < n_cols:
            out[r, cut_from:] = np.nan

    return out[0] if is_1d else out


# ---- from src/cwa/plotting/waveforms.py ---------------------------------------

def align_waveform_time(
    time_series: np.ndarray,
    value_series: np.ndarray,
    align_mode: str = "off",
    rise_thr_ratio: float = 0.1,
    tc2_val: Optional[float] = None,
) -> np.ndarray:
    """
    Align the time axis of a waveform based on a reference point.

    Parameters
    ----------
    time_series : np.ndarray
        Array of time points (seconds).
    value_series : np.ndarray
        Array of waveform values (photometric/speed/height).
    align_mode : str, default 'off'
        Alignment mode:
        - 'off': no alignment, use original time
        - 'peak': t=0 at peak value (maximum)
        - 'rise': t=0 at first time value exceeds rise_thr_ratio * max_value
        - 'tc2': t=0 at tc2_val
    rise_thr_ratio : float, default 0.1
        Ratio of maximum to determine rise onset (e.g. 10% height).
    tc2_val : float, optional
        Pre-computed coagulation time Tc2 in seconds.

    Returns
    -------
    np.ndarray
        Shifted time series.
    """
    t = np.asarray(time_series, dtype=float)
    v = np.asarray(value_series, dtype=float)

    if align_mode.lower() == "peak":
        valid_mask = np.isfinite(v)
        if np.any(valid_mask):
            peak_idx = np.nanargmax(v)
            return t - t[peak_idx]
    elif align_mode.lower() == "rise":
        valid_mask = np.isfinite(v)
        if np.any(valid_mask):
            v_max = np.nanmax(v)
            v_min = np.nanmin(v)
            thr = v_min + (v_max - v_min) * rise_thr_ratio
            above = np.where(v >= thr)[0]
            if len(above) > 0:
                return t - t[above[0]]
    elif align_mode.lower() == "tc2" and tc2_val is not None and np.isfinite(tc2_val):
        return t - float(tc2_val)

    return t


# ---- derived waveforms (follows src/cwa/signal/derive.py::derive_waveforms) -------------

TIME_STEP_SEC = 0.1
MEDIAN_HALF = 20  # Mn of the 01 batch


def time_axis(n_points: int, step: float = TIME_STEP_SEC) -> np.ndarray:
    """Time of each prof point: 0.1, 0.2, ... seconds (same labels as the 01 batch)."""
    return np.round(step * np.arange(1, n_points + 1), 1)


@dataclass
class Derived:
    """Derived waveforms for N records on one time axis, and Te/Tc per record."""

    time: np.ndarray
    raw: np.ndarray
    cumulative: np.ndarray
    scaled: np.ndarray            # 0-100 % (maximum = 100)
    endpoint_scaled: np.ndarray   # 0-100 % (last point = 100)
    slope: np.ndarray             # 1st derivative of ``scaled`` (%/s)
    acceleration: np.ndarray      # 2nd derivative (%/s^2), slope of ``slope``
    tetc: pd.DataFrame            # Te1, Tc1, Te2, Tc2, Te1_Tc1, Te2_Tc2


def derive_batch(
    raw2d: np.ndarray,
    time_data: np.ndarray,
    *,
    window_end_sec: Optional[float] = None,
    coag_ratio: float = 0.5,
    do_trim: bool = False,
    batch_size: int = 100,
) -> Derived:
    """Moving average -> diff -> median -> cumulative -> Te/Tc -> 0-100 % -> slope -> acceleration."""
    raw2d = np.asarray(raw2d, dtype=float)
    if raw2d.ndim == 1:
        raw2d = raw2d[None, :]
    time_data = np.asarray(time_data, dtype=float)
    if window_end_sec is not None:
        keep = time_data <= float(window_end_sec) + 1e-9
        raw2d = raw2d[:, keep]
        time_data = time_data[keep]

    if raw2d.shape[1] == 0:  # every record empty: nothing to derive
        empty = np.full(raw2d.shape, np.nan)
        nan = np.full(raw2d.shape[0], np.nan)
        tetc = pd.DataFrame({k: nan for k in ["Te1", "Tc1", "Te1_Tc1", "Te2", "Tc2", "Te2_Tc2"]})
        return Derived(time_data, raw2d, empty, empty, empty, empty, empty, tetc)

    work =moving_average_batch(raw2d, AnF=4, AnB=4, batch_size=batch_size)
    diff = adjacent_diff(work)
    med = median_batch(diff, Mn=MEDIAN_HALF, batch_size=batch_size)
    cumulative = cumulative_batch(med)
    ratio = ratio_batch(cumulative, points=RATIO_POINTS, batch_size=batch_size)
    tetc = search_te_tc(cumulative_array=cumulative, ratio_array=ratio, time_data=time_data,
                        coag_ratio=coag_ratio, te_tc_cutoff=1.8)
    trimmed = apply_te2_trimming(cumulative, tetc.te2_end_indices, inplace=False) if do_trim else cumulative
    scaled = normalize_max_100(trimmed)

    slope = slope_batch(time_data, scaled, half=SLOPE_HALF, batch_size=batch_size)
    core = window_all_finite_mask_2d(scaled, left=max(MEDIAN_HALF, SLOPE_HALF), right=SLOPE_HALF)
    mask = core & np.isfinite(raw2d)
    slope[~mask] = np.nan
    head_zero_inplace(slope, mask)

    # The repo's viewer takes the acceleration as the slope (half=10) of the velocity waveform.
    acceleration = slope_batch(time_data, slope, half=SLOPE_HALF, batch_size=batch_size)

    return Derived(
        time=time_data,
        raw=raw2d,
        cumulative=trimmed,
        scaled=scaled,
        endpoint_scaled=normalize_endpoint_100(trimmed),
        slope=slope,
        acceleration=acceleration,
        tetc=tetc.to_dataframe(),
    )
