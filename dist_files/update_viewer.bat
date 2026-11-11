@echo off
chcp 932 >nul
setlocal
cd /d "%~dp0"

if not exist "%~dp0runtime\python.exe" (
    echo [エラー] 必要なファイルが見つかりません。先に zip をすべて展開してください。
    if not defined CP3000_NO_PAUSE pause
    exit /b 1
)

if not defined CP3000_PORT set "CP3000_PORT=8000"
set "PYTHONNOUSERSITE=1"

set "CTL=%~dp0runtime\viewer_ctl.py"
if not exist "%CTL%" set "CTL=%~dp0app\viewer_ctl.py"

"%~dp0runtime\python.exe" "%CTL%" --root "%~dp0." update --port %CP3000_PORT%
set "UPD_RC=%ERRORLEVEL%"
if not "%UPD_RC%"=="0" (
    echo.
    if not defined CP3000_NO_PAUSE pause
)
exit /b %UPD_RC%
