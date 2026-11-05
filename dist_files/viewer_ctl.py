"""Helper utilities for launching and updating the distributable CP3000 waveform viewer.

Executed by start_viewer.bat and update_viewer.bat using the bundled runtime/python.exe.
Uses only Python standard library modules so that it never locks files inside app/ or site-packages/.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
import zipfile
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

DEFAULT_GITHUB_REPO = "hirano-sekisui-m/cp3000-waveform-viewer"


def _configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconf = getattr(stream, "reconfigure", None)
        if callable(reconf):
            try:
                reconf(errors="replace")
            except Exception:
                pass


def parse_version_text(text: str) -> Dict[str, str]:
    """Parse 'app=0.1.0 runtime=py3.12.10-r1' (space or newline separated) into a dict."""
    result: Dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        for token in line.split():
            if "=" in token:
                k, v = token.split("=", 1)
                result[k.strip()] = v.strip()
    return result


def read_update_source(user_dir: Path) -> Optional[Path]:
    """Read shared folder path from CP3000_UPDATE_SOURCE env var or user/update_source.txt."""
    env_src = os.environ.get("CP3000_UPDATE_SOURCE", "").strip()
    if env_src:
        return Path(env_src)
    src_file = user_dir / "update_source.txt"
    if not src_file.is_file():
        return None
    for enc in ("utf-8-sig", "cp932", "utf-8"):
        try:
            content = src_file.read_text(encoding=enc)
            break
        except Exception:
            content = ""
    for raw in content.splitlines():
        line = raw.strip().strip('"')
        if not line or line.startswith("#"):
            continue
        if "<" in line or ">" in line:
            return None
        return Path(line)
    return None


def is_port_open(host: str, port: int, timeout: float = 0.4) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def open_browser(url: str) -> None:
    if os.environ.get("CP3000_NO_BROWSER") == "1":
        print(f"[ブラウザ起動スキップ] {url}")
        return
    try:
        webbrowser.open(url)
    except Exception as exc:
        print(f"[注意] ブラウザを自動で開けませんでした ({exc})。{url} を開いてください。")


def open_explorer(folder: Path) -> None:
    if os.environ.get("CP3000_NO_EXPLORER") == "1":
        print(f"[エクスプローラー起動スキップ] {folder}")
        return
    try:
        if hasattr(os, "startfile"):
            os.startfile(str(folder))  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["explorer", str(folder)])
    except Exception as exc:
        print(f"[注意] フォルダを開けませんでした ({exc}): {folder}")


def _http_request(url: str, headers: Optional[Dict[str, str]] = None, timeout: float = 15.0) -> bytes:
    """Perform HTTP GET request with fallback for corporate SSL/TLS inspection environments."""
    hdrs = {"User-Agent": "CP3000Viewer"}
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(url, headers=hdrs)

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except (ssl.SSLError, urllib.error.URLError) as exc:
        err_str = str(exc).lower()
        if "ssl" in err_str or "certificate" in err_str or isinstance(exc, ssl.SSLError):
            unverified_ctx = ssl._create_unverified_context()
            with urllib.request.urlopen(req, context=unverified_ctx, timeout=timeout) as resp:
                return resp.read()
        raise


def _download_file(url: str, dest_path: Path, headers: Optional[Dict[str, str]] = None, timeout: float = 120.0) -> None:
    """Download file from url to dest_path with progress indication and SSL fallback."""
    hdrs = {"User-Agent": "CP3000Viewer"}
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(url, headers=hdrs)

    def _open():
        try:
            return urllib.request.urlopen(req, timeout=timeout)
        except (ssl.SSLError, urllib.error.URLError) as exc:
            err_str = str(exc).lower()
            if "ssl" in err_str or "certificate" in err_str or isinstance(exc, ssl.SSLError):
                return urllib.request.urlopen(req, context=ssl._create_unverified_context(), timeout=timeout)
            raise

    dest_path.parent.mkdir(parents=True, exist_ok=True)
    with _open() as resp:
        total_header = resp.getheader("Content-Length")
        total_bytes = int(total_header) if total_header and total_header.isdigit() else 0
        downloaded = 0
        chunk_size = 64 * 1024
        with open(dest_path, "wb") as f:
            while True:
                chunk = resp.read(chunk_size)
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)
                if total_bytes > 0:
                    pct = int(downloaded * 100 / total_bytes)
                    mb = downloaded / (1024 * 1024)
                    tot_mb = total_bytes / (1024 * 1024)
                    print(f"\rダウンロード中... {pct}% ({mb:.1f} MB / {tot_mb:.1f} MB)", end="", flush=True)
                else:
                    mb = downloaded / (1024 * 1024)
                    print(f"\rダウンロード中... {mb:.1f} MB", end="", flush=True)
        print()


def get_github_release_info(repo: str = DEFAULT_GITHUB_REPO) -> Dict[str, Any]:
    api_url = f"https://api.github.com/repos/{repo}/releases/latest"
    raw_json = _http_request(api_url, timeout=10.0)
    return json.loads(raw_json.decode("utf-8"))


def resolve_github_latest(repo: str = DEFAULT_GITHUB_REPO) -> Tuple[Dict[str, str], str, Optional[Dict[str, Any]]]:
    """Fetch latest release info from GitHub.

    Returns (version_dict, html_url, app_zip_asset_dict).
    """
    data = get_github_release_info(repo)
    html_url = data.get("html_url", f"https://github.com/{repo}/releases/latest")
    assets = data.get("assets", [])

    version_dict: Dict[str, str] = {}
    for asset in assets:
        if asset.get("name") == "latest.txt":
            try:
                asset_url = asset.get("url") or asset.get("browser_download_url")
                raw_txt = _http_request(asset_url, headers={"Accept": "application/octet-stream"}, timeout=10.0)
                version_dict = parse_version_text(raw_txt.decode("utf-8-sig", errors="replace"))
                break
            except Exception:
                pass

    if not version_dict.get("app"):
        tag = data.get("tag_name", "").lstrip("v").strip()
        if tag:
            version_dict["app"] = tag
        if "runtime" not in version_dict:
            version_dict["runtime"] = "py3.12.10-r1"

    latest_app = version_dict.get("app", "")
    target_zip_name = f"CP3000Viewer_app_{latest_app}.zip"
    app_zip_asset = None
    for asset in assets:
        if asset.get("name") == target_zip_name:
            app_zip_asset = asset
            break

    return version_dict, html_url, app_zip_asset


def _check_update_notice(root_dir: Path) -> None:
    """Optionally print a notice if latest version is available (shared folder or GitHub)."""
    try:
        version_file = root_dir / "VERSION.txt"
        if not version_file.is_file():
            return
        local = parse_version_text(version_file.read_text(encoding="utf-8-sig", errors="replace"))

        src = read_update_source(root_dir / "user")
        if src is not None and src.is_dir():
            latest_file = src / "latest.txt"
            if not latest_file.is_file():
                return
            latest = parse_version_text(latest_file.read_text(encoding="utf-8-sig", errors="replace"))
        else:
            repo = os.environ.get("CP3000_GITHUB_REPO", DEFAULT_GITHUB_REPO)
            latest, _, _ = resolve_github_latest(repo)

        if latest.get("app") and (latest.get("app") != local.get("app") or latest.get("runtime") != local.get("runtime")):
            print(f"[お知らせ] 新しい版があります (現在: {local.get('app', '?')} -> 最新: {latest.get('app')})。")
            print("           終了後に update_viewer.bat をダブルクリックして更新できます。")
    except Exception:
        pass


def cmd_prelaunch(root_dir: Path, port: int) -> int:
    url = f"http://localhost:{port}"
    if is_port_open("127.0.0.1", port):
        print(f"ビューワーはすでに起動しています。ブラウザを開きます ({url})。")
        open_browser(url)
        return 10
    _check_update_notice(root_dir)
    return 0


def cmd_wait_and_open(port: int, timeout: float) -> int:
    env_timeout = os.environ.get("CP3000_WAIT_TIMEOUT")
    if env_timeout:
        try:
            timeout = float(env_timeout)
        except ValueError:
            pass
    health_url = f"http://127.0.0.1:{port}/_stcore/health"
    app_url = f"http://localhost:{port}"
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with opener.open(health_url, timeout=1.0) as resp:
                body = resp.read().decode("utf-8", errors="replace").strip().lower()
                if resp.status == 200 and "ok" in body:
                    open_browser(app_url)
                    return 0
        except Exception:
            pass
        time.sleep(0.25)
    return 1


def _find_extracted_root(tmp_dir: Path) -> Optional[Path]:
    """Locate the directory inside tmp_dir that contains app/app.py."""
    if (tmp_dir / "app" / "app.py").is_file():
        return tmp_dir
    for child in tmp_dir.iterdir():
        if child.is_dir() and (child / "app" / "app.py").is_file():
            return child
    return None


def cmd_update(root_dir: Path, port: int, source_override: Optional[str] = None) -> int:
    os.chdir(root_dir)
    version_file = root_dir / "VERSION.txt"
    local_text = version_file.read_text(encoding="utf-8-sig", errors="replace") if version_file.is_file() else ""
    local = parse_version_text(local_text)
    local_app = local.get("app", "unknown")
    local_rt = local.get("runtime", "unknown")

    tmp_dir = root_dir / "_update_tmp"
    app_dir = root_dir / "app"
    app_old = root_dir / "app_old"

    configured_source = Path(source_override) if source_override else read_update_source(root_dir / "user")
    use_shared_folder = configured_source is not None and configured_source.is_dir()

    if use_shared_folder:
        source_dir = configured_source
        latest_file = source_dir / "latest.txt"
        if not latest_file.is_file():
            print(f"[エラー] 共有フォルダの latest.txt が見つかりません: {latest_file}")
            return 1

        latest = parse_version_text(latest_file.read_text(encoding="utf-8-sig", errors="replace"))
        latest_app = latest.get("app")
        latest_rt = latest.get("runtime")
        if not latest_app or not latest_rt:
            print(f"[エラー] latest.txt の形式が正しくありません: {latest_file}")
            return 1
        release_page_url = None
        app_zip_src: Optional[Path] = source_dir / f"CP3000Viewer_app_{latest_app}.zip"
        app_zip_asset = None
    else:
        # GitHub Releases mode
        repo = os.environ.get("CP3000_GITHUB_REPO", DEFAULT_GITHUB_REPO)
        print("GitHub Releases から最新版を確認しています...")
        try:
            latest, release_page_url, app_zip_asset = resolve_github_latest(repo)
        except Exception as exc:
            print(f"[エラー] 最新版の確認に失敗しました: {exc}")
            print("インターネット接続を確認するか、社内共有フォルダがある場合は")
            print("user\\update_source.txt にパスを記入してください。")
            return 1

        latest_app = latest.get("app")
        latest_rt = latest.get("runtime")
        if not latest_app or not latest_rt:
            print("[エラー] 最新版の情報を取得できませんでした。")
            return 1
        app_zip_src = None

    print(f"現在の版: app={local_app} runtime={local_rt}")
    print(f"最新の版: app={latest_app} runtime={latest_rt}")

    if latest_app == local_app and latest_rt == local_rt:
        print("お使いの CP3000 波形ビューワーは最新です。")
        return 0

    if latest_rt != local_rt:
        print(f"全体の入れ替えが必要です (runtime: {local_rt} -> {latest_rt})。")
        if use_shared_folder:
            print(f"共有フォルダから CP3000Viewer_{latest_app}_full.zip をコピーして展開してください。")
            open_explorer(source_dir)
        else:
            print(f"GitHub Releases から CP3000Viewer_{latest_app}_full.zip をダウンロードして展開してください。")
            if release_page_url:
                open_browser(release_page_url)
        return 0

    # App-only update: verify viewer is not running first
    if is_port_open("127.0.0.1", port):
        print("[エラー] ビューワーが起動中です。")
        print("ビューワーの黒い画面を閉じて終了してから、もう一度 update_viewer.bat を実行してください。")
        return 2

    # Clean tmp_dir
    if tmp_dir.exists():
        shutil.rmtree(tmp_dir, ignore_errors=True)
    tmp_dir.mkdir(parents=True, exist_ok=True)

    # Obtain app zip
    if use_shared_folder:
        if app_zip_src is None or not app_zip_src.is_file():
            print(f"[エラー] 更新ファイルが見つかりません: {app_zip_src}")
            return 1
        target_zip = app_zip_src
    else:
        if app_zip_asset is None:
            print(f"[エラー] GitHub Release に更新パッケージ (CP3000Viewer_app_{latest_app}.zip) が見つかりません。")
            return 1
        download_url = app_zip_asset.get("url") or app_zip_asset.get("browser_download_url")
        target_zip = tmp_dir / f"CP3000Viewer_app_{latest_app}.zip"
        print(f"最新版 (v{latest_app}) の更新パッケージをダウンロードしています...")
        try:
            _download_file(download_url, target_zip, headers={"Accept": "application/octet-stream"})
        except Exception as exc:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            print(f"[エラー] 更新パッケージのダウンロードに失敗しました: {exc}")
            return 1

    # Extract
    try:
        with zipfile.ZipFile(target_zip, "r") as zf:
            zf.extractall(tmp_dir)
        extracted_root = _find_extracted_root(tmp_dir)
        if extracted_root is None or not (extracted_root / "app" / "cp3000" / "__init__.py").is_file():
            raise RuntimeError("展開したファイルに app/app.py または app/cp3000 が含まれていません。")
    except Exception as exc:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        print(f"[エラー] 更新ファイルの展開に失敗しました: {exc}")
        return 1

    # Recover if a previous hard crash left app_old without app
    if not app_dir.exists() and app_old.exists():
        app_old.rename(app_dir)
    if app_old.exists():
        shutil.rmtree(app_old, ignore_errors=True)

    if app_dir.exists():
        app_dir.rename(app_old)

    try:
        if os.environ.get("CP3000_SIMULATE_UPDATE_FAIL") == "1":
            raise RuntimeError("更新途中の模擬エラー (CP3000_SIMULATE_UPDATE_FAIL=1)")

        shutil.move(str(extracted_root / "app"), str(app_dir))

        for fname in ("start_viewer.bat", "start_viewer_react.bat", "update_viewer.bat", "README.txt"):
            cand = extracted_root / fname
            if cand.is_file():
                shutil.copy2(cand, root_dir / fname)

        new_ctl = app_dir / "viewer_ctl.py"
        runtime_ctl = root_dir / "runtime" / "viewer_ctl.py"
        if new_ctl.is_file() and runtime_ctl.parent.is_dir():
            try:
                new_ctl_text = new_ctl.read_text(encoding="utf-8", errors="replace")
                if "DEFAULT_GITHUB_REPO" in new_ctl_text:
                    shutil.copy2(new_ctl, runtime_ctl)
            except Exception:
                shutil.copy2(new_ctl, runtime_ctl)

        version_file.write_text(f"app={latest_app} runtime={latest_rt}\n", encoding="utf-8")
    except Exception as exc:
        if app_dir.exists() and app_old.exists():
            shutil.rmtree(app_dir, ignore_errors=True)
        if app_old.exists() and not app_dir.exists():
            app_old.rename(app_dir)
        if local_text:
            try:
                version_file.write_text(local_text, encoding="utf-8")
            except Exception:
                pass
        shutil.rmtree(tmp_dir, ignore_errors=True)
        print(f"[エラー] 更新の途中で問題が発生したため、元の版に戻しました: {exc}")
        return 1

    shutil.rmtree(app_old, ignore_errors=True)
    shutil.rmtree(tmp_dir, ignore_errors=True)
    print(f"更新が完了しました (app={local_app} -> {latest_app})。")
    return 0


def main() -> int:
    _configure_stdio()
    root_default = Path(__file__).resolve().parents[1]
    ap = argparse.ArgumentParser(description="CP3000 波形ビューワー 起動・更新ヘルパー")
    ap.add_argument("--root", default=str(root_default), help="CP3000Viewer ルートフォルダ")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_pre = sub.add_parser("prelaunch")
    p_pre.add_argument("--port", type=int, default=8510)

    p_wait = sub.add_parser("wait-and-open")
    p_wait.add_argument("--port", type=int, default=8510)
    p_wait.add_argument("--timeout", type=float, default=60.0)

    p_upd = sub.add_parser("update")
    p_upd.add_argument("--port", type=int, default=8510)
    p_upd.add_argument("--source", default=None)

    args = ap.parse_args()
    root_dir = Path(args.root).resolve()

    if args.cmd == "prelaunch":
        return cmd_prelaunch(root_dir, args.port)
    if args.cmd == "wait-and-open":
        return cmd_wait_and_open(args.port, args.timeout)
    if args.cmd == "update":
        return cmd_update(root_dir, args.port, args.source)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
