"""Integration tests for the distributable package (start_viewer.bat, update_viewer.bat, viewer_ctl.py).

Covers Section 8 of plan/CP3k_waveform_distributable-pkg_設計計画書.md:
- #1: Existing tests (tests/test_viewer.py) pass on bundled Python 3.12 runtime
- #2: Full zip and app zip exist and have valid structure
- #3 & #6: start_viewer.bat works with Python removed from PATH, in a folder with spaces and Japanese chars
- #4 & #5: Bundled demo_data renders and produces identical Te/Tc & CSV output to dev environment
- #8: Custom user/settings.json survives update_viewer.bat when updating app version
- #9: update_viewer.bat refuses to update while the viewer is running and leaves files untouched
- #10: Mid-update failure rolls back app_old -> app and VERSION.txt so original version still works
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import build_dist  # noqa: E402
import cp3000  # noqa: E402


def _clean_env(**extra: str) -> dict[str, str]:
    env = build_dist.clean_env()
    env["CP3000_NO_PAUSE"] = "1"
    env["CP3000_NO_BROWSER"] = "1"
    env["CP3000_NO_EXPLORER"] = "1"
    env.update(extra)
    return env


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _wait_health(port: int, timeout: float = 40.0) -> bool:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    url = f"http://127.0.0.1:{port}/_stcore/health"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with opener.open(url, timeout=1.0) as resp:
                body = resp.read().decode("utf-8", errors="replace").strip().lower()
                if resp.status == 200 and "ok" in body:
                    return True
        except Exception:
            pass
        time.sleep(0.25)
    return False


def _kill_tree(pid: int) -> None:
    subprocess.run(
        ["taskkill", "/F", "/T", "/PID", str(pid)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )


@pytest.fixture(scope="module")
def built_zips() -> tuple[Path, Path]:
    version = build_dist.read_app_version()
    full_zip = ROOT / "dist" / f"CP3000Viewer_{version}_full.zip"
    app_zip = ROOT / "dist" / f"CP3000Viewer_app_{version}.zip"
    if not full_zip.is_file() or not app_zip.is_file():
        build_dist.build()
    return full_zip, app_zip


@pytest.fixture(scope="module")
def extracted_jp_dir(tmp_path_factory, built_zips) -> Path:
    """Extract full zip into a directory containing spaces and Japanese characters."""
    full_zip, _ = built_zips
    pkg_dir = tmp_path_factory.mktemp("dist_test") / "空白 と 日本語 フォルダ" / "CP3000Viewer"
    pkg_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(full_zip, "r") as zf:
        zf.extractall(pkg_dir)
    if (pkg_dir / "CP3000Viewer" / "start_viewer.bat").is_file():
        pkg_dir = pkg_dir / "CP3000Viewer"
    assert (pkg_dir / "runtime" / "python.exe").is_file()
    assert (pkg_dir / "app" / "app.py").is_file()
    assert (pkg_dir / "start_viewer.bat").is_file()
    assert (pkg_dir / "update_viewer.bat").is_file()
    return pkg_dir


def test_01_existing_tests_pass_on_runtime_python(extracted_jp_dir):
    """#1: Existing tests (tests/test_viewer.py) pass on bundled Python 3.12 runtime."""
    runtime_py = extracted_jp_dir / "runtime" / "python.exe"
    venv_site = Path(pytest.__file__).resolve().parents[1]
    code = (
        f"import sys; sys.path.append({str(venv_site)!r}); "
        "import pytest; "
        f"raise SystemExit(pytest.main([{str(ROOT / 'tests' / 'test_viewer.py')!r}, '-q', '-p', 'no:cacheprovider']))"
    )
    res = subprocess.run(
        [str(runtime_py), "-c", code],
        cwd=str(ROOT),
        env=_clean_env(),
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, f"STDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"


def test_02_dev_vs_runtime_results_identical(extracted_jp_dir, tmp_path):
    """#5: Bundled runtime produces identical table and Te/Tc calculations as development Python."""
    demo_batch = extracted_jp_dir / "app" / "demo_data" / "demo_batch_001"
    files = cp3000.find_batch_files(demo_batch)
    dev_batch = cp3000.load_batch(files.prof[0], files.csv[0], files.log[0])
    t, m = dev_batch.matrix(range(len(dev_batch.records)))
    dev_derived = cp3000.derive_batch(m, t)

    dev_csv = tmp_path / "dev_table.csv"
    rt_csv = tmp_path / "rt_table.csv"
    dev_tetc_csv = tmp_path / "dev_tetc.csv"
    rt_tetc_csv = tmp_path / "rt_tetc.csv"

    dev_batch.table.to_csv(dev_csv, index=False, encoding="utf-8-sig")
    dev_derived.tetc.to_csv(dev_tetc_csv, index=False, encoding="utf-8-sig")

    runtime_py = extracted_jp_dir / "runtime" / "python.exe"
    script = (
        "import cp3000; "
        f"f = cp3000.find_batch_files({str(demo_batch)!r}); "
        "b = cp3000.load_batch(f.prof[0], f.csv[0], f.log[0]); "
        "t, m = b.matrix(range(len(b.records))); "
        "d = cp3000.derive_batch(m, t); "
        f"b.table.to_csv({str(rt_csv)!r}, index=False, encoding='utf-8-sig'); "
        f"d.tetc.to_csv({str(rt_tetc_csv)!r}, index=False, encoding='utf-8-sig')"
    )
    subprocess.run([str(runtime_py), "-c", script], env=_clean_env(), check=True)

    assert dev_csv.read_text(encoding="utf-8-sig") == rt_csv.read_text(encoding="utf-8-sig")
    df_dev = pd.read_csv(dev_tetc_csv)
    df_rt = pd.read_csv(rt_tetc_csv)
    assert np.allclose(df_dev.to_numpy(float), df_rt.to_numpy(float), equal_nan=True)


def test_03_unextracted_zip_warning(tmp_path):
    """Section 6: Opening start_viewer.bat or update_viewer.bat without extracting runtime stops with message."""
    shutil.copy2(ROOT / "dist_files" / "start_viewer.bat", tmp_path / "start_viewer.bat")
    res = subprocess.run(
        ["cmd.exe", "/c", str(tmp_path / "start_viewer.bat")],
        cwd=str(tmp_path),
        env=_clean_env(),
        capture_output=True,
    )
    out = res.stdout.decode("cp932", errors="replace")
    assert res.returncode == 1
    assert "先に zip をすべて展開してください" in out


def test_04_start_viewer_bat_without_python_on_path_and_double_click(extracted_jp_dir):
    """#3, #4, #6: start_viewer.bat runs from Japanese+space folder with no Python on PATH, and 2nd launch just opens browser."""
    port = _free_port()
    env = _clean_env(CP3000_PORT=str(port))
    bat = extracted_jp_dir / "start_viewer.bat"

    proc = subprocess.Popen(
        ["cmd.exe", "/c", str(bat)],
        cwd=str(extracted_jp_dir),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        assert _wait_health(port, timeout=40.0), "Streamlit server did not respond to /_stcore/health"

        # Second double-click while already running: should exit 0 immediately without starting a 2nd server
        res2 = subprocess.run(
            ["cmd.exe", "/c", str(bat)],
            cwd=str(extracted_jp_dir),
            env=env,
            capture_output=True,
            timeout=15,
        )
        out2 = res2.stdout.decode("cp932", errors="replace")
        assert res2.returncode == 0
        assert "すでに起動しています" in out2

        # #9: Running update_viewer.bat while viewer is running must refuse and make no changes
        share = extracted_jp_dir.parent / "mock_share_running"
        share.mkdir(parents=True, exist_ok=True)
        (share / "latest.txt").write_text("app=9.9.9 runtime=py3.12.10-r1\n", encoding="utf-8")
        (extracted_jp_dir / "user" / "update_source.txt").write_text(str(share) + "\n", encoding="utf-8")

        upd_res = subprocess.run(
            ["cmd.exe", "/c", str(extracted_jp_dir / "update_viewer.bat")],
            cwd=str(extracted_jp_dir),
            env=env,
            capture_output=True,
            timeout=15,
        )
        upd_out = upd_res.stdout.decode("cp932", errors="replace")
        assert upd_res.returncode == 2
        assert "起動中" in upd_out
        assert "app=0.1.0" in (extracted_jp_dir / "VERSION.txt").read_text(encoding="utf-8")
    finally:
        _kill_tree(proc.pid)
        try:
            proc.wait(timeout=5)
        except Exception:
            pass


def test_05_startup_failure_writes_last_error_log(extracted_jp_dir):
    """Section 6: If startup fails, error details are saved to user/last_error.log."""
    err_log = extracted_jp_dir / "user" / "last_error.log"
    err_log.unlink(missing_ok=True)
    port = _free_port()

    # Pass an invalid Streamlit config env var so prelaunch succeeds (0) and streamlit run fails immediately
    env = _clean_env(
        CP3000_PORT=str(port),
        CP3000_WAIT_TIMEOUT="1",
        STREAMLIT_SERVER_MAX_UPLOAD_SIZE="not_an_integer",
    )
    res = subprocess.run(
        ["cmd.exe", "/c", str(extracted_jp_dir / "start_viewer.bat")],
        cwd=str(extracted_jp_dir),
        env=env,
        capture_output=True,
        timeout=20,
    )
    out = res.stdout.decode("cp932", errors="replace")
    assert res.returncode != 0
    assert "last_error.log" in out
    assert err_log.is_file() and err_log.stat().st_size > 0


def _make_mock_app_zip(pkg_dir: Path, zip_path: Path, new_version: str, runtime_version: str = "py3.12.10-r1") -> None:
    """Create a valid CP3000Viewer_app_<new_version>.zip from the existing app/ folder."""
    stage = zip_path.parent / f"_stage_{new_version}" / "CP3000Viewer"
    if stage.exists():
        shutil.rmtree(stage)
    shutil.copytree(pkg_dir / "app", stage / "app")
    init_py = stage / "app" / "cp3000" / "__init__.py"
    txt = init_py.read_text(encoding="utf-8").replace('__version__ = "0.1.0"', f'__version__ = "{new_version}"')
    init_py.write_text(txt, encoding="utf-8")
    shutil.copy2(pkg_dir / "start_viewer.bat", stage / "start_viewer.bat")
    shutil.copy2(pkg_dir / "update_viewer.bat", stage / "update_viewer.bat")
    shutil.copy2(pkg_dir / "README.txt", stage / "README.txt")
    (stage / "VERSION.txt").write_text(f"app={new_version} runtime={runtime_version}\r\n", encoding="utf-8")
    build_dist.make_app_zip(stage, zip_path)
    shutil.rmtree(stage.parent, ignore_errors=True)


def test_06_update_rollback_on_failure_and_success_preserves_settings(extracted_jp_dir, tmp_path):
    """#8 & #10: Mid-update failure rolls back cleanly; normal update updates app and preserves user/settings.json."""
    share = tmp_path / "shared_folder"
    share.mkdir(parents=True, exist_ok=True)
    _make_mock_app_zip(extracted_jp_dir, share / "CP3000Viewer_app_0.2.0.zip", "0.2.0")
    (share / "latest.txt").write_text("app=0.2.0 runtime=py3.12.10-r1\r\n", encoding="utf-8")

    user_dir = extracted_jp_dir / "user"
    (user_dir / "update_source.txt").write_text(str(share) + "\r\n", encoding="utf-8")
    custom_settings = {"root": r"E:\CWA\data\raw", "last_batch": "batch_20261105"}
    (user_dir / "settings.json").write_text(json.dumps(custom_settings, ensure_ascii=False), encoding="utf-8")

    port = _free_port()
    upd_bat = extracted_jp_dir / "update_viewer.bat"

    # 1. #10: Simulate failure midway after renaming app -> app_old
    fail_env = _clean_env(CP3000_PORT=str(port), CP3000_SIMULATE_UPDATE_FAIL="1")
    res_fail = subprocess.run(
        ["cmd.exe", "/c", str(upd_bat)],
        cwd=str(extracted_jp_dir),
        env=fail_env,
        capture_output=True,
        timeout=20,
    )
    out_fail = res_fail.stdout.decode("cp932", errors="replace")
    assert res_fail.returncode == 1
    assert "元の版に戻しました" in out_fail
    assert not (extracted_jp_dir / "app_old").exists()
    assert (extracted_jp_dir / "app" / "app.py").is_file()
    assert "app=0.1.0" in (extracted_jp_dir / "VERSION.txt").read_text(encoding="utf-8")

    # Verify the rolled-back app still imports and reports 0.1.0
    runtime_py = extracted_jp_dir / "runtime" / "python.exe"
    chk = subprocess.run(
        [str(runtime_py), "-c", "import cp3000; assert cp3000.__version__ == '0.1.0'"],
        env=_clean_env(),
        check=False,
    )
    assert chk.returncode == 0

    # 2. #8: Run normal update (0.1.0 -> 0.2.0) and verify user/settings.json is preserved
    ok_env = _clean_env(CP3000_PORT=str(port))
    res_ok = subprocess.run(
        ["cmd.exe", "/c", str(upd_bat)],
        cwd=str(extracted_jp_dir),
        env=ok_env,
        capture_output=True,
        timeout=20,
    )
    out_ok = res_ok.stdout.decode("cp932", errors="replace")
    assert res_ok.returncode == 0, out_ok
    assert "更新が完了しました" in out_ok
    assert "app=0.2.0" in (extracted_jp_dir / "VERSION.txt").read_text(encoding="utf-8")
    assert json.loads((user_dir / "settings.json").read_text(encoding="utf-8")) == custom_settings

    chk2 = subprocess.run(
        [str(runtime_py), "-c", "import cp3000; assert cp3000.__version__ == '0.2.0'"],
        env=_clean_env(),
        check=False,
    )
    assert chk2.returncode == 0

    # 3. Running update again when already at 0.2.0 reports up-to-date
    res_up2date = subprocess.run(
        ["cmd.exe", "/c", str(upd_bat)],
        cwd=str(extracted_jp_dir),
        env=ok_env,
        capture_output=True,
        timeout=20,
    )
    out_up2date = res_up2date.stdout.decode("cp932", errors="replace")
    assert res_up2date.returncode == 0
    assert "最新です" in out_up2date

    # 4. When runtime version changes in latest.txt, prompts full replacement
    (share / "latest.txt").write_text("app=0.3.0 runtime=py3.12.10-r2\r\n", encoding="utf-8")
    res_rt = subprocess.run(
        ["cmd.exe", "/c", str(upd_bat)],
        cwd=str(extracted_jp_dir),
        env=ok_env,
        capture_output=True,
        timeout=20,
    )
    out_rt = res_rt.stdout.decode("cp932", errors="replace")
    assert res_rt.returncode == 0
    assert "全体の入れ替えが必要です" in out_rt
    assert "app=0.2.0" in (extracted_jp_dir / "VERSION.txt").read_text(encoding="utf-8")
