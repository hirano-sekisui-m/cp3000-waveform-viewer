@echo off
setlocal
cd /d "%~dp0"

echo ========================================================
echo   CP3000 波形ビューワー (React + FastAPI 3層構成)
echo ========================================================
echo.

if not exist ".venv\Scripts\python.exe" (
    echo [1/3] Python 仮想環境 (.venv) を作成しています...
    python -m venv .venv
    if errorlevel 1 (
        echo [エラー] Python の仮想環境の作成に失敗しました。
        pause
        exit /b 1
    )
)

echo [2/3] 必要なライブラリを確認しています...
.venv\Scripts\python -m pip install -r requirements.txt --quiet

echo [3/3] ビューワーサーバー (FastAPI) を起動しています...
echo ブラウザで http://localhost:8000 を開きます。
echo 終了するにはこのウィンドウを閉じるか Ctrl+C を押してください。
echo.

start http://localhost:8000
.venv\Scripts\python -m uvicorn api.main:app --host 127.0.0.1 --port 8000 --reload
pause
