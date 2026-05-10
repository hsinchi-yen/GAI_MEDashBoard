@echo off
setlocal

for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8501 ^| findstr LISTENING') do (
    echo Stopping process %%a on port 8501...
    taskkill /PID %%a /F >nul 2>&1
)

echo Done.
