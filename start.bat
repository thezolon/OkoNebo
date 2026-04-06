@echo off
:: start.bat — start OkoNebo (Windows)
:: Requires: Docker Desktop with the Compose plugin
:: No Python required on the host.

if /I "%~1"=="--check" (
    echo start.bat syntax check OK
    exit /b 0
)

cd /d "%~dp0"

:: Touch persistence files so Docker bind-mounts get regular files, not dirs.
if not exist secure_settings.db type nul > secure_settings.db
if not exist cache.db type nul > cache.db

echo Starting OkoNebo...
docker compose up -d --build --remove-orphans
if errorlevel 1 (
    echo ERROR: docker compose failed. Is Docker Desktop running?
    pause
    exit /b 1
)

echo.
echo   Dashboard : http://localhost:8888
echo   API docs  : http://localhost:8888/docs
echo.

:: Simple health check — retry up to 5 times
set ATTEMPTS=0
:healthloop
set /a ATTEMPTS+=1
curl -sf http://localhost:8888/api/bootstrap >nul 2>&1
if not errorlevel 1 (
    echo Container is ready.
    goto done
)
if %ATTEMPTS% GEQ 5 (
    echo Container did not become healthy in time. Check logs:
    echo   docker compose logs okonebo
    pause
    exit /b 1
)
echo Waiting for container to be ready ^(attempt %ATTEMPTS%/5^)...
timeout /t 3 /nobreak >nul
goto healthloop

:done
echo.
echo OkoNebo is running. Open http://localhost:8888 in your browser.
