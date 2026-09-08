@echo off
setlocal EnableDelayedExpansion
title Flowsmith — Stopping...

:: ============================================================
:: ONE-CLICK SHUTDOWN
:: Safely stops all services. Preserves data volumes.
:: ============================================================

set "ROOT=%~dp0"
cd /d "%ROOT%"

:: --- Load .env if present ---
if exist "%ROOT%.env" (
    for /f "usebackq tokens=1,* delims==" %%a in ("%ROOT%.env") do (
        set "LINE=%%a"
        if not "!LINE:~0,1!"=="#" if "%%b" neq "" set "%%a=%%b"
    )
)

:: --- Load backend .env if present ---
if exist "%ROOT%backend\.env" (
    for /f "usebackq tokens=1,* delims==" %%a in ("%ROOT%backend\.env") do (
        set "LINE=%%a"
        if not "!LINE:~0,1!"=="#" if "%%b" neq "" set "%%a=%%b"
    )
)

:: --- Configuration (read saved runtime ports or default to 8000 / 5173) ---
set "BACKEND_PORT=8000"
set "FRONTEND_PORT=5173"
if exist "%ROOT%.runtime\backend.port" (
    set /p BACKEND_PORT=<"%ROOT%.runtime\backend.port"
    set "BACKEND_PORT=!BACKEND_PORT: =!"
)
if exist "%ROOT%.runtime\frontend.port" (
    set /p FRONTEND_PORT=<"%ROOT%.runtime\frontend.port"
    set "FRONTEND_PORT=!FRONTEND_PORT: =!"
)

echo.
echo ============================================================
echo   FLOWSMITH — STOPPING
echo ============================================================
echo.

:: ============================================================
:: STEP 1: Stop application processes
:: ============================================================
echo [1/3] Stopping application processes...

:: Kill backend process and window
taskkill /FI "WINDOWTITLE eq MAT-Backend" /F /T >nul 2>&1
echo    Backend window ...... STOPPED

:: Kill worker process and window
taskkill /FI "WINDOWTITLE eq MAT-Worker" /F /T >nul 2>&1
echo    Worker window ....... STOPPED

:: Kill frontend dev server and window
taskkill /FI "WINDOWTITLE eq MAT-Frontend" /F /T >nul 2>&1
echo    Frontend window ..... STOPPED

:: Kill underlying Python processes (app.serve and app.queue.worker)
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object CommandLine -match 'app\.(serve|queue\.worker)' | Stop-Process -Force -ErrorAction SilentlyContinue" >nul 2>&1
echo    Python processes .... STOPPED

:: Kill any lingering node/vite processes on the frontend port
for /f "tokens=5" %%p in ('netstat -aon 2^>nul ^| findstr ":%FRONTEND_PORT%" ^| findstr "LISTENING"') do (
    taskkill /PID %%p /F >nul 2>&1
)

:: Kill any lingering python processes on the backend port
for /f "tokens=5" %%p in ('netstat -aon 2^>nul ^| findstr ":%BACKEND_PORT%" ^| findstr "LISTENING"') do (
    taskkill /PID %%p /F >nul 2>&1
)

:: Kill any lingering SF stub server on port 8181
for /f "tokens=5" %%p in ('netstat -aon 2^>nul ^| findstr ":8181" ^| findstr "LISTENING"') do (
    taskkill /PID %%p /F >nul 2>&1
)
echo    Port listeners ...... STOPPED

echo.

:: ============================================================
:: STEP 2: Stop Docker Compose services (app + worker containers)
:: ============================================================
echo [2/3] Stopping Docker containers...

cd /d "%ROOT%"
docker compose stop app worker 2>nul
echo    App container ....... STOPPED
echo    Worker container .... STOPPED
echo    PostgreSQL .......... still running (use "docker compose down" to stop)
echo    Redis ............... still running (use "docker compose down" to stop)
echo.

:: ============================================================
:: STEP 3: Cleanup
:: ============================================================
echo [3/3] Cleaning up runtime files...
if exist "%ROOT%.runtime" (
    del /q "%ROOT%.runtime\*" 2>nul
    echo    Runtime files ....... CLEANED
)

echo.
echo ============================================================
echo   ALL SERVICES STOPPED
echo ============================================================
echo.
echo   Infrastructure (PostgreSQL, Redis) is still running.
echo   Data volumes are preserved.
echo.
echo   To fully stop everything:
echo     docker compose down
echo.
echo   To stop and delete all data:
echo     docker compose down -v
echo.
echo ============================================================

echo.
echo Press any key to close...
pause >nul
