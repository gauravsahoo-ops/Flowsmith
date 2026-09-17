@echo off
setlocal EnableDelayedExpansion
title Flowsmith — Restarting...

:: ============================================================
:: ONE-CLICK RESTART
:: Stops all services, then starts them again.
:: Preserves data volumes.
:: ============================================================

set "ROOT=%~dp0"
cd /d "%ROOT%"

:: --- Python & Alembic detection ---
set "VENV_PY=%ROOT%.venv\Scripts\python.exe"
set "VENV_ALEMBIC=%ROOT%.venv\Scripts\alembic.exe"
if not exist "%VENV_PY%" (
    set "VENV_PY=python"
    set "VENV_ALEMBIC=alembic"
)

:: --- Load .env if present ---
if exist "%ROOT%.env" (
    for /f "usebackq tokens=1,* delims==" %%a in ("%ROOT%.env") do (
        set "LINE=%%a"
        if not "!LINE:~0,1!"=="#" if "%%b" neq "" set "%%a=%%b"
    )
)

:: --- Load backend .env (Salesforce credentials, SSRF bypass) ---
if exist "%ROOT%backend\.env" (
    for /f "usebackq tokens=1,* delims==" %%a in ("%ROOT%backend\.env") do (
        set "LINE=%%a"
        if not "!LINE:~0,1!"=="#" if "%%b" neq "" set "%%a=%%b"
    )
)

:: --- Configuration (read saved runtime ports or default to 8000 / 5173) ---
if not defined BACKEND_PORT set "BACKEND_PORT=8000"
if not defined FRONTEND_PORT set "FRONTEND_PORT=5173"
if not defined BACKEND_HOST set "BACKEND_HOST=0.0.0.0"
if not defined FRONTEND_HOST set "FRONTEND_HOST=0.0.0.0"
if exist "%ROOT%.runtime\backend.port" (
    set /p SAVED_BACKEND_PORT=<"%ROOT%.runtime\backend.port"
    set "SAVED_BACKEND_PORT=!SAVED_BACKEND_PORT: =!"
    if "!SAVED_BACKEND_PORT!" neq "" set "BACKEND_PORT=!SAVED_BACKEND_PORT!"
)
if exist "%ROOT%.runtime\frontend.port" (
    set /p SAVED_FRONTEND_PORT=<"%ROOT%.runtime\frontend.port"
    set "SAVED_FRONTEND_PORT=!SAVED_FRONTEND_PORT: =!"
    if "!SAVED_FRONTEND_PORT!" neq "" set "FRONTEND_PORT=!SAVED_FRONTEND_PORT!"
)

if not exist "%ROOT%.runtime" mkdir "%ROOT%.runtime"

echo.
echo ============================================================
echo   FLOWSMITH — RESTARTING
echo ============================================================
echo.

:: ============================================================
:: STEP 1: Stop all services (non-interactive)
:: ============================================================
echo [1/2] Stopping services...

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

:: Kill any lingering processes on known ports
for /f "tokens=5" %%p in ('netstat -aon 2^>nul ^| findstr ":%BACKEND_PORT%" ^| findstr "LISTENING"') do (
    taskkill /PID %%p /F >nul 2>&1
)
for /f "tokens=5" %%p in ('netstat -aon 2^>nul ^| findstr ":%FRONTEND_PORT%" ^| findstr "LISTENING"') do (
    taskkill /PID %%p /F >nul 2>&1
)
for /f "tokens=5" %%p in ('netstat -aon 2^>nul ^| findstr ":8181" ^| findstr "LISTENING"') do (
    taskkill /PID %%p /F >nul 2>&1
)
echo    Port listeners ...... STOPPED

:: Stop Docker app/worker containers
docker compose stop app worker 2>nul
echo    Docker containers ... STOPPED

:: Cleanup runtime files
if exist "%ROOT%.runtime" del /q "%ROOT%.runtime\*" 2>nul

echo.
echo    Waiting for services to fully stop...
timeout /t 3 /nobreak >nul
echo.

:: ============================================================
:: STEP 2: Start all services
:: ============================================================
echo [2/2] Starting services...
echo.

:: Ensure Docker infrastructure is up
echo    Ensuring infrastructure...
cd /d "%ROOT%"
docker compose up -d postgres redis 2>nul

:: Wait for PostgreSQL
set /a "RETRIES=0"
:RESTART_WAIT_PG
timeout /t 2 /nobreak >nul
docker exec mat-postgres pg_isready -U automate -d automate >nul 2>&1
if errorlevel 1 (
    set /a "RETRIES+=1"
    if !RETRIES! GEQ 30 (
        echo    ERROR: PostgreSQL not ready. Aborting.
        pause
        exit /b 1
    )
    goto RESTART_WAIT_PG
)
echo    PostgreSQL .......... READY

:: Verify pgvector extension
docker exec mat-postgres psql -U automate -d automate -c "SELECT extname FROM pg_extension WHERE extname = 'vector';" 2>nul | findstr "vector" >nul 2>&1
if errorlevel 1 (
    echo    Installing pgvector extension...
    docker exec mat-postgres psql -U automate -d automate -c "CREATE EXTENSION IF NOT EXISTS vector;" >nul 2>&1
)
echo    pgvector ............ READY

:: Wait for Redis
set /a "RETRIES=0"
:RESTART_WAIT_REDIS
timeout /t 2 /nobreak >nul
docker exec mat-redis redis-cli ping 2>nul | findstr "PONG" >nul 2>&1
if errorlevel 1 (
    set /a "RETRIES+=1"
    if !RETRIES! GEQ 15 (
        echo    ERROR: Redis not ready. Aborting.
        pause
        exit /b 1
    )
    goto RESTART_WAIT_REDIS
)
echo    Redis ............... READY

:: Run migrations with fallback
cd /d "%ROOT%backend"
"%VENV_PY%" -m alembic upgrade head 2>nul
if errorlevel 1 "%VENV_ALEMBIC%" upgrade head 2>nul
if errorlevel 1 (
    echo    Alembic migration had issues. Attempting create_all fallback...
    "%VENV_PY%" -c "from app.db import init_db; init_db()"
    if errorlevel 1 (
        echo.
        echo ERROR: Database migration failed.
        pause
        exit /b 1
    )
)
"%VENV_PY%" -c "import sys; sys.path.insert(0, '.'); from app.models import DataTable, DataTableColumn, DataTableRow; print('Data Tables OK')" 2>nul
if errorlevel 1 (
    echo    WARNING: Data Tables not ready
) else (
    echo    Data Tables ......... READY
)
:: Clear Python cache
echo    Clearing Python cache...
for /d /r "%ROOT%backend" %%d in (__pycache__) do @if exist "%%d" rd /s /q "%%d" 2>nul
del /s /q "%ROOT%backend\*.pyc" 2>nul
echo    Python cache ........ CLEARED
echo    Migrations .......... DONE

:: Start backend
set "BACKEND_LAUNCHER=%ROOT%.runtime\start_backend.cmd"
(
    echo @echo off
    echo title MAT-Backend
    echo cd /d "%ROOT%backend"
    echo set HOST=%BACKEND_HOST%
    echo set PORT=%BACKEND_PORT%
    echo set APP_ENV=development
    echo set CORS_ORIGINS=http://localhost:%FRONTEND_PORT%,http://127.0.0.1:%FRONTEND_PORT%,http://localhost:8000,http://127.0.0.1:8000
    echo set PUBLIC_URL=http://localhost:%FRONTEND_PORT%
    echo set DATABASE_URL=postgresql://automate:automate@127.0.0.1:5432/automate
    echo set QUEUE_BACKEND=redis
    echo set REDIS_URL=redis://127.0.0.1:6379/0
    echo set QUEUE_EMBEDDED_CONSUMER=false
    echo set SERVE_FRONTEND=true
    echo set SAFE_HTTP_ALLOWED_HOSTS=%SAFE_HTTP_ALLOWED_HOSTS%
    echo set SAFE_HTTP_ALLOWED_PORTS=%SAFE_HTTP_ALLOWED_PORTS%
    echo set SALESFORCE_CLIENT_ID=%SALESFORCE_CLIENT_ID%
    echo set SALESFORCE_CLIENT_SECRET=%SALESFORCE_CLIENT_SECRET%
    echo set SALESFORCE_REDIRECT_URI=%SALESFORCE_REDIRECT_URI%
    echo set SALESFORCE_LOGIN_URL=%SALESFORCE_LOGIN_URL%
    echo set SALESFORCE_API_VERSION=%SALESFORCE_API_VERSION%
    echo set SALESFORCE_SCOPES=%SALESFORCE_SCOPES%
    echo set JWT_SECRET=%JWT_SECRET%
    echo set CREDENTIALS_ENCRYPTION_KEY=%CREDENTIALS_ENCRYPTION_KEY%
    echo "!VENV_PY!" -m app.serve
    echo if errorlevel 1 pause
) > "!BACKEND_LAUNCHER!"
start "MAT-Backend" cmd /c "!BACKEND_LAUNCHER!"

:: Wait for backend
set /a "RETRIES=0"
:RESTART_WAIT_BACKEND
timeout /t 2 /nobreak >nul
curl -s http://127.0.0.1:%BACKEND_PORT%/api/health >nul 2>&1
if errorlevel 1 (
    set /a "RETRIES+=1"
    if !RETRIES! GEQ 30 (
        echo    ERROR: Backend did not start. Check MAT-Backend window.
        pause
        exit /b 1
    )
    goto RESTART_WAIT_BACKEND
)
echo    Backend API ......... READY on port %BACKEND_PORT%

:: Start worker
set "WORKER_LAUNCHER=%ROOT%.runtime\start_worker.cmd"
(
    echo @echo off
    echo title MAT-Worker
    echo cd /d "%ROOT%backend"
    echo set DATABASE_URL=postgresql://automate:automate@127.0.0.1:5432/automate
    echo set QUEUE_BACKEND=redis
    echo set REDIS_URL=redis://127.0.0.1:6379/0
    echo set QUEUE_EMBEDDED_CONSUMER=false
    echo set SAFE_HTTP_ALLOWED_HOSTS=%SAFE_HTTP_ALLOWED_HOSTS%
    echo set SAFE_HTTP_ALLOWED_PORTS=%SAFE_HTTP_ALLOWED_PORTS%
    echo set SALESFORCE_CLIENT_ID=%SALESFORCE_CLIENT_ID%
    echo set SALESFORCE_CLIENT_SECRET=%SALESFORCE_CLIENT_SECRET%
    echo set SALESFORCE_REDIRECT_URI=%SALESFORCE_REDIRECT_URI%
    echo set SALESFORCE_LOGIN_URL=%SALESFORCE_LOGIN_URL%
    echo set SALESFORCE_API_VERSION=%SALESFORCE_API_VERSION%
    echo set SALESFORCE_SCOPES=%SALESFORCE_SCOPES%
    echo set JWT_SECRET=%JWT_SECRET%
    echo set CREDENTIALS_ENCRYPTION_KEY=%CREDENTIALS_ENCRYPTION_KEY%
    echo "!VENV_PY!" -m app.queue.worker
    echo if errorlevel 1 pause
) > "!WORKER_LAUNCHER!"
start "MAT-Worker" cmd /c "!WORKER_LAUNCHER!"
timeout /t 3 /nobreak >nul
echo    Worker .............. STARTED

:: Start frontend
echo    Starting frontend dev server...
cd /d "%ROOT%frontend"
if not exist "%ROOT%frontend\node_modules" call npm ci >nul 2>&1

set "FRONTEND_LAUNCHER=%ROOT%.runtime\start_frontend.cmd"
(
    echo @echo off
    echo title MAT-Frontend
    echo cd /d "%ROOT%frontend"
    echo call npx vite --host %FRONTEND_HOST% --port %FRONTEND_PORT%
    echo if errorlevel 1 pause
) > "!FRONTEND_LAUNCHER!"
start "MAT-Frontend" cmd /c "!FRONTEND_LAUNCHER!"

:: Wait for frontend
set /a "RETRIES=0"
:RESTART_WAIT_FRONTEND
timeout /t 2 /nobreak >nul
curl -s http://127.0.0.1:%FRONTEND_PORT%/ >nul 2>&1
if errorlevel 1 (
    set /a "RETRIES+=1"
    if !RETRIES! GEQ 20 (
        echo    ERROR: Frontend did not start. Check MAT-Frontend window.
        pause
        exit /b 1
    )
    goto RESTART_WAIT_FRONTEND
)
echo    Frontend ............ READY on port %FRONTEND_PORT%

:: Save port info
echo %BACKEND_PORT% > "%ROOT%.runtime\backend.port"
echo %FRONTEND_PORT% > "%ROOT%.runtime\frontend.port"

:: Detect LAN IP
set "LAN_IP="
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /i "IPv4" ^| findstr /v "127.0.0.1"') do (
    set "RAW_IP=%%a"
    set "RAW_IP=!RAW_IP: =!"
    if not defined LAN_IP set "LAN_IP=!RAW_IP!"
)

echo.
echo ============================================================
echo   FLOWSMITH — RESTARTED
echo ============================================================
echo.
echo     Local:     http://localhost:%FRONTEND_PORT%
if defined LAN_IP (
echo     Network:   http://!LAN_IP!:%FRONTEND_PORT%
)
echo     API:       http://localhost:%BACKEND_PORT%/api/health
echo.
echo   Process Windows:
echo     MAT-Backend   — Backend API logs
echo     MAT-Worker    — Worker process logs
echo     MAT-Frontend  — Frontend dev server logs
echo.
echo ============================================================
echo.
echo Press any key to close this window (services will keep running)...
pause >nul
