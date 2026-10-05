@echo off
REM ============================================================
REM  VisionQC AI MES - install all dependencies (Windows)
REM  Double-click this file, or run "install.bat" in cmd.
REM  Safe to run again: it only adds what is missing.
REM  (Messages are in English so cmd does not break on Korean text.)
REM ============================================================
setlocal
cd /d "%~dp0"

echo.
echo ============================================================
echo   VisionQC AI MES - dependency install
echo ============================================================
echo.

REM ---------- 1. check tools ----------
echo [1/5] Checking Python and Node.js ...
where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] "python" was not found.
    echo         Install Python 3.11+ from https://www.python.org/downloads/
    echo         and CHECK "Add python.exe to PATH" during install.
    goto :fail
)
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)"
if errorlevel 1 (
    echo [ERROR] Python 3.11 or newer is required. Current version:
    python --version
    goto :fail
)
python --version

where npm >nul 2>nul
if errorlevel 1 (
    echo [ERROR] "npm" was not found. Install Node.js 20 LTS from https://nodejs.org/
    goto :fail
)
for /f "delims=" %%v in ('node --version') do echo Node.js %%v
echo.

REM ---------- 2. backend (Python virtual env + packages) ----------
echo [2/5] Backend: creating virtual env backend\.venv and installing packages ...
if not exist "backend\.venv\Scripts\python.exe" (
    python -m venv backend\.venv
    if errorlevel 1 goto :fail
)
backend\.venv\Scripts\python.exe -m pip install --upgrade pip
if errorlevel 1 goto :fail
backend\.venv\Scripts\python.exe -m pip install -r backend\requirements-dev.txt
if errorlevel 1 goto :fail
echo.

REM ---------- 3. vision client packages (for running its tests on this PC) ----------
echo [3/5] Vision client: installing packages into the same virtual env ...
backend\.venv\Scripts\python.exe -m pip install -r vision_client\requirements.txt
if errorlevel 1 goto :fail
echo.

REM ---------- 4. frontend (npm) ----------
echo [4/5] Frontend: npm install (first time can take a few minutes) ...
pushd frontend
call npm install
if errorlevel 1 (
    popd
    goto :fail
)
popd
echo.

REM ---------- 5. settings file ----------
echo [5/5] Settings file backend\.env ...
if exist "backend\.env" (
    echo backend\.env already exists - kept as is.
) else (
    copy "backend\.env.example" "backend\.env" >nul
    echo Created backend\.env from .env.example  ^(edit passwords/keys if needed^)
)
echo.

REM ---------- optional: MySQL DB + demo data ----------
where mysql >nul 2>nul
if errorlevel 1 (
    echo [INFO] "mysql" command not found on PATH - skipping DB setup.
    echo        Run backend\sql\schema.sql in MySQL Workbench, then:
    echo        cd backend  ^&^&  .venv\Scripts\python.exe seed.py --demo
    goto :done
)
set "ANS="
set /p ANS="Create MySQL database/user and load demo data now? (y/n) "
if /i not "%ANS%"=="y" goto :done
echo Enter the MySQL ROOT password when asked.
mysql -u root -p < backend\sql\schema.sql
if errorlevel 1 (
    echo [WARN] DB creation failed. Check that MySQL is running and the root password.
    goto :done
)
pushd backend
.venv\Scripts\python.exe seed.py --demo
popd

:done
echo.
echo ============================================================
echo   Install finished.
echo   Start servers : start.bat
echo   Run tests     : test.bat
echo   Login         : admin / admin1234
echo ============================================================
echo.
pause
exit /b 0

:fail
echo.
echo ============================================================
echo   Install FAILED. Read the message above.
echo   Troubleshooting: docs\SETUP.md  (section 11)
echo ============================================================
echo.
pause
exit /b 1
