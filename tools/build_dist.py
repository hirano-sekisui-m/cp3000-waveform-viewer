"""Build distributable zip packages for CP3000 波形ビューワー.

Usage:
    python tools/build_dist.py

Outputs in dist/:
    CP3000Viewer_<version>_full.zip   Full bundle (embeddable Python 3.12 + packages + app + demo_data)
    CP3000Viewer_app_<version>.zip    Lightweight app-only bundle for update_viewer.bat
    latest.txt                        Version manifest for the shared folder
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import socket
import ssl
import subprocess
import sys
import time
import urllib.request
import zipfile
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
DIST_FILES_DIR = ROOT / "dist_files"
BUILD_DIR = ROOT / "build"
CACHE_DIR = BUILD_DIR / "cache"
DIST_DIR = ROOT / "dist"

PYTHON_VERSION = "3.12.10"
RUNTIME_REV = "r1"
DEFAULT_RUNTIME_VERSION = f"py{PYTHON_VERSION}-{RUNTIME_REV}"

EMBED_ZIP_NAME = f"python-{PYTHON_VERSION}-embed-amd64.zip"
EMBED_ZIP_URL = f"https://www.python.org/ftp/python/{PYTHON_VERSION}/{EMBED_ZIP_NAME}"
EMBED_ZIP_SHA256 = "4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3"

PTH_CONTENT = (
    "python312.zip\r\n"
    ".\r\n"
    "Lib\\site-packages\r\n"
    "..\\app\r\n"
    "import site\r\n"
)

START_BAT_CONTENT = """\
@echo off
setlocal
cd /d "%~dp0"

if not exist "%~dp0runtime\\python.exe" (
    echo [エラー] 必要なファイルが見つかりません。先に zip をすべて展開してください。
    if not defined CP3000_NO_PAUSE pause
    exit /b 1
)
if not exist "%~dp0app\\app.py" (
    echo [エラー] app\\app.py が見つかりません。先に zip をすべて展開してください。
    if not defined CP3000_NO_PAUSE pause
    exit /b 1
)

if not exist "%~dp0user" mkdir "%~dp0user"
set "CP3000_SETTINGS=%~dp0user\\settings.json"
set "PYTHONNOUSERSITE=1"
if not defined CP3000_PORT set "CP3000_PORT=8510"

set "CTL=%~dp0runtime\\viewer_ctl.py"
if not exist "%CTL%" set "CTL=%~dp0app\\viewer_ctl.py"

"%~dp0runtime\\python.exe" "%CTL%" --root "%~dp0." prelaunch --port %CP3000_PORT%
set "PRE_RC=%ERRORLEVEL%"
if "%PRE_RC%"=="10" exit /b 0
if not "%PRE_RC%"=="0" (
    if not defined CP3000_NO_PAUSE pause
    exit /b %PRE_RC%
)

echo CP3000 波形ビューワーを起動しています...
echo この画面を閉じるとビューワーが終了します。
echo.

start "" /b "%~dp0runtime\\python.exe" "%CTL%" --root "%~dp0." wait-and-open --port %CP3000_PORT%
"%~dp0runtime\\python.exe" -m streamlit run "%~dp0app\\app.py" --server.address 127.0.0.1 --server.port %CP3000_PORT% --server.headless true 2> "%~dp0user\\last_error.log"
set "ST_RC=%ERRORLEVEL%"
if not "%ST_RC%"=="0" (
    echo.
    echo [エラー] ビューワーの起動に失敗しました。エラー内容を user\\last_error.log に保存しました。
    if exist "%~dp0user\\last_error.log" type "%~dp0user\\last_error.log"
    if not defined CP3000_NO_PAUSE pause
    exit /b %ST_RC%
)
exit /b 0
"""

UPDATE_BAT_CONTENT = """\
@echo off
setlocal
cd /d "%~dp0"

if not exist "%~dp0runtime\\python.exe" (
    echo [エラー] 必要なファイルが見つかりません。先に zip をすべて展開してください。
    if not defined CP3000_NO_PAUSE pause
    exit /b 1
)

if not defined CP3000_PORT set "CP3000_PORT=8510"
set "PYTHONNOUSERSITE=1"

set "CTL=%~dp0runtime\\viewer_ctl.py"
if not exist "%CTL%" set "CTL=%~dp0app\\viewer_ctl.py"

"%~dp0runtime\\python.exe" "%CTL%" --root "%~dp0." update --port %CP3000_PORT%
set "UPD_RC=%ERRORLEVEL%"
echo.
if not defined CP3000_NO_PAUSE pause
exit /b %UPD_RC%
"""


def write_cp932_crlf(path: Path, text: str) -> None:
    normalized = text.replace("\r\n", "\n").replace("\n", "\r\n")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(normalized.encode("cp932"))


def sync_dist_files_templates() -> None:
    """Ensure dist_files/start_viewer.bat and dist_files/update_viewer.bat exist in CP932 + CRLF."""
    write_cp932_crlf(DIST_FILES_DIR / "start_viewer.bat", START_BAT_CONTENT)
    write_cp932_crlf(DIST_FILES_DIR / "update_viewer.bat", UPDATE_BAT_CONTENT)


def read_app_version() -> str:
    init_py = (ROOT / "cp3000" / "__init__.py").read_text(encoding="utf-8")
    m = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']', init_py, re.M)
    if not m:
        raise RuntimeError("Could not find __version__ in cp3000/__init__.py")
    return m.group(1)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def ensure_embed_python_zip() -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    dest = CACHE_DIR / EMBED_ZIP_NAME
    if dest.is_file():
        actual = sha256_file(dest)
        if actual.lower() == EMBED_ZIP_SHA256.lower():
            print(f"[1/8] Using cached {EMBED_ZIP_NAME} (SHA-256 verified)")
            return dest
        print(f"[warn] Cached {EMBED_ZIP_NAME} had unexpected SHA-256 ({actual}), re-downloading...")
        dest.unlink()

    print(f"[1/8] Downloading {EMBED_ZIP_URL} ...")
    ctx = ssl.create_default_context()
    ctx.verify_flags &= ~getattr(ssl, "VERIFY_X509_STRICT", 0)
    with urllib.request.urlopen(EMBED_ZIP_URL, context=ctx, timeout=60) as resp:
        data = resp.read()
    dest.write_bytes(data)
    actual = sha256_file(dest)
    if actual.lower() != EMBED_ZIP_SHA256.lower():
        dest.unlink(missing_ok=True)
        raise RuntimeError(
            f"SHA-256 mismatch for {EMBED_ZIP_NAME}: expected {EMBED_ZIP_SHA256}, got {actual}"
        )
    print(f"[1/8] Downloaded and verified {EMBED_ZIP_NAME} ({len(data):,} bytes)")
    return dest


def unpack_runtime(embed_zip: Path, runtime_dir: Path) -> None:
    print(f"[2/8] Unpacking embeddable Python into {runtime_dir} ...")
    runtime_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(embed_zip, "r") as zf:
        zf.extractall(runtime_dir)
    pth_file = runtime_dir / "python312._pth"
    pth_file.write_bytes(PTH_CONTENT.encode("ascii"))


def install_packages(runtime_dir: Path, lock_file: Path) -> None:
    site_packages = runtime_dir / "Lib" / "site-packages"
    site_packages.mkdir(parents=True, exist_ok=True)
    print(f"[3/8] Installing locked wheels into {site_packages} ...")
    cmd = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--target",
        str(site_packages),
        "--python-version",
        "3.12",
        "--platform",
        "win_amd64",
        "--only-binary=:all:",
        "--no-compile",
        "--no-warn-script-location",
        "-r",
        str(lock_file),
    ]
    subprocess.run(cmd, check=True)


def prune_site_packages(site_packages: Path) -> None:
    """Remove bundled package unit tests, C/C++ headers, and static libs to save space."""
    print("[4/8] Pruning unnecessary files from site-packages ...")
    removed_dirs = 0
    removed_files = 0

    # Directories safe to remove (preserving streamlit/testing and pandas/_testing)
    prune_dir_names = {"tests", "test", "include", "share", "nbextension", "labextension", ".agents", "licenses", "__pycache__"}
    for root, dirs, _ in os.walk(site_packages, topdown=True):
        root_p = Path(root)
        rel_parts = root_p.relative_to(site_packages).parts
        for d in list(dirs):
            d_lower = d.lower()
            if d_lower in prune_dir_names:
                # Never touch streamlit/testing
                if rel_parts and rel_parts[0] == "streamlit" and d_lower == "testing":
                    continue
                target = root_p / d
                shutil.rmtree(target, ignore_errors=True)
                dirs.remove(d)
                removed_dirs += 1

    # Remove static libraries, C/Cython sources, JS source maps, .pyc, and debug symbols
    prune_exts = {".pdb", ".lib", ".a", ".c", ".cpp", ".cc", ".h", ".hpp", ".pyx", ".pxd", ".map", ".pyc"}
    for p in list(site_packages.rglob("*")):
        if p.is_file() and p.suffix.lower() in prune_exts:
            try:
                p.unlink()
                removed_files += 1
            except OSError:
                pass

    print(f"      Removed {removed_dirs} directories and {removed_files} dev/header files.")


def clean_env() -> dict[str, str]:
    """Return environment with PATH restricted to Windows system dirs (no external Python)."""
    sys_root = os.environ.get("SystemRoot", r"C:\Windows")
    env = os.environ.copy()
    env["PATH"] = f"{sys_root}\\System32;{sys_root};{sys_root}\\System32\\Wbem"
    env["PYTHONNOUSERSITE"] = "1"
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    return env


def copy_app_and_build_demo(pkg_root: Path, runtime_python: Path, app_version: str) -> None:
    print("[5/8] Copying app files and generating synthetic demo_data ...")
    app_dir = pkg_root / "app"
    app_dir.mkdir(parents=True, exist_ok=True)

    shutil.copy2(ROOT / "app.py", app_dir / "app.py")
    shutil.copytree(
        ROOT / "cp3000",
        app_dir / "cp3000",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        dirs_exist_ok=True,
    )
    if app_version != read_app_version():
        init_file = app_dir / "cp3000" / "__init__.py"
        text = init_file.read_text(encoding="utf-8")
        text = re.sub(r'^__version__\s*=\s*["\'][^"\']+["\']', f'__version__ = "{app_version}"', text, flags=re.M)
        init_file.write_text(text, encoding="utf-8")

    st_dir = app_dir / ".streamlit"
    st_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / ".streamlit" / "config.toml", st_dir / "config.toml")

    # Copy helper controller script into both app/ and runtime/
    shutil.copy2(DIST_FILES_DIR / "viewer_ctl.py", app_dir / "viewer_ctl.py")
    shutil.copy2(DIST_FILES_DIR / "viewer_ctl.py", pkg_root / "runtime" / "viewer_ctl.py")

    # Generate demo_data using the bundled runtime Python
    demo_dir = app_dir / "demo_data"
    subprocess.run(
        [str(runtime_python), str(ROOT / "tools" / "make_demo_batch.py"), "--out", str(demo_dir)],
        env=clean_env(),
        check=True,
    )
    sample_csv = ROOT / "demo_data" / "250326CSV_data.csv"
    if sample_csv.is_file():
        shutil.copy2(sample_csv, demo_dir / sample_csv.name)


def place_root_and_user_files(
    pkg_root: Path,
    app_version: str,
    runtime_version: str,
    update_source: str,
) -> None:
    print("[6/8] Writing launcher bat files, README.txt, VERSION.txt, and user/ defaults ...")
    sync_dist_files_templates()
    shutil.copy2(DIST_FILES_DIR / "start_viewer.bat", pkg_root / "start_viewer.bat")
    shutil.copy2(DIST_FILES_DIR / "update_viewer.bat", pkg_root / "update_viewer.bat")

    readme_text = (DIST_FILES_DIR / "README.txt").read_text(encoding="utf-8")
    (pkg_root / "README.txt").write_bytes(readme_text.replace("\r\n", "\n").replace("\n", "\r\n").encode("utf-8"))

    version_line = f"app={app_version} runtime={runtime_version}\r\n"
    (pkg_root / "VERSION.txt").write_bytes(version_line.encode("utf-8"))

    user_dir = pkg_root / "user"
    user_dir.mkdir(parents=True, exist_ok=True)
    (user_dir / "settings.json").write_bytes(b"{}\r\n")
    update_src_content = (
        "# 配布元の共有フォルダのパスを 1 行で記入してください\r\n"
        f"{update_source}\r\n"
    )
    (user_dir / "update_source.txt").write_bytes(update_src_content.encode("utf-8"))


def precompile_bytecode(pkg_root: Path, runtime_python: Path) -> None:
    print("[7/8] Pre-compiling app bytecode with compileall ...")
    subprocess.run(
        [
            str(runtime_python),
            "-m",
            "compileall",
            "-q",
            str(pkg_root / "app"),
            str(pkg_root / "runtime" / "viewer_ctl.py"),
        ],
        env=clean_env(),
        check=True,
    )


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def verify_bundle(pkg_root: Path, runtime_python: Path, expected_version: str) -> None:
    print("[8/8] Verifying bundle (isolated imports + Streamlit health check) ...")
    env = clean_env()
    env["CP3000_SETTINGS"] = str(pkg_root / "user" / "settings.json")
    env["PYTHONDONTWRITEBYTECODE"] = "1"

    # 1. Verify imports
    check_code = (
        "import streamlit, plotly, numpy, pandas, pyarrow, altair, cp3000; "
        f"assert cp3000.__version__ == {expected_version!r}, cp3000.__version__; "
        "print('      Imports OK: cp3000=' + cp3000.__version__ + ', streamlit=' + streamlit.__version__)"
    )
    subprocess.run([str(runtime_python), "-c", check_code], env=env, check=True)

    # 2. Verify Streamlit server launch and /_stcore/health response
    port = find_free_port()
    cmd = [
        str(runtime_python),
        "-m",
        "streamlit",
        "run",
        str(pkg_root / "app" / "app.py"),
        "--server.address",
        "127.0.0.1",
        "--server.port",
        str(port),
        "--server.headless",
        "true",
        "--browser.gatherUsageStats",
        "false",
    ]
    proc = subprocess.Popen(
        cmd,
        cwd=str(pkg_root),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    health_url = f"http://127.0.0.1:{port}/_stcore/health"
    ok = False
    try:
        deadline = time.monotonic() + 45.0
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                break
            try:
                with opener.open(health_url, timeout=1.0) as resp:
                    body = resp.read().decode("utf-8", errors="replace").strip().lower()
                    if resp.status == 200 and "ok" in body:
                        ok = True
                        break
            except Exception:
                pass
            time.sleep(0.3)
        if not ok:
            out, err = proc.communicate(timeout=5)
            raise RuntimeError(
                f"Streamlit health check failed on port {port}.\n"
                f"STDOUT: {out.decode('utf-8', errors='replace')}\n"
                f"STDERR: {err.decode('utf-8', errors='replace')}"
            )
        print(f"      Streamlit /_stcore/health responded OK on 127.0.0.1:{port}")
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()

    # Ensure user/settings.json stays clean for initial distribution
    (pkg_root / "user" / "settings.json").write_bytes(b"{}\r\n")


def make_zip_from_dir(source_dir: Path, zip_path: Path, include_top: bool = False) -> None:
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    if zip_path.exists():
        zip_path.unlink()
    base = source_dir.parent if include_top else source_dir

    def _entry_priority(p: Path) -> tuple[int, str]:
        rel = p.relative_to(source_dir)
        parts = rel.parts
        if len(parts) == 1:
            return (0, rel.as_posix().lower())
        if parts[0] == "user":
            return (1, rel.as_posix().lower())
        if parts[0] == "app":
            return (2, rel.as_posix().lower())
        return (3, rel.as_posix().lower())

    all_files = [p for p in source_dir.rglob("*") if p.is_file()]
    all_files.sort(key=_entry_priority)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for p in all_files:
            zf.write(p, p.relative_to(base))


def make_app_zip(pkg_root: Path, zip_path: Path, include_top: bool = False) -> None:
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    if zip_path.exists():
        zip_path.unlink()
    base = pkg_root.parent if include_top else pkg_root
    items = [
        pkg_root / "README.txt",
        pkg_root / "start_viewer.bat",
        pkg_root / "update_viewer.bat",
        pkg_root / "VERSION.txt",
    ]
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for item in items:
            if item.is_file():
                zf.write(item, item.relative_to(base))
        for p in sorted((pkg_root / "app").rglob("*")):
            if p.is_file():
                zf.write(p, p.relative_to(base))


def build(
    *,
    app_version: Optional[str] = None,
    runtime_version: str = DEFAULT_RUNTIME_VERSION,
    update_source: str = r"\\<サーバー>\<共有>\CP3000Viewer",
    out_dir: Path = DIST_DIR,
    staging_root: Optional[Path] = None,
    skip_verify: bool = False,
) -> tuple[Path, Path]:
    version = app_version or read_app_version()
    lock_file = ROOT / "requirements-lock.txt"
    if not lock_file.is_file():
        raise FileNotFoundError(f"Missing {lock_file}")

    embed_zip = ensure_embed_python_zip()

    stage_base = staging_root or (BUILD_DIR / "staging")
    pkg_root = stage_base / "CP3000Viewer"
    if pkg_root.exists():
        shutil.rmtree(pkg_root)

    runtime_dir = pkg_root / "runtime"
    unpack_runtime(embed_zip, runtime_dir)
    install_packages(runtime_dir, lock_file)
    prune_site_packages(runtime_dir / "Lib" / "site-packages")

    runtime_python = runtime_dir / "python.exe"
    copy_app_and_build_demo(pkg_root, runtime_python, version)
    place_root_and_user_files(pkg_root, version, runtime_version, update_source)
    precompile_bytecode(pkg_root, runtime_python)

    if not skip_verify:
        verify_bundle(pkg_root, runtime_python, version)

    out_dir.mkdir(parents=True, exist_ok=True)
    full_zip = out_dir / f"CP3000Viewer_{version}_full.zip"
    app_zip = out_dir / f"CP3000Viewer_app_{version}.zip"
    latest_txt = out_dir / "latest.txt"

    print(f"Creating {full_zip.name} and {app_zip.name} ...")
    make_zip_from_dir(pkg_root, full_zip, include_top=False)
    make_app_zip(pkg_root, app_zip, include_top=False)
    latest_txt.write_bytes(f"app={version} runtime={runtime_version}\r\n".encode("utf-8"))

    full_mb = full_zip.stat().st_size / (1024 * 1024)
    app_kb = app_zip.stat().st_size / 1024
    print(f"Done!\n  Full zip: {full_zip} ({full_mb:.1f} MB)\n  App zip : {app_zip} ({app_kb:.1f} KB)")
    return full_zip, app_zip


def main() -> int:
    ap = argparse.ArgumentParser(description="Build CP3000Viewer distributable zip packages.")
    ap.add_argument("--app-version", default=None, help="Override app version (default: from cp3000/__init__.py)")
    ap.add_argument("--runtime-version", default=DEFAULT_RUNTIME_VERSION, help="Runtime version tag")
    ap.add_argument(
        "--update-source",
        default=os.environ.get("CP3000_UPDATE_SOURCE", r"\\<サーバー>\<共有>\CP3000Viewer"),
        help="Default shared folder path written to user/update_source.txt",
    )
    ap.add_argument("--out-dir", default=str(DIST_DIR), help="Output directory for zip files")
    ap.add_argument("--skip-verify", action="store_true", help="Skip Streamlit server health check")
    args = ap.parse_args()

    build(
        app_version=args.app_version,
        runtime_version=args.runtime_version,
        update_source=args.update_source,
        out_dir=Path(args.out_dir),
        skip_verify=args.skip_verify,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
