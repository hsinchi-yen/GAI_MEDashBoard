@echo off
setlocal

cd /d "%~dp0"

echo Building and starting Global Macro Dashboard via Docker...
echo.

docker compose up --build -d

if errorlevel 1 (
    echo.
    echo Failed to start Docker service. Make sure Docker Desktop is running.
    pause
    exit /b 1
)

echo.
echo Dashboard is starting at http://localhost:8501
echo Run "docker compose logs -f" to follow logs.
echo Run "docker compose down" to stop.
echo.
start http://localhost:8501
