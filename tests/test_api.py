"""Tests for FastAPI backend endpoints."""

from __future__ import annotations

import sys
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from api.main import app
from make_demo_batch import build_batch

client = TestClient(app)


@pytest.fixture(scope="module")
def demo_batch_dir(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("api_demo")
    build_batch(root / "b6000", n_samples=4, profile_n=6000, seed=1, start_internal=18001)
    return root


@pytest.fixture(scope="module", autouse=True)
def setup_batch(demo_batch_dir):
    folder = demo_batch_dir / "b6000"
    res = client.post("/api/batches/load", json={"folder_path": str(folder)})
    assert res.status_code == 200


def test_health():
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}

    # Compatibility health endpoints
    compat_res = client.get("/_stcore/health")
    assert compat_res.status_code == 200
    assert "ok" in compat_res.text


def test_spa_serving():
    res = client.get("/")
    assert res.status_code == 200
    assert "text/html" in res.headers.get("content-type", "")


def test_settings_get_and_post():
    res = client.get("/api/settings")
    assert res.status_code == 200

    update_res = client.post("/api/settings", json={"extra": {"test_key": "test_val"}})
    assert update_res.status_code == 200
    assert update_res.json().get("test_key") == "test_val"


def test_list_folders(demo_batch_dir):
    res = client.get("/api/batches/folders", params={"root_path": str(demo_batch_dir)})
    assert res.status_code == 200
    folders = res.json()
    assert len(folders) == 1
    assert folders[0]["has_prof"] is True


def test_summary():
    res = client.get("/api/batches/summary")
    assert res.status_code == 200
    summary = res.json()
    assert summary["name"] == "b6000"
    assert summary["total_records"] > 0
    assert "APTT" in summary["items_list"] or "PT" in summary["items_list"]


def test_query_records():
    res = client.post("/api/batches/records", json={"limit": 5})
    assert res.status_code == 200
    data = res.json()
    assert data["total"] > 0
    assert len(data["records"]) <= 5
    assert "Tc2(計算)" in data["records"][0]


def test_derive_waveforms():
    req = {
        "positions": [0, 1],
        "align": "off",
        "baseline": False,
        "thin": True,
    }
    res = client.post("/api/waveforms/derive", json=req)
    assert res.status_code == 200
    data = res.json()
    assert len(data["series"]) == 2
    s0 = data["series"][0]
    assert len(s0["time"]) > 0
    assert len(s0["raw"]) == len(s0["time"])
    assert len(s0["scaled"]) == len(s0["time"])
    assert len(s0["slope"]) == len(s0["time"])


def test_waveform_detail():
    res = client.get("/api/waveforms/detail/1")
    assert res.status_code == 200
    data = res.json()
    assert data["no"] == 1
    assert "calculated" in data
    assert "Tc2" in data["calculated"]
    assert "record_info" in data


def test_export_csv():
    # Table CSV
    table_res = client.get("/api/export/table-csv")
    assert table_res.status_code == 200
    assert table_res.headers["content-type"].startswith("text/csv")
    assert b"No" in table_res.content

    # Waveforms CSV
    wf_res = client.post("/api/export/waveforms-csv", json={"positions": [0, 1], "kind": "raw"})
    assert wf_res.status_code == 200
    assert wf_res.headers["content-type"].startswith("text/csv")


def test_load_chromogenic_standalone_csv():
    demo_csv = ROOT / "demo_data" / "261022_比色項目csvの例.csv"
    if not demo_csv.is_file():
        pytest.skip("261022_比色項目csvの例.csv not found")

    res = client.post("/api/batches/load", json={"csv_path": str(demo_csv)})
    assert res.status_code == 200
    summary = res.json()
    assert summary["modes"] == ["比色項目"]
    assert summary["total_records"] > 0

    # Query records
    rec_res = client.post("/api/batches/records", json={"mode": "比色項目", "limit": 10})
    assert rec_res.status_code == 200
    recs = rec_res.json()["records"]
    assert len(recs) > 0
    assert recs[0]["測定モード"] == "比色項目"

    # Derive waveforms with abs_slope
    wf_res = client.post("/api/waveforms/derive", json={"positions": [0], "align": "off", "ref_point_idx": 4})
    assert wf_res.status_code == 200
    wf_data = wf_res.json()
    assert len(wf_data["series"]) == 1
    s0 = wf_data["series"][0]
    assert s0["mode"] == "比色項目"
    assert s0["abs_slope"] is not None
    assert len(s0["abs_slope"]) == len(s0["time"])
    assert s0["base_aligned"] is not None
    assert abs(s0["base_aligned"][4]) < 1e-6

    # Test summary has time_points
    assert len(summary["time_points"]) > 0

    # Detail test
    det_res = client.get(f"/api/waveforms/detail/{recs[0]['No']}?ref_point_idx=4")
    assert det_res.status_code == 200
    det_data = det_res.json()
    assert det_data["base_aligned"] is not None
    assert abs(det_data["base_aligned"][4]) < 1e-6

    # Export test
    exp_res = client.post("/api/export/waveforms-csv", json={"positions": [0], "kind": "base_aligned", "ref_point_idx": 4})
    assert exp_res.status_code == 200
    assert exp_res.headers["content-type"].startswith("text/csv")


