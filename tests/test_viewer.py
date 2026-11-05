"""Tests on synthetic batches (tools/make_demo_batch.py). No real data is used."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import cp3000  # noqa: E402
from cp3000.batch import csv_attributes_and_items  # noqa: E402
from make_demo_batch import build_batch  # noqa: E402


@pytest.fixture(scope="module")
def demo(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("demo")
    build_batch(root / "b6000", n_samples=8, profile_n=6000, seed=1, start_internal=18001)
    build_batch(root / "b3600", n_samples=4, profile_n=3600, seed=2, start_internal=19001)
    return root


def test_find_folders_and_files(demo):
    folders = cp3000.find_batch_folders(demo)
    assert {f.name for f in folders} == {"b6000", "b3600"}
    files = cp3000.find_batch_files(demo / "b6000")
    assert [p.name for p in files.prof] == ["prof01.dat"]
    assert [p.name for p in files.log] == ["LOG01.dat"]
    assert files.csv[0].name.endswith("CSV_data.csv")


@pytest.mark.parametrize("name,n_points,n_samples", [("b6000", 6000, 8), ("b3600", 3600, 4)])
def test_full_join(demo, name, n_points, n_samples):
    f = cp3000.find_batch_files(demo / name)
    b = cp3000.load_batch(f.prof[0], f.csv[0], f.log[0])
    assert b.profile_n == n_points
    # 2 items per sample + one re-measured sample (2 more waveforms)
    assert len(b.records) == 2 * n_samples + 2
    assert b.table["CSV対応"].all()
    assert b.table["依頼No"].nunique() == n_samples
    assert b.table["再測定"].sum() == 4
    assert set(b.table["項目名"]) == {"APTT", "PT"}
    assert (b.table["エラーフラグ"] != 0).sum() == 1
    assert b.warnings == []
    # table row i <-> prof record i
    assert (b.table["No"].to_numpy() == np.arange(1, len(b.records) + 1)).all()


def test_tc2_close_to_device_value(demo):
    f = cp3000.find_batch_files(demo / "b6000")
    b = cp3000.load_batch(f.prof[0], f.csv[0], f.log[0])
    t, m = b.matrix(range(len(b.records)))
    d = cp3000.derive_batch(m, t)
    first = ~b.table["再測定"] | ~b.table.duplicated(["依頼No", "項目番号"])
    diff = (d.tetc["Tc2"] - b.table["測定値"].astype(float))[first.to_numpy()]
    assert np.nanmax(np.abs(diff)) < 1.0


def test_prof_only_and_csv_without_log(demo):
    f = cp3000.find_batch_files(demo / "b6000")
    b = cp3000.load_batch(f.prof[0])
    assert len(b.table) == 18 and not b.table["CSV対応"].any()
    assert b.table["項目名"].str.startswith("項目").all()
    b2 = cp3000.load_batch(f.prof[0], f.csv[0], None)
    assert set(b2.table["項目名"]) == {"APTT", "PT"}  # names from the CSV item master
    assert any("LOG がない" in w for w in b2.warnings)


def test_subset_derivation_matches_full(demo):
    f = cp3000.find_batch_files(demo / "b6000")
    b = cp3000.load_batch(f.prof[0], f.csv[0], f.log[0])
    t, m = b.matrix(range(len(b.records)))
    full = cp3000.derive_batch(m, t)
    t2, m2 = b.matrix([3, 1])
    sub = cp3000.derive_batch(m2, t2)
    n = len(t2)
    assert np.allclose(sub.slope[0], full.slope[3, :n], equal_nan=True)
    assert np.allclose(sub.tetc["Tc2"].to_numpy(), full.tetc["Tc2"].to_numpy()[[3, 1]], equal_nan=True)


def test_csv_without_attribute_column():
    header = ["依頼No.", "PID", "受付日時", "検体名", "CWAPTN(sec)", "", "CWAPTL(sec)", "_1"]
    body = [["0001", "S1", "2026/01/01", "N1", "28.5", "", "30.2", ""]]
    attrs, items = csv_attributes_and_items(header, body)
    assert list(attrs.columns) == ["依頼No_norm", "依頼No.", "SID", "受付日時", "検体名", "検体ﾊﾞｰｺｰﾄﾞ"]
    assert items["項目名"].tolist() == ["CWAPTN", "CWAPTL"]


def test_empty_waveforms_do_not_crash(tmp_path):
    rec = bytearray(16) + bytes(3600 * 2)  # all zero -> data count 0
    rec[0:2] = (5).to_bytes(2, "little")
    (tmp_path / "prof01.dat").write_bytes(bytes(rec) * 2)
    b = cp3000.load_batch(tmp_path / "prof01.dat")
    t, m = b.matrix([0, 1])
    d = cp3000.derive_batch(m, t)
    assert d.tetc["Tc2"].isna().all()
    assert any("データ数 0" in w for w in b.warnings)


def test_raw_folder_is_not_written(demo):
    folder = demo / "b3600"
    before = sorted(p.name for p in folder.iterdir())
    f = cp3000.find_batch_files(folder)
    cp3000.load_batch(f.prof[0], f.csv[0], f.log[0])
    assert sorted(p.name for p in folder.iterdir()) == before


def test_app_renders(demo, tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest

    app_dir = tmp_path / "app"
    shutil.copytree(ROOT / "cp3000", app_dir / "cp3000")
    shutil.copy(ROOT / "app.py", app_dir / "app.py")
    (app_dir / "settings.json").write_text('{"root": "%s"}' % str(demo).replace("\\", "\\\\"), encoding="utf-8")
    monkeypatch.syspath_prepend(str(app_dir))
    at = AppTest.from_file(str(app_dir / "app.py"), default_timeout=120)
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert at.title[0].value.endswith("b6000")
    align = [s.label for s in at.sidebar.selectbox].index("時間軸のそろえ方")
    for mode in ["tc2", "peak", "rise", "off"]:
        at.sidebar.selectbox[align].set_value(mode).run()
        assert not at.exception, (mode, [e.value for e in at.exception])
    at.sidebar.selectbox[0].set_value("b3600").run()
    assert not at.exception
    assert at.title[0].value.endswith("b3600")


def test_csv_only_batch_and_derivation(demo):
    syn_csv = demo / "b6000" / "b6000_CSV_data.csv"
    b_syn = cp3000.load_batch(syn_csv)
    assert b_syn.prof_path is None
    assert b_syn.csv_path == syn_csv
    assert b_syn.profile_n == 127
    assert len(b_syn.records) == 16
    assert b_syn.table["CSV対応"].all()
    d_syn = b_syn.derive(range(len(b_syn.records)))
    assert d_syn.scaled.shape == (16, 127)
    assert d_syn.tetc["Tc2"].notna().all()

    csv_path = ROOT / "demo_data" / "250326CSV_data.csv"
    if not csv_path.is_file():
        return
    b = cp3000.load_batch(None, csv_path)
    b_pos = cp3000.load_batch(csv_path)
    assert b.prof_path is None
    assert b.csv_path == csv_path
    assert b.profile_n == 127
    assert len(b.records) == 125
    assert len(b_pos.records) == 125
    assert b.table["依頼No"].nunique() == 14
    assert b.table["項目名"].nunique() == 13
    assert b.table["CSV対応"].all()
    assert b.table.loc[0, "SID"] == "Request-0001"
    assert b.table.loc[0, "属性"] == "Cal_409RBV"

    t, m = b.matrix(range(len(b.records)))
    assert t.shape == (127,)
    assert np.isclose(t[0], 0.0) and np.isclose(t[1], 2.8) and np.isclose(t[-1], 352.8)
    assert m.shape == (125, 127)

    d = b.derive(range(len(b.records)))
    assert d.scaled.shape == (125, 127)
    assert d.slope.shape == (125, 127)
    assert d.acceleration.shape == (125, 127)
    assert int(d.tetc["Tc2"].notna().sum()) >= 110
    # 0001 CWAPTN (row 0) and CAPTTn (row 6)
    assert 13.5 <= float(d.tetc.loc[0, "Tc2"]) <= 15.5
    assert 27.0 <= float(d.tetc.loc[6, "Tc2"]) <= 29.5


def test_app_renders_csv_only(demo, tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest

    src_csv = ROOT / "demo_data" / "250326CSV_data.csv"
    target_name = "250326CSV_data.csv" if src_csv.is_file() else "b6000_CSV_data.csv"
    shutil.copy2(src_csv if src_csv.is_file() else (demo / "b6000" / "b6000_CSV_data.csv"), demo / target_name)
    app_dir = tmp_path / "app_csv"
    shutil.copytree(ROOT / "cp3000", app_dir / "cp3000")
    shutil.copy(ROOT / "app.py", app_dir / "app.py")
    (app_dir / "settings.json").write_text('{"root": "%s"}' % str(demo).replace("\\", "\\\\"), encoding="utf-8")
    monkeypatch.syspath_prepend(str(app_dir))
    at = AppTest.from_file(str(app_dir / "app.py"), default_timeout=120)
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert target_name in at.sidebar.selectbox[0].options
    at.sidebar.selectbox[0].set_value(target_name).run()
    assert not at.exception, [e.value for e in at.exception]
    assert at.title[0].value.endswith(Path(target_name).stem)
    align = [s.label for s in at.sidebar.selectbox].index("時間軸のそろえ方")
    for mode in ["tc2", "peak", "rise", "off"]:
        at.sidebar.selectbox[align].set_value(mode).run()
        assert not at.exception, (mode, [e.value for e in at.exception])


def test_csv_variable_and_mixed_time_intervals(tmp_path, monkeypatch):
    """Verify CSV profiles work with arbitrary and mixed time intervals across measurement modes."""
    from streamlit.testing.v1 import AppTest

    def make_coag_curve(t: np.ndarray, tc: float, amp: float = 1500.0, width: float = 4.5) -> np.ndarray:
        return np.round(amp / (1.0 + np.exp(-(t - tc) / width))).astype(float)

    # Three records with different measurement intervals (0.5s, 1.4s, 4.8s) and point counts
    t0 = np.round(np.arange(0, 127) * 0.5, 2)   # 0.5s step (up to 63.0s), Tc ~ 25s
    v0 = make_coag_curve(t0, tc=25.0)
    t1 = np.round(np.arange(0, 127) * 1.4, 2)   # 1.4s step (up to 176.4s), Tc ~ 32s
    v1 = make_coag_curve(t1, tc=32.0)
    t2 = np.round(np.arange(0, 100) * 4.8, 2)   # 4.8s step (100 pts, up to 475.2s), Tc ~ 45s
    v2 = make_coag_curve(t2, tc=45.0)

    lines = [
        "依頼No.,SID,検体ﾊﾞｰｺｰﾄﾞ,測定日,属性,PT(sec),,APTT(sec),,Fbg(sec),",
        "0001,S-01,,2026/03/26,ModeMix,25.0,,32.0,,45.0,",
        "依頼No.,項目名,項目番号,測光ﾎﾟｰﾄ,処理値,フラグ,ﾌﾟﾛﾌｧｲﾙ",
        "0001,PT,1,1,25.0,," + ",".join(f"{x:g}" for x in t0),
        ",,,,0,," + ",".join(f"{int(x)}" for x in v0),
        "0001,APTT,2,2,32.0,," + ",".join(f"{x:g}" for x in t1),
        ",,,,0,," + ",".join(f"{int(x)}" for x in v1),
        "0001,Fbg,3,3,45.0,," + ",".join(f"{x:g}" for x in t2),
        ",,,,0,," + ",".join(f"{int(x)}" for x in v2),
    ]
    csv_file = tmp_path / "mixed_mode_CSV_data.csv"
    csv_file.write_bytes("\r\n".join(lines).encode("cp932"))

    b = cp3000.load_batch(csv_file)
    assert len(b.records) == 3
    assert b.time_step_summary() == "0.5〜4.8秒間隔"
    assert b.profile_n_summary() == "100〜127 点/レコード"
    assert b.table["時間間隔(秒)"].tolist() == [0.5, 1.4, 4.8]
    assert np.allclose(b.record_time(0), t0)
    assert np.allclose(b.record_time(1), t1)
    assert np.allclose(b.record_time(2), t2)

    d = b.derive([0, 1, 2])
    assert d.times is not None and len(d.times) == 3
    assert np.allclose(d.time_at(0), t0)
    assert np.allclose(d.time_at(1), t1)
    assert np.allclose(d.time_at(2), t2)
    assert abs(float(d.tetc.loc[0, "Tc2"]) - 25.0) < 1.5
    assert abs(float(d.tetc.loc[1, "Tc2"]) - 32.0) < 1.5
    assert abs(float(d.tetc.loc[2, "Tc2"]) - 45.0) < 2.5

    # Also verify UI rendering on the mixed-interval CSV batch
    app_dir = tmp_path / "app_mix"
    shutil.copytree(ROOT / "cp3000", app_dir / "cp3000")
    shutil.copy(ROOT / "app.py", app_dir / "app.py")
    (app_dir / "settings.json").write_text('{"root": "%s"}' % str(csv_file).replace("\\", "\\\\"), encoding="utf-8")
    monkeypatch.syspath_prepend(str(app_dir))
    at = AppTest.from_file(str(app_dir / "app.py"), default_timeout=120)
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert at.title[0].value.endswith("mixed_mode_CSV_data")
    align = [s.label for s in at.sidebar.selectbox].index("時間軸のそろえ方")
    for mode in ["tc2", "peak", "rise", "off"]:
        at.sidebar.selectbox[align].set_value(mode).run()
        assert not at.exception, (mode, [e.value for e in at.exception])


