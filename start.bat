@echo off
setlocal EnableDelayedExpansion
title Flowsmith — Starting...

:: ============================================================
:: ONE-CLICK STARTUP
:: Double-click this file to start the entire platform.
:: ============================================================

:: --- Resolve project root from this script's location ---
set "ROOT=%~dp0"
cd /d "%ROOT%"

:: --- Load .env if present ---
if exist "%ROOT%.env" (
    echo    Loading .env...
    for /f "usebackq tokens=1,* delims==" %%a in ("%ROOT%.env") do (
        set "LINE=%%a"
        if not "!LINE:~0,1!"=="#" if "%%b" neq "" set "%%a=%%b"
    )
)

:: --- Load backend .env (Salesforce credentials, SSRF bypass) ---
if exist "%ROOT%backend\.env" (
    echo    Loading backend\.env...
    for /f "usebackq tokens=1,* delims==" %%a in ("%ROOT%backend\.env") do (
        set "LINE=%%a"
        if not "!LINE:~0,1!"=="#" if "%%b" neq "" set "%%a=%%b"
    )
)

:: --- Configuration ---
if not defined BACKEND_PORT set "BACKEND_PORT=8000"
if not defined FRONTEND_PORT set "FRONTEND_PORT=5173"
if not defined POSTGRES_PORT set "POSTGRES_PORT=5432"
if not defined REDIS_PORT set "REDIS_PORT=6379"
if not defined BACKEND_HOST set "BACKEND_HOST=0.0.0.0"
if not defined FRONTEND_HOST set "FRONTEND_HOST=0.0.0.0"

:: --- Python & Alembic detection ---
set "VENV_PY=%ROOT%.venv\Scripts\python.exe"
set "VENV_ALEMBIC=%ROOT%.venv\Scripts\alembic.exe"
if not exist "%VENV_PY%" (
    set "VENV_PY=python"
    set "VENV_ALEMBIC=alembic"
)

:: --- PID file directory for clean shutdown ---
if not exist "%ROOT%.runtime" mkdir "%ROOT%.runtime"

echo.
echo ============================================================
echo   FLOWSMITH — STARTING
echo ============================================================
echo.

:: ============================================================
:: STEP 1: Check Prerequisites
:: ============================================================
echo [1/9] Checking prerequisites...

:: Check Docker
where docker >nul 2>&1
if errorlevel 1 (
    echo.
    echo ERROR: Docker is not installed or not on PATH.
    echo Please install Docker Desktop: https://docker.com/products/docker-desktop
    echo.
    pause
    exit /b 1
)

:: Check Docker Compose (docker compose plugin)
docker compose version >nul 2>&1
if errorlevel 1 (
    echo.
    echo ERROR: Docker Compose is not available.
    echo Please update Docker Desktop to the latest version.
    echo.
    pause
    exit /b 1
)

:: Check Node.js
where node >nul 2>&1
if errorlevel 1 (
    echo.
    echo ERROR: Node.js is not installed or not on PATH.
    echo Please install Node.js: https://nodejs.org
    echo.
    pause
    exit /b 1
)

:: Check npm
where npm >nul 2>&1
if errorlevel 1 (
    echo.
    echo ERROR: npm is not installed.
    echo Please reinstall Node.js from https://nodejs.org
    echo.
    pause
    exit /b 1
)

:: Check Python
where python >nul 2>&1
if errorlevel 1 (
    echo.
    echo ERROR: Python is not installed or not on PATH.
    echo Please install Python 3.12+: https://python.org
    echo.
    pause
    exit /b 1
)

echo    Docker .............. OK
echo    Docker Compose ..... OK
echo    Node.js ............ OK
echo    Python ............. OK
echo.

:: ============================================================
:: STEP 2: Start Docker Engine (if Desktop is installed but stopped)
:: ============================================================
echo [2/9] Checking Docker engine...

docker info >nul 2>&1
if errorlevel 1 (
    echo    Docker engine is not running. Attempting to start Docker Desktop...

    set "DOCKER_DESKTOP="
    if exist "C:\Program Files\Docker\Docker\Docker Desktop.exe" (
        set "DOCKER_DESKTOP=C:\Program Files\Docker\Docker\Docker Desktop.exe"
    ) else if exist "%LOCALAPPDATA%\Programs\Docker\Docker\Docker Desktop.exe" (
        set "DOCKER_DESKTOP=%LOCALAPPDATA%\Programs\Docker\Docker\Docker Desktop.exe"
    )

    if defined DOCKER_DESKTOP (
        start "" "!DOCKER_DESKTOP!"
        echo    Waiting for Docker engine to become ready...
        set /a "RETRIES=0"
        :WAIT_DOCKER
        timeout /t 3 /nobreak >nul
        docker info >nul 2>&1
        if errorlevel 1 (
            set /a "RETRIES+=1"
            if !RETRIES! GEQ 40 (
                echo.
                echo ERROR: Docker engine did not start within 2 minutes.
                echo Please start Docker Desktop manually and try again.
                echo.
                pause
                exit /b 1
            )
            echo    ... waiting (!RETRIES!/40^)
            goto WAIT_DOCKER
        )
        echo    Docker engine is ready.
    ) else (
        echo.
        echo ERROR: Docker Desktop is installed but not running.
        echo Please start Docker Desktop manually and try again.
        echo.
        pause
        exit /b 1
    )
) else (
    echo    Docker engine is running.
)
echo.

:: ============================================================
:: STEP 3: Start Infrastructure (PostgreSQL + Redis)
:: ============================================================
echo [3/9] Starting infrastructure containers...

cd /d "%ROOT%"
docker compose up -d postgres redis
if errorlevel 1 (
    echo.
    echo ERROR: Failed to start Docker containers.
    echo Run: docker compose logs
    echo.
    pause
    exit /b 1
)
echo    PostgreSQL + Redis containers started.
echo.

:: ============================================================
:: STEP 4: Wait for Infrastructure Health
:: ============================================================
echo [4/9] Waiting for infrastructure to be ready...

:: Wait for PostgreSQL
echo    Waiting for PostgreSQL...
set /a "RETRIES=0"
:WAIT_PG
timeout /t 2 /nobreak >nul
docker exec mat-postgres pg_isready -U automate -d automate >nul 2>&1
if errorlevel 1 (
    set /a "RETRIES+=1"
    if !RETRIES! GEQ 30 (
        echo.
        echo ERROR: PostgreSQL did not become ready within 60 seconds.
        echo Check: docker logs mat-postgres
        echo.
        pause
        exit /b 1
    )
    goto WAIT_PG
)
echo    PostgreSQL ........... READY

:: Verify pgvector extension
docker exec mat-postgres psql -U automate -d automate -c "SELECT extname FROM pg_extension WHERE extname = 'vector';" 2>nul | findstr "vector" >nul 2>&1
if errorlevel 1 (
    echo    WARNING: pgvector extension not found. Installing...
    docker exec mat-postgres psql -U automate -d automate -c "CREATE EXTENSION IF NOT EXISTS vector;" >nul 2>&1
)
echo    pgvector ............ READY

:: Wait for Redis
echo    Waiting for Redis...
set /a "RETRIES=0"
:WAIT_REDIS
timeout /t 2 /nobreak >nul
docker exec mat-redis redis-cli ping 2>nul | findstr "PONG" >nul 2>&1
if errorlevel 1 (
    set /a "RETRIES+=1"
    if !RETRIES! GEQ 15 (
        echo.
        echo ERROR: Redis did not become ready within 30 seconds.
        echo Check: docker logs mat-redis
        echo.
        pause
        exit /b 1
    )
    goto WAIT_REDIS
)
echo    Redis ............... READY
echo.

:: ============================================================
:: STEP 5: Run Database Migrations
:: ============================================================
echo [5/9] Running database migrations...

cd /d "%ROOT%backend"
if not defined DATABASE_URL set "DATABASE_URL=postgresql://automate:automate@127.0.0.1:5432/automate"

:: Use venv Python explicitly (fixes 3.12 vs 3.13 mismatch)
set "VENV_PY=%ROOT%.venv\Scripts\python.exe"
set "VENV_ALEMBIC=%ROOT%.venv\Scripts\alembic.exe"
if not exist "%VENV_PY%" (
    echo    WARNING: No .venv found. Using system Python.
    echo    Run: python -m venv .venv ^&^& .venv\Scripts\activate.bat ^&^& pip install -r backend\requirements.txt
    set "VENV_PY=python"
    set "VENV_ALEMBIC=alembic"
)

:: Run Alembic migrations
"%VENV_PY%" -m alembic upgrade head
if errorlevel 1 (
    echo    Alembic migration had issues. Attempting create_all fallback...
    "%VENV_PY%" -c "from app.db import init_db; init_db()"
    if errorlevel 1 (
        echo.
        echo ERROR: Database migration failed.
        echo Check: docker logs mat-postgres
        echo.
        pause
        exit /b 1
    )
)
:: Verify Data Tables schema (DATA-TABLES-01)
"%VENV_PY%" -c "import sys; sys.path.insert(0, '.'); from app.models import DataTable, DataTableColumn, DataTableRow; print('Data Tables models OK')" 2>nul
if errorlevel 1 (
    echo    WARNING: Data Tables models not importable — check backend/app/models/data_table.py
) else (
    echo    Data Tables ......... READY
)
:: Clear Python cache
echo    Clearing Python cache...
for /d /r "%ROOT%backend" %%d in (__pycache__) do @if exist "%%d" rd /s /q "%%d" 2>nul
del /s /q "%ROOT%backend\*.pyc" 2>nul
echo    Python cache ........ CLEARED
echo    Migrations ........... DONE
echo.

:: ============================================================
:: STEP 6: Start Backend API
:: ============================================================
echo [6/9] Starting backend API...

:: Stop any previous backend or worker processes before starting fresh
taskkill /FI "WINDOWTITLE eq MAT-Backend" /F /T >nul 2>&1
taskkill /FI "WINDOWTITLE eq MAT-Worker" /F /T >nul 2>&1
taskkill /FI "WINDOWTITLE eq MAT-Frontend" /F /T >nul 2>&1
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object CommandLine -match 'app\.(serve|queue\.worker)' | Stop-Process -Force -ErrorAction SilentlyContinue" >nul 2>&1
for /f "tokens=5" %%p in ('netstat -aon 2^>nul ^| findstr ":%BACKEND_PORT%" ^| findstr "LISTENING"') do (
    taskkill /PID %%p /F >nul 2>&1
)
for /f "tokens=5" %%p in ('netstat -aon 2^>nul ^| findstr ":%FRONTEND_PORT%" ^| findstr "LISTENING"') do (
    taskkill /PID %%p /F >nul 2>&1
)
for /f "tokens=5" %%p in ('netstat -aon 2^>nul ^| findstr ":8181" ^| findstr "LISTENING"') do (
    taskkill /PID %%p /F >nul 2>&1
)

:: Write a temporary helper script (avoids && env-var trailing spaces)
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

:: Wait for backend to be ready
echo    Waiting for backend API...
set /a "RETRIES=0"
:WAIT_BACKEND
timeout /t 2 /nobreak >nul
curl -s http://127.0.0.1:%BACKEND_PORT%/api/health >nul 2>&1
if errorlevel 1 (
    set /a "RETRIES+=1"
    if !RETRIES! GEQ 30 (
        echo.
        echo ERROR: Backend API did not start within 60 seconds.
        echo Check the MAT-Backend window for errors.
        echo.
        pause
        exit /b 1
    )
    goto WAIT_BACKEND
)
echo    Backend API ......... READY on port %BACKEND_PORT%
echo.

:: ============================================================
:: STEP 7: Start Worker
:: ============================================================
echo [7/9] Starting worker...

:: Write a temporary helper script
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

:: Brief wait for worker startup
timeout /t 3 /nobreak >nul
echo    Worker .............. STARTED
echo.

:: ============================================================
:: STEP 8: Start Frontend Dev Server
:: ============================================================
echo [8/9] Starting frontend dev server...

cd /d "%ROOT%frontend"

:: Install dependencies if node_modules is missing
if not exist "%ROOT%frontend\node_modules" (
    echo    Installing frontend dependencies...
    cd /d "%ROOT%frontend"
    call npm ci
    if errorlevel 1 (
        echo.
        echo ERROR: Frontend dependency installation failed.
        echo.
        pause
        exit /b 1
    )
)

:: Write a temporary helper script (same pattern as backend/worker)
set "FRONTEND_LAUNCHER=%ROOT%.runtime\start_frontend.cmd"
(
    echo @echo off
    echo title MAT-Frontend
    echo cd /d "%ROOT%frontend"
    echo call npx vite --host %FRONTEND_HOST% --port %FRONTEND_PORT%
    echo if errorlevel 1 pause
) > "!FRONTEND_LAUNCHER!"

start "MAT-Frontend" cmd /c "!FRONTEND_LAUNCHER!"

:: Wait for frontend to be ready
echo    Waiting for frontend...
set /a "RETRIES=0"
:WAIT_FRONTEND
timeout /t 2 /nobreak >nul
curl -s http://127.0.0.1:%FRONTEND_PORT%/ >nul 2>&1
if errorlevel 1 (
    set /a "RETRIES+=1"
    if !RETRIES! GEQ 20 (
        echo.
        echo ERROR: Frontend did not start within 40 seconds.
        echo Check the MAT-Frontend window for errors.
        echo.
        pause
        exit /b 1
    )
    goto WAIT_FRONTEND
)
echo    Frontend ............ READY on port %FRONTEND_PORT%
echo.

:: ============================================================
:: STEP 9: Health Check + Display
:: ============================================================
echo [9/9] Running health checks...
echo.

:: Detect LAN IP
set "LAN_IP="
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /i "IPv4" ^| findstr /v "127.0.0.1"') do (
    set "RAW_IP=%%a"
    set "RAW_IP=!RAW_IP: =!"
    if not defined LAN_IP set "LAN_IP=!RAW_IP!"
)

:: Backend health check
set "BACKEND_STATUS=FAIL"
curl -s http://127.0.0.1:%BACKEND_PORT%/api/health 2>nul | findstr "\"ok\"" >nul 2>&1
if not errorlevel 1 set "BACKEND_STATUS=PASS"

:: Ready check
set "READY_STATUS=FAIL"
curl -s http://127.0.0.1:%BACKEND_PORT%/api/readyz 2>nul | findstr "\"ready\"" >nul 2>&1
if not errorlevel 1 set "READY_STATUS=PASS"

:: Frontend check
set "FRONTEND_STATUS=FAIL"
curl -s http://127.0.0.1:%FRONTEND_PORT%/ 2>nul | findstr "root" >nul 2>&1
if not errorlevel 1 set "FRONTEND_STATUS=PASS"

echo ============================================================
echo   FLOWSMITH — READY
echo ============================================================
echo.
echo   Application URLs:
echo.
echo     Local:     http://localhost:%FRONTEND_PORT%
if defined LAN_IP (
echo     Network:   http://!LAN_IP!:%FRONTEND_PORT%
)
echo     API:       http://localhost:%BACKEND_PORT%/api/health
if defined LAN_IP (
echo     API [LAN]: http://!LAN_IP!:%BACKEND_PORT%/api/health
)
echo.
echo   Service Status:
echo.
echo     Backend API ......... %BACKEND_STATUS%  (port %BACKEND_PORT%)
echo     Frontend ............ %FRONTEND_STATUS%  (port %FRONTEND_PORT%)
echo     PostgreSQL .......... PASS  (port %POSTGRES_PORT%)
echo     pgvector ............ PASS
echo     Redis ............... PASS  (port %REDIS_PORT%)
echo     Ready Check ......... %READY_STATUS%
echo.
echo   Process Windows:
echo     MAT-Backend   — Backend API logs
echo     MAT-Worker    — Worker process logs
echo     MAT-Frontend  — Frontend dev server logs
echo.
echo   To stop: run stop.bat
echo   Or press Ctrl+C in each process window.
echo.
echo ============================================================

:: Save port info for stop.bat
echo %BACKEND_PORT% > "%ROOT%.runtime\backend.port"
echo %FRONTEND_PORT% > "%ROOT%.runtime\frontend.port"

:: Keep window open
echo.
echo Press any key to close this window (services will keep running)...
pause >nul
