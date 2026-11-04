@echo off
rem CP3000 waveform viewer launcher (first run creates .venv and installs requirements)
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo [setup] creating .venv ...
  python -m venv .venv || goto :error
  ".venv\Scripts\python.exe" -m pip install --upgrade pip
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt || goto :error
)
if not exist "demo_data" ".venv\Scripts\python.exe" tools\make_demo_batch.py
start "" /b cmd /c "timeout /t 4 /nobreak >nul & start http://localhost:8510"
".venv\Scripts\python.exe" -m streamlit run app.py
goto :eof

:error
echo [error] setup failed. Check that Python 3.10+ is on PATH.
pause
