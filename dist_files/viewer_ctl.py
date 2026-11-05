"""Helper utilities for launching and updating the distributable CP3000 waveform viewer.

Executed by start_viewer.bat and update_viewer.bat using the bundled runtime/python.exe.
Uses only Python standard library modules so that it never locks files inside app/ or site-packages/.
"""

from __future__ import annotations

import argparse
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser
import zipfile
from pathlib import Path
from typing import Dict, Optional


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


def _check_update_notice(root_dir: Path) -> None:
    """Optionally print a notice if latest.txt in the shared folder has a newer version."""
    try:
        src = read_update_source(root_dir / "user")
        if src is None:
            return
        latest_file = src / "latest.txt"
        version_file = root_dir / "VERSION.txt"
        if not latest_file.is_file() or not version_file.is_file():
            return
        latest = parse_version_text(latest_file.read_text(encoding="utf-8-sig", errors="replace"))
        local = parse_version_text(version_file.read_text(encoding="utf-8-sig", errors="replace"))
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

    source_dir = Path(source_override) if source_override else read_update_source(root_dir / "user")
    if source_dir is None:
        print("[エラー] 共有フォルダの場所が設定されていません。")
        print("user\\update_source.txt に配布元フォルダのパスを記入してください。")
        return 1

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

    print(f"現在の版: app={local_app} runtime={local_rt}")
    print(f"最新の版: app={latest_app} runtime={latest_rt}")

    if latest_app == local_app and latest_rt == local_rt:
        print("お使いの CP3000 波形ビューワーは最新です。")
        return 0

    if latest_rt != local_rt:
        print(f"全体の入れ替えが必要です (runtime: {local_rt} -> {latest_rt})。")
        print(f"共有フォルダから CP3000Viewer_{latest_app}_full.zip をコピーして展開してください。")
        open_explorer(source_dir)
        return 0

    # App-only update: verify viewer is not running first
    if is_port_open("127.0.0.1", port):
        print("[エラー] ビューワーが起動中です。")
        print("ビューワーの黒い画面を閉じて終了してから、もう一度 update_viewer.bat を実行してください。")
        return 2

    app_zip = source_dir / f"CP3000Viewer_app_{latest_app}.zip"
    if not app_zip.is_file():
        print(f"[エラー] 更新ファイルが見つかりません: {app_zip}")
        return 1

    tmp_dir = root_dir / "_update_tmp"
    app_dir = root_dir / "app"
    app_old = root_dir / "app_old"

    if tmp_dir.exists():
        shutil.rmtree(tmp_dir, ignore_errors=True)

    try:
        tmp_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(app_zip, "r") as zf:
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

        for fname in ("start_viewer.bat", "README.txt"):
            cand = extracted_root / fname
            if cand.is_file():
                shutil.copy2(cand, root_dir / fname)

        new_ctl = app_dir / "viewer_ctl.py"
        runtime_ctl = root_dir / "runtime" / "viewer_ctl.py"
        if new_ctl.is_file() and runtime_ctl.parent.is_dir():
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
