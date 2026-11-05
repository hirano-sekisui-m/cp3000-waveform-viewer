@echo off
chcp 932 >nul
setlocal
cd /d "%~dp0"

if not exist "%~dp0runtime\python.exe" (
    echo [エラー] 必要なファイルが見つかりません。先に zip をすべて展開してください。
    if not defined CP3000_NO_PAUSE pause
    exit /b 1
)

if not exist "%~dp0user" mkdir "%~dp0user"
set "CP3000_SETTINGS=%~dp0user\settings.json"
set "PYTHONNOUSERSITE=1"
if not defined CP3000_PORT set "CP3000_PORT=8000"

set "CTL=%~dp0runtime\viewer_ctl.py"
if not exist "%CTL%" set "CTL=%~dp0app\viewer_ctl.py"

"%~dp0runtime\python.exe" "%CTL%" --root "%~dp0." prelaunch --port %CP3000_PORT%
set "PRE_RC=%ERRORLEVEL%"
if "%PRE_RC%"=="10" exit /b 0
if not "%PRE_RC%"=="0" (
    if not defined CP3000_NO_PAUSE pause
    exit /b %PRE_RC%
)

echo CP3000 波形ビューワー (React + FastAPI) を起動しています...
echo この画面を閉じるとビューワーが終了します。
echo.

start "" /b "%~dp0runtime\python.exe" "%CTL%" --root "%~dp0." wait-and-open --port %CP3000_PORT%
"%~dp0runtime\python.exe" -m uvicorn api.main:app --app-dir "%~dp0app" --host 127.0.0.1 --port %CP3000_PORT% 2> "%~dp0user\last_error.log"
set "UVICORN_RC=%ERRORLEVEL%"
if not "%UVICORN_RC%"=="0" (
    echo.
    echo [エラー] ビューワーの起動に失敗しました。エラー内容を user\last_error.log に保存しました。
    if exist "%~dp0user\last_error.log" type "%~dp0user\last_error.log"
    if not defined CP3000_NO_PAUSE pause
    exit /b %UVICORN_RC%
)
exit /b 0
