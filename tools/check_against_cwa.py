"""Check that this package gives the same results as the CWA-ML-tool code it was copied from.

Run with a Python that can import the CWA-ML-tool sources (numpy, pandas, openpyxl, pyarrow):

    <python> tools/check_against_cwa.py --cwa-src C:/Users/.../CWA-ML-tool/src --batch demo_data/demo_batch_001

The batch folder is copied to a temporary folder first, because the original merger writes
"LOG展開後.xlsx" next to the LOG file. Compared:
1. merger.merge_raw_inputs (CSV + LOG + prof join) vs cp3000.load_batch: 依頼No, SID, 項目名,
   測定値 and every waveform point, for each joined row.
2. cwa.signal.derive.derive_waveforms vs cp3000.derive_batch: 0-100 % waveform, velocity, Te/Tc.
3. Acceleration: the repo viewer's calculate_slope_fast(t, velocity, half=10) vs ours.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parents[1]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cwa-src", required=True)
    ap.add_argument("--batch", required=True)
    args = ap.parse_args()
    sys.path.insert(0, str(HERE))
    sys.path.insert(0, str(Path(args.cwa_src).resolve()))

    import cp3000
    from cwa.ingestion.merger import detect_in_folder, merge_raw_inputs
    from cwa.signal.derive import derive_waveforms
    from cwa.signal.slope import calculate_slope_fast

    failures = 0

    def check(label: str, ok: bool, detail: str = "") -> None:
        nonlocal failures
        failures += 0 if ok else 1
        print(f"[{'OK' if ok else 'NG'}] {label}{(' - ' + detail) if detail else ''}")

    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / Path(args.batch).name
        shutil.copytree(args.batch, work)
        csv_p, log_p, prof_p = detect_in_folder(work)
        _, _, wide = merge_raw_inputs(csv_p, log_p, prof_p, out_dir=None)
        ours = cp3000.load_batch(prof_p, csv_p, log_p)

    # 1. join ------------------------------------------------------------------------
    joined = wide.dropna(subset=["内部依頼No"])
    tcols = [c for c in wide.columns if str(c).replace(".", "", 1).isdigit()]
    n_rows = n_wave = 0
    for _, row in joined.iterrows():
        mine = ours.table[(ours.table["内部依頼No"] == row["内部依頼No"]) & (ours.table["項目番号"] == row["項目番号"])]
        if len(mine) != 1:
            check(f"row 内部依頼No={row['内部依頼No']} 項目番号={row['項目番号']}", False, f"{len(mine)} rows in ours")
            continue
        m = mine.iloc[0]
        same = (m["依頼No"] == row["依頼No_norm"] and m["SID"] == row["SID"]
                and m["項目名"] == row["項目名"] and m["測定値"] == row["測定値"])
        n_rows += same
        ref = pd.to_numeric(row[tcols], errors="coerce").to_numpy(dtype=float)
        ref = ref[np.isfinite(ref)]
        got = ours.records[int(mine.index[0])].data.astype(float)
        n_wave += bool(len(ref) == len(got) and np.array_equal(ref, got))
    check("join: 依頼No / SID / 項目名 / 測定値", n_rows == len(joined), f"{n_rows}/{len(joined)} rows")
    check("join: waveform points", n_wave == len(joined), f"{n_wave}/{len(joined)} waveforms")

    # 2. derived waveforms -------------------------------------------------------------
    t, m = ours.matrix(range(len(ours.records)))
    raw = pd.DataFrame(m, columns=[f"{x:.1f}" for x in t])
    raw.insert(0, "measurement_id", [str(i) for i in range(len(m))])
    for window in (None, 360.0):
        ref = derive_waveforms(raw, window_end_sec=window)
        got = cp3000.derive_batch(m, t, window_end_sec=window)
        tag = f"window={window}"
        check(f"derive {tag}: 0-100 %", np.allclose(ref.cumulative_scaled.iloc[:, 1:].to_numpy(float), got.scaled, equal_nan=True))
        check(f"derive {tag}: velocity", np.allclose(ref.slope.iloc[:, 1:].to_numpy(float), got.slope, equal_nan=True))
        cols = ["Te1", "Te2", "Tc1", "Tc2"]
        check(f"derive {tag}: Te/Tc", np.allclose(ref.te_tc[cols].to_numpy(float), got.tetc[cols].to_numpy(float), equal_nan=True))
        acc = np.vstack([calculate_slope_fast(got.time, v, half=10) for v in ref.slope.iloc[:, 1:].to_numpy(float)])
        check(f"derive {tag}: acceleration", np.allclose(acc, got.acceleration, equal_nan=True))

    print("ALL OK" if failures == 0 else f"{failures} check(s) failed")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
