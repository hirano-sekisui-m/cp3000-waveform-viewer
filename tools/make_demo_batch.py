"""Write synthetic CP3000 batches (CSV + LOG + prof) for trying the viewer without real data.

    python tools/make_demo_batch.py            # -> demo_data/demo_batch_001, demo_batch_002

All values are made up. The file layouts follow what the readers expect:
* *CSV_data.csv (cp932): section 1 (依頼No., SID, 検体ﾊﾞｰｺｰﾄﾞ, 測定日, 属性, item + D-flag pairs),
  a blank line, then section 2 (依頼No., 項目名, 項目番号, ...)
* LOG01.dat (cp932 text): "hh:mm:ss<内部依頼No-項目No> AnalRunSet:<表示依頼No>.255" and SInfo lines
* prof01.dat: 16-byte header + 6000 (or 3600) little-endian uint16 points per record, zero padded
"""

from __future__ import annotations

import argparse
import csv
import io
from pathlib import Path

import numpy as np

ITEMS = {"APTT": 25, "PT": 9}  # item name -> item number


def sigmoid_wave(t: np.ndarray, tc: float, amp: float, width: float, base: float,
                 rng: np.random.Generator, second: float = 0.0) -> np.ndarray:
    """Absorbance-like curve: baseline + rising sigmoid (+ optional slow second phase) + noise."""
    y = base + amp / (1.0 + np.exp(-(t - tc) / width))
    if second:
        y += second * amp / (1.0 + np.exp(-(t - tc * 1.6) / (width * 3)))
    y += rng.normal(0, 4.0, t.size)
    return np.clip(y, 1, 65535)


def build_batch(out: Path, *, n_samples: int, profile_n: int, seed: int, start_internal: int) -> None:
    rng = np.random.default_rng(seed)
    out.mkdir(parents=True, exist_ok=True)
    t = 0.1 * np.arange(1, profile_n + 1)

    kinds = ["正常", "延長(軽度)", "延長(高度)", "二相性"]
    samples = []
    for i in range(n_samples):
        kind = kinds[i % len(kinds)]
        aptt = {"正常": 30, "延長(軽度)": 48, "延長(高度)": 75, "二相性": 40}[kind] + rng.normal(0, 2)
        pt = 11.5 + rng.normal(0, 0.5) + (4 if kind == "延長(高度)" else 0)
        samples.append({"no": i + 1, "kind": kind, "APTT": aptt, "PT": pt,
                        "attr": "Control" if i == 0 else "Sample"})

    # --- LOG + prof ----------------------------------------------------------------------
    log = ["09:00:01 _readMasFlag True", "09:00:05 [PC]10[UNIT]0", "09:00:10 分析ｽﾀｰﾄ"]
    records = []
    csv_profiles = {}
    t_csv = np.round(2.8 * np.arange(127), 1)
    t_csv_idx = np.clip(np.round(t_csv * 10).astype(int) - 1, 0, profile_n - 1)
    internal = start_internal
    minute = 0
    runs = [(s, False) for s in samples] + [(samples[2], True)]  # one re-measurement
    for s, rerun in runs:
        minute += 1
        hh, mm = 9 + minute // 60, minute % 60
        for k, (name, item_no) in enumerate(ITEMS.items()):
            ts = f"{hh:02d}:{mm:02d}:{10 + k:02d}"
            log.append(f"{ts}<{internal}-{item_no}> AnalRunSet:{s['no']}.255 IraiUp{internal}:3")
            log.append(f"{ts}<{internal}-{item_no}> SInfo1 0:{internal}/{k + 1}/1/{s['no']}/{200 + s['no']}/")
            if name == "APTT":
                tc = s["APTT"] + (1.5 if rerun else 0)
                base = 2600.0
                y = sigmoid_wave(t, tc, amp=900 + rng.normal(0, 60), width=1.6 + tc / 40, base=base,
                                 rng=rng, second=0.25 if s["kind"] == "二相性" else 0.0)
                length = min(profile_n, int(max(180, tc * 4) * 10))
            else:
                tc = s["PT"]
                base = 2400.0
                y = sigmoid_wave(t, tc, amp=1200, width=0.8, base=base, rng=rng)
                length = min(profile_n, 900)
            data = np.zeros(profile_n, dtype="<u2")
            data[:length] = y[:length].astype("<u2")
            error_flag = 1 if (s["no"] == n_samples and name == "PT") else 0
            records.append((internal, item_no, k + 1, length // 10, error_flag, data))
            if not rerun:
                prof_vals = np.maximum(0, np.round(y[t_csv_idx] - base)).astype(int)
                prof_vals[0] = 0
                csv_profiles[(s["no"], name)] = prof_vals
        internal += 1
    log.append(f"{9 + (minute + 1) // 60:02d}:{(minute + 1) % 60:02d}:00 分析終了")
    (out / "LOG01.dat").write_bytes(("\r\n".join(log) + "\r\n").encode("cp932"))

    # --- CSV ---------------------------------------------------------------------------
    buf = io.StringIO()
    w = csv.writer(buf, quoting=csv.QUOTE_ALL, lineterminator="\r\n")
    w.writerow(["依頼No.", "SID", "検体ﾊﾞｰｺｰﾄﾞ", "測定日", "属性", "APTT(sec)", "", "PT(sec)", ""])
    for s in samples:
        w.writerow([f"{s['no']:04d}", f"DEMO-{seed:02d}-{s['no']:03d}", f"9{seed:02d}{s['no']:05d}",
                    "2026/11/01", s["attr"], f"{s['APTT']:.1f}", "", f"{s['PT']:.1f}", ""])
    w.writerow([])
    w.writerow(["依頼No.", "項目名", "", "測光ﾎﾟｰﾄ", "処理値", "", "ﾌﾟﾛﾌｧｲﾙ"])
    t_strs = [f"{x:.1f}" for x in t_csv]
    for s in samples:
        for k, (name, no) in enumerate(ITEMS.items()):
            v_strs = [str(int(v)) for v in csv_profiles[(s["no"], name)]]
            w.writerow([f"{s['no']:04d}", name, str(no), str(k + 1), f"{s[name]:.1f}", "", *t_strs])
            w.writerow(["", "", "", "", "0", "", *v_strs])
            w.writerow([" "])
    (out / f"{out.name}_CSV_data.csv").write_bytes(buf.getvalue().encode("cp932"))

    blob = bytearray()
    for internal_no, item_no, port, sec, error_flag, data in records:
        head = bytearray(16)
        head[0:2] = int(internal_no).to_bytes(2, "little")
        head[2] = item_no
        head[3] = port
        head[12:14] = int(error_flag).to_bytes(2, "little")
        head[14:16] = int(sec).to_bytes(2, "little")
        blob += head + data.tobytes()
    (out / "prof01.dat").write_bytes(bytes(blob))
    print(f"wrote {out} ({len(records)} waveforms, {profile_n} points/record)")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=str(Path(__file__).resolve().parents[1] / "demo_data"))
    args = ap.parse_args()
    root = Path(args.out)
    build_batch(root / "demo_batch_001", n_samples=12, profile_n=6000, seed=1, start_internal=18001)
    build_batch(root / "demo_batch_002", n_samples=6, profile_n=3600, seed=2, start_internal=19001)


if __name__ == "__main__":
    main()
