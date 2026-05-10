@echo off
setlocal

cd /d "%~dp0"

set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"
if not exist "%PYTHON_EXE%" set "PYTHON_EXE=python"

echo Starting Global Macro Dashboard on http://localhost:8501
echo.
"%PYTHON_EXE%" -m streamlit run dashboard.py --server.port 8501

if errorlevel 1 (
    echo.
    echo Failed to start the dashboard.
    pause
)
