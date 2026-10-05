@echo off
REM ============================================================
REM  VisionQC AI MES - start backend + frontend (Windows)
REM  Opens two windows. Close a window (or Ctrl+C) to stop it.
REM  MySQL must be running (Windows service "MySQL80").
REM ============================================================
setlocal
cd /d "%~dp0"

if not exist "backend\.venv\Scripts\python.exe" (
    echo [ERROR] Dependencies are not installed. Run install.bat first.
    pause
    exit /b 1
)
if not exist "frontend\node_modules" (
    echo [ERROR] Frontend packages are not installed. Run install.bat first.
    pause
    exit /b 1
)

start "VisionQC backend :8000" /D "%~dp0backend" cmd /k .venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
start "VisionQC frontend :5173" /D "%~dp0frontend" cmd /k npm run dev

echo Starting... the browser will open in a few seconds.
echo   Screen  : http://localhost:5173   (admin / admin1234)
echo   API docs: http://localhost:8000/docs
timeout /t 6 /nobreak >nul
start "" http://localhost:5173
