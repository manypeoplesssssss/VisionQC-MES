@echo off
REM ============================================================
REM  VisionQC AI MES - run all tests (Windows)
REM  test.bat                      : backend + vision client
REM  test.bat tests\test_ingest.py : one backend test file (extra args go to pytest)
REM ============================================================
setlocal
cd /d "%~dp0"
if not exist "backend\.venv\Scripts\python.exe" (
    echo [ERROR] Run install.bat first.
    pause
    exit /b 1
)

REM (no parentheses blocks here: %ERRORLEVEL% inside a block is read too early)
if "%~1"=="" goto :all
pushd backend
.venv\Scripts\python.exe -m pytest %*
set "RC=%ERRORLEVEL%"
popd
exit /b %RC%

:all
echo ===== backend tests =====
pushd backend
.venv\Scripts\python.exe -m pytest -q
set "RC1=%ERRORLEVEL%"
popd

echo.
echo ===== vision client tests =====
pushd vision_client
..\backend\.venv\Scripts\python.exe -m pytest -q
set "RC2=%ERRORLEVEL%"
popd

echo.
if "%RC1%%RC2%"=="00" (
    echo ALL TESTS PASSED
) else (
    echo SOME TESTS FAILED - see output above
)
pause
