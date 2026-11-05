@echo off
setlocal
cd /d "%~dp0\web"

set "NODEPATH=%USERPROFILE%\.tools\node-v20"
if exist "%NODEPATH%\node.exe" (
    set "PATH=%NODEPATH%;%PATH%"
)

echo Vite 開発サーバーを起動しています (http://localhost:5173)...
echo バックエンドの FastAPI (http://localhost:8000) も別ターミナルで起動してください。
echo.

call npm run dev
pause
