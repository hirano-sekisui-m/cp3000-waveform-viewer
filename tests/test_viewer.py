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
